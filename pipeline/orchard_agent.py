"""``ask_orchard_advisor()`` -- the Track 1 free-form Q&A agent (design doc Sec A.6/B.5,
Fase 2/3 "vraagbank"). Mirrors the shape of Auto Pilot's ``ask_captain()``/``ask_chief_engineer()``
(RAG context + optional ReACT tool-calling + CoT), adapted for open question-answering instead
of a fixed-candidate decision: there is no JSON decision contract here, just a grounded,
cited Dutch answer.

Pipeline per question:
  1. Always run one upfront knowledge-base search (the question itself as the query) -- Track 1
     grounding is not optional/elective the way tool calls are, same as Chief Engineer's RAG
     step always running when `spec["rag"]` is set.
  2. Build a system+user prompt: persona, grounding/compliance rules, the retrieved excerpts,
     and (if a tool catalog is given) the ReACT tool-call protocol.
  3. Call the cloud Qwen3-8B server with ``enable_thinking=True`` -- Qwen3's native chain-of-
     thought (``<think>...</think>``) is used directly instead of a hand-rolled COT_INSTR
     prompt trick (Auto Pilot's own domains needed the latter because their base checkpoints
     don't expose a native thinking mode the same way; Qwen3 does, so use it).
  4. Parse the reply: either a `{"call_tool": ..., "args": ...}` request (execute it, append the
     result as a new user turn, loop -- up to `max_tool_hops`) or a final plain-text answer.
  5. Return the answer, the extracted reasoning trace (for an optional "Redenering" expander in
     the UI), every tool call made, and a deduped source list for a "Bronnen:" footer.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pipeline.orchard_rag import RagIndex
from pipeline.orchard_tool_catalog import BoundTool, build_tool_catalog
from pipeline.qwen_remote import generate_remote

SYSTEM_PROMPT = (
    "Je bent een Nederlandstalige adviseur voor een kersenteler (zoete kers, Prunus avium). "
    "Antwoord kort, praktisch en in het Nederlands. Baseer feitelijke uitspraken ALTIJD op de "
    "aangeleverde kennisbank-fragmenten of tool-resultaten -- verzin nooit een getal, dosering of "
    "middelnaam. Als iets niet in de aangeleverde informatie staat, zeg dat expliciet in plaats "
    "van te gokken. Noem nooit een concreet gewasbeschermingsmiddel of dosering als harde "
    "aanbeveling -- verwijs daarvoor naar de ctgb_toelating-tool/Ctgb-databank. Sluit je antwoord "
    "af met een regel 'Bronnen: ...' die de gebruikte fragmenten/tools noemt."
)

TOOL_CALL_INSTR = (
    "Je mag voordat je antwoordt optioneel extra feiten ophalen door EEN tool per beurt aan te "
    "roepen (maximaal {max_hops} aanroepen in totaal):\n{tool_list}\n\n"
    'Om een tool aan te roepen, antwoord dan met UITSLUITEND dit JSON-object: '
    '{{"call_tool": "<tool naam>", "args": "<eventueel argument, of null>"}}\n'
    "Als je klaar bent (of geen tool nodig hebt), antwoord dan gewoon met je definitieve "
    "antwoord in platte tekst (GEEN JSON)."
)


@dataclass
class AdvisorResponse:
    answer: str
    reasoning: str = ""
    tool_calls: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    grounding: str = "red"  # "green" | "red" -- see assess_grounding()


def _strip_think(text: str) -> tuple[str, str]:
    """Returns (reasoning, remainder) -- Qwen3's <think>...</think> block extracted out, so
    the remainder can be parsed as either a tool call or the final answer.

    If generation was cut off (`max_new_tokens` reached) before the model finished its own
    thinking, `<think>` has no matching `</think>` yet -- returning the still-open block as
    `remainder` would leak raw, half-finished reasoning as if it were the answer. Treat that
    case as "no answer yet" instead (empty remainder): the caller's normal "no tool call ->
    use remainder as the answer" path then correctly reports nothing usable came back,
    rather than showing broken CoT text to the farmer."""
    m = re.search(r"<think>(.*?)</think>", text, re.DOTALL)
    if m:
        reasoning = m.group(1).strip()
        remainder = (text[:m.start()] + text[m.end():]).strip()
        return reasoning, remainder
    if "<think>" in text:
        return text.split("<think>", 1)[1].strip(), ""
    return "", text.strip()


def _extract_tool_call(remainder: str) -> dict | None:
    """Returns {"call_tool": ..., "args": ...} if `remainder` is (only) a legal tool-call JSON
    object, else None (meaning: treat `remainder` as the final plain-text answer instead)."""
    cleaned = re.sub(r"^```(json)?|```$", "", remainder.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and "call_tool" in obj:
        return obj
    return None


def _dedup(items: list[str]) -> list[str]:
    seen, out = set(), []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def build_history_messages(turns: list[tuple[str, str]]) -> list[dict]:
    """Pure: converts a flat ``[(role, text), ...]`` conversation log (oldest first, e.g. the
    Streamlit page's own chat history) into the ``[{"role": ..., "content": ...}, ...]`` shape
    `ask_orchard_advisor()`'s `history` argument expects. Strips the UI-only disclaimer note
    (the italic "*Let op: ...*" line the chat page appends to every LLM answer, see
    `app/pages/2_Vraag_de_Adviseur.py`) from assistant turns before re-feeding them back to the
    model -- no point spending tokens on the model re-reading its own boilerplate warning."""
    messages = []
    for role, text in turns:
        if role == "assistant":
            text = re.split(r"\n\n\*Let op:", text)[0].strip()
        messages.append({"role": role, "content": text})
    return messages


def assess_grounding(answer: str, sources: list[str], tool_calls: list[str]) -> str:
    """Returns "green" or "red" -- a HEURISTIC indicator of whether `answer` appears to
    actually use the sources/tool results that were available, rather than ignoring them and
    asserting something freely (design doc Deel F #12 -- this is NOT a factual-correctness
    check, only a "did it cite what it had" check). "green" requires BOTH (a) at least one
    source or tool call was available this turn, AND (b) the answer text itself references a
    citation (contains "bron(nen):" or literally names one of the tools that were called) --
    a response that HAD sources available but never mentions them in its own text still comes
    back "red" (the model may simply have ignored its own context)."""
    if not sources and not tool_calls:
        return "red"
    text_lower = answer.lower()
    if "bronnen:" in text_lower or "bron:" in text_lower:
        return "green"
    if any(tc.lower() in text_lower for tc in tool_calls):
        return "green"
    return "red"


def ask_orchard_advisor(
    question: str, ctx, snapshot: dict | None = None, rag_index: RagIndex | None = None,
    max_tool_hops: int = 3, max_new_tokens: int = 700,
    history: list[dict] | None = None, max_history_turns: int = 4,
) -> AdvisorResponse:
    """Builds the prompt, runs the (optional) ReACT tool-call loop, and returns a grounded
    answer. Never raises on a reachable-but-confused model reply -- worst case, the raw model
    text is returned as the answer with an empty source list, same "always return something
    usable" posture as the rest of this project's LLM call sites.

    `history` (new, 2026-10-09): prior turns of the SAME conversation, as
    ``[{"role": "user"|"assistant", "content": ...}, ...]`` oldest-first -- lets the model
    answer follow-up questions ("en hoe zit dat met ...?") with real context instead of
    treating every question as a fresh, isolated one. Capped to the last
    `max_history_turns` EXCHANGES (so `2 * max_history_turns` messages) to keep the prompt
    within the server's token budget -- older turns are silently dropped, newest first."""
    from pipeline.orchard_rag import format_context, format_sources, retrieve

    sources: list[str] = []
    if rag_index is not None:
        hits = retrieve(question, rag_index, k=6)
        context_block = format_context(hits)
        sources.extend(format_sources(hits))
    else:
        context_block = "(kennisbank-index nog niet gebouwd)"

    tool_catalog: dict[str, BoundTool] = build_tool_catalog(ctx, snapshot, rag_index)
    tool_list_text = "\n".join(f"- {t.name}: {t.description}" for t in tool_catalog.values())
    tool_instr = TOOL_CALL_INSTR.format(max_hops=max_tool_hops, tool_list=tool_list_text)

    user_msg = (
        f"Vraag: {question}\n\n"
        f"Relevante kennisbank-fragmenten:\n{context_block}\n\n"
        f"{tool_instr}"
    )
    capped_history = (history or [])[-(2 * max_history_turns):]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *capped_history,
                {"role": "user", "content": user_msg}]

    reasoning_parts: list[str] = []
    tool_calls_made: list[str] = []

    for _hop in range(max_tool_hops + 1):
        raw = generate_remote(messages=messages, max_new_tokens=max_new_tokens, enable_thinking=True)
        reasoning, remainder = _strip_think(raw)
        if reasoning:
            reasoning_parts.append(reasoning)

        if not remainder:
            # Generation was cut off mid-<think> (max_new_tokens reached before the model
            # got to its actual answer) -- one retry with a larger budget before giving up,
            # rather than silently returning an empty/broken-looking answer.
            raw = generate_remote(messages=messages, max_new_tokens=max_new_tokens * 2, enable_thinking=True)
            reasoning, remainder = _strip_think(raw)
            if reasoning:
                reasoning_parts.append(reasoning)

        tool_call = _extract_tool_call(remainder) if _hop < max_tool_hops else None
        if tool_call is None:
            final_answer = remainder or "(geen antwoord ontvangen -- het model had meer tokens nodig dan beschikbaar)"
            deduped_sources = _dedup(sources)
            return AdvisorResponse(
                answer=final_answer,
                reasoning="\n\n".join(reasoning_parts),
                tool_calls=tool_calls_made,
                sources=deduped_sources,
                grounding=assess_grounding(final_answer, deduped_sources, tool_calls_made),
            )

        name = tool_call.get("call_tool")
        tool = tool_catalog.get(name)
        messages.append({"role": "assistant", "content": remainder})
        if tool is None:
            messages.append({"role": "user", "content": f"Onbekende tool {name!r}. Kies een tool uit de lijst of geef je antwoord."})
            continue

        arg = tool_call.get("args")
        result = tool.fn(arg if isinstance(arg, str) else None)
        tool_calls_made.append(name)
        sources.extend(result.sources)
        messages.append({"role": "user", "content": f"Tool-resultaat ({name}):\n{result.facts}\n\nGeef nu je antwoord, of roep nog een tool aan."})

    # Exhausted all hops without a final answer -- ask once more, tools disabled, as a safety net.
    messages.append({"role": "user", "content": "Je hebt geen tool-aanroepen meer over. Geef nu je definitieve antwoord in platte tekst."})
    raw = generate_remote(messages=messages, max_new_tokens=max_new_tokens, enable_thinking=True)
    reasoning, remainder = _strip_think(raw)
    if reasoning:
        reasoning_parts.append(reasoning)
    final_answer = remainder or "(geen antwoord ontvangen)"
    deduped_sources = _dedup(sources)
    return AdvisorResponse(
        answer=final_answer,
        reasoning="\n\n".join(reasoning_parts),
        tool_calls=tool_calls_made,
        sources=deduped_sources,
        grounding=assess_grounding(final_answer, deduped_sources, tool_calls_made),
    )
