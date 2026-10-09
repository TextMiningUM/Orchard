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
  3. Call the cloud Qwen3-8B server with an ADAPTIVE thinking budget (`_needs_deep_thinking()`,
     2026-10-09): a short, single-fact question gets `enable_thinking=False` (Qwen3's native
     non-thinking mode -- faster, no `<think>` block at all), a genuinely multi-factor advice
     question gets `enable_thinking=True` (Qwen3's native chain-of-thought). Either way this
     uses Qwen3's OWN thinking toggle directly instead of a hand-rolled COT_INSTR prompt trick
     (Auto Pilot's own domains needed the latter because their base checkpoints don't expose a
     native thinking mode the same way; Qwen3 does, so use it).
  4. Parse the reply: either a `{"call_tool": ..., "args": ...}` request (execute it, append the
     result as a new user turn, loop -- up to `max_tool_hops`) or a final plain-text answer.
  5. Return the answer, the extracted reasoning trace (for an optional "Redenering" expander in
     the UI), every tool call made, and a deduped source list for a "Bronnen:" footer.

`ask_orchard_advisor_stream()` is a streaming twin of the above for the UI's final answer
(`st.write_stream()`, 2026-10-09 vLLM migration -- see design doc Sec G.21): intermediate
ReACT tool-call hops are NOT streamed (the full text is needed immediately to detect a
tool-call JSON vs. a plain answer, same reasoning as `generate_remote()` vs `stream_remote()`
in `pipeline/qwen_remote.py`), but the final hop is streamed token-by-token to the user once
it's clear it's a plain-text answer and not a tool call (see `_stream_hop()`).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pipeline.orchard_rag import RagIndex
from pipeline.orchard_tool_catalog import BoundTool, build_tool_catalog
from pipeline.qwen_remote import generate_remote, stream_remote

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


# A long question, or one with multiple clauses/conditions to weigh, benefits from Qwen3's
# full <think> chain-of-thought; a short single-fact lookup that merely missed the Streamlit
# page's own keyword router (`_route_question()` in `app/pages/3_Vraag_de_Adviseur.py` --
# vorst/regen/koude-uren/suzuki/barst/middel questions never even reach this module) does not.
_COMPLEXITY_MARKERS = (
    " en ", " maar ", " zowel ", " rekening houdend", " gelijktijdig", " allebei", " beide",
    " tegelijk", " waarom ", " hoe kan het dat", " welke van de", " of moet ik",
)
_COMPLEXITY_WORD_THRESHOLD = 18


def _needs_deep_thinking(question: str) -> bool:
    """Heuristic (design doc Deel F) for an adaptive thinking budget -- NOT a safety-relevant
    classifier: worst case a "simple" question gets a shallower-than-ideal budget and the
    answer is a bit less thorough, never wrong (the grounding/citation rules in SYSTEM_PROMPT
    apply identically either way). `enable_thinking=False` is Qwen3's own faster, non-thinking
    mode (no <think> block generated at all -- see cloud/qwen_inference_server.py's measured
    tokens/s), appropriate for a short, single-fact question; `enable_thinking=True` is kept
    for anything that weighs multiple factors/conditions, i.e. a genuine advice question."""
    q = f" {question.strip().lower()} "
    return len(question.split()) > _COMPLEXITY_WORD_THRESHOLD or any(m in q for m in _COMPLEXITY_MARKERS)


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


def _build_prompt_state(
    question: str, ctx, snapshot: dict | None, rag_index: RagIndex | None,
    max_tool_hops: int, history: list[dict] | None, max_history_turns: int,
) -> tuple[list[dict], dict[str, BoundTool], list[str]]:
    """Shared prelude for `ask_orchard_advisor()`/`ask_orchard_advisor_stream()`: upfront RAG
    search, tool catalog, and the system+user prompt (incl. capped conversation history --
    see `ask_orchard_advisor()`'s docstring for the `history`/`max_history_turns` contract).
    Returns (messages, tool_catalog, sources-so-far)."""
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
    return messages, tool_catalog, sources


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
    within the server's token budget -- older turns are silently dropped, newest first.

    Thinking budget (2026-10-09, see `_needs_deep_thinking()`): decided ONCE per question from
    the question text itself, then reused for every hop of that question's loop. After the
    FIRST tool call, the per-hop token budget is halved (floor `_POST_TOOL_MIN_TOKENS`) -- the
    model is now synthesizing an answer from facts already handed to it, not exploring from
    scratch, so it needs less headroom."""
    enable_thinking = _needs_deep_thinking(question)
    messages, tool_catalog, sources = _build_prompt_state(
        question, ctx, snapshot, rag_index, max_tool_hops, history, max_history_turns)

    reasoning_parts: list[str] = []
    tool_calls_made: list[str] = []
    budget = max_new_tokens

    for _hop in range(max_tool_hops + 1):
        raw = generate_remote(messages=messages, max_new_tokens=budget, enable_thinking=enable_thinking)
        reasoning, remainder = _strip_think(raw)
        if reasoning:
            reasoning_parts.append(reasoning)

        if not remainder:
            # Generation was cut off mid-<think> (max_new_tokens reached before the model
            # got to its actual answer) -- one retry with a larger budget before giving up,
            # rather than silently returning an empty/broken-looking answer.
            raw = generate_remote(messages=messages, max_new_tokens=budget * 2, enable_thinking=enable_thinking)
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
        budget = max(_POST_TOOL_MIN_TOKENS, max_new_tokens // 2)

    # Exhausted all hops without a final answer -- ask once more, tools disabled, as a safety net.
    messages.append({"role": "user", "content": "Je hebt geen tool-aanroepen meer over. Geef nu je definitieve antwoord in platte tekst."})
    raw = generate_remote(messages=messages, max_new_tokens=budget, enable_thinking=enable_thinking)
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


_POST_TOOL_MIN_TOKENS = 250


class StreamingAdvisorAnswer:
    """Iterable of visible answer-text chunks for `st.write_stream()`. Iterate it directly to
    display the final answer live as it's generated; once fully consumed, `.response` holds
    the same `AdvisorResponse` the non-streaming `ask_orchard_advisor()` returns (reasoning,
    tool_calls, sources, grounding) for the rest of the UI (CoT expander, grounding badge,
    feedback buttons) to use exactly as before."""

    def __init__(self, generator_fn) -> None:
        self._gen = generator_fn()
        self.response: AdvisorResponse | None = None

    def __iter__(self):
        for chunk in self._gen:
            if isinstance(chunk, AdvisorResponse):
                self.response = chunk
            else:
                yield chunk


def _stream_hop(messages: list[dict], max_new_tokens: int, enable_thinking: bool):
    """Streams ONE generation hop via `stream_remote()`. Yields visible answer-text chunks
    (for live display) while SILENTLY buffering the `<think>` block (that has its own
    "Redenering" expander, fed from the parsed-out reasoning afterwards -- raw thinking
    tokens should never flash past in the main chat bubble) and, once past `</think>`,
    silently buffering a hop whose remainder looks like it's forming a tool-call JSON (starts
    with `{`) rather than a plain answer -- only a hop that's clearly NOT a tool call streams
    its text live. Returns (raw_text, reasoning, remainder) as the final value via
    `StopIteration` is avoided here -- callers should capture it via the generator's return,
    so instead this is a generator that yields `str` chunks and, as its LAST item, yields the
    `(raw, reasoning, remainder)` tuple for the caller to finish parsing (mirroring
    `StreamingAdvisorAnswer`'s own "non-str sentinel as last item" convention)."""
    raw = ""
    last_visible_len = 0
    decided_not_tool_call = False
    for delta in stream_remote(messages=messages, max_new_tokens=max_new_tokens, enable_thinking=enable_thinking):
        raw += delta
        reasoning, remainder = _strip_think(raw)
        if not remainder:
            continue  # still inside an unclosed <think> block -- nothing visible yet
        if not decided_not_tool_call:
            if remainder.lstrip().startswith("{"):
                continue  # looks like it's forming tool-call JSON -- stay silent this hop
            decided_not_tool_call = True
        new_text = remainder[last_visible_len:]
        if new_text:
            last_visible_len = len(remainder)
            yield new_text
    reasoning, remainder = _strip_think(raw)
    yield (raw, reasoning, remainder)


def ask_orchard_advisor_stream(
    question: str, ctx, snapshot: dict | None = None, rag_index: RagIndex | None = None,
    max_tool_hops: int = 3, max_new_tokens: int = 700,
    history: list[dict] | None = None, max_history_turns: int = 4,
) -> StreamingAdvisorAnswer:
    """Streaming twin of `ask_orchard_advisor()` -- same prompt/ReACT/grounding logic, but the
    FINAL hop (the one that turns out not to be a tool call) streams its answer text live via
    the returned `StreamingAdvisorAnswer` instead of only being available once generation is
    fully done. Intermediate tool-call hops are still generated hop-by-hop (not streamed to
    the user -- see `_stream_hop()`'s docstring), so a question that needs 2 tool calls first
    still shows a brief "thinking" pause before the live-streamed answer starts, same as
    before; only the LAST, user-visible hop is now incremental."""
    enable_thinking = _needs_deep_thinking(question)

    def _run():
        messages, tool_catalog, sources = _build_prompt_state(
            question, ctx, snapshot, rag_index, max_tool_hops, history, max_history_turns)
        reasoning_parts: list[str] = []
        tool_calls_made: list[str] = []
        budget = max_new_tokens

        for _hop in range(max_tool_hops + 1):
            raw = reasoning = remainder = ""
            for item in _stream_hop(messages, budget, enable_thinking):
                if isinstance(item, tuple):
                    raw, reasoning, remainder = item
                else:
                    yield item
            if reasoning:
                reasoning_parts.append(reasoning)

            if not remainder:
                # Cut off mid-<think> -- one silent retry with a larger budget (not streamed,
                # since we don't yet know if THIS attempt even produces a visible answer).
                raw = generate_remote(messages=messages, max_new_tokens=budget * 2, enable_thinking=enable_thinking)
                reasoning, remainder = _strip_think(raw)
                if reasoning:
                    reasoning_parts.append(reasoning)
                if remainder:
                    yield remainder

            tool_call = _extract_tool_call(remainder) if _hop < max_tool_hops else None
            if tool_call is None:
                final_answer = remainder or "(geen antwoord ontvangen -- het model had meer tokens nodig dan beschikbaar)"
                if not remainder:
                    yield final_answer  # nothing was streamed yet for this (rare) double-cutoff case
                deduped_sources = _dedup(sources)
                yield AdvisorResponse(
                    answer=final_answer,
                    reasoning="\n\n".join(reasoning_parts),
                    tool_calls=tool_calls_made,
                    sources=deduped_sources,
                    grounding=assess_grounding(final_answer, deduped_sources, tool_calls_made),
                )
                return

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
            budget = max(_POST_TOOL_MIN_TOKENS, max_new_tokens // 2)

        # Exhausted all hops -- ask once more, tools disabled, streamed (it's necessarily final).
        messages.append({"role": "user", "content": "Je hebt geen tool-aanroepen meer over. Geef nu je definitieve antwoord in platte tekst."})
        raw = reasoning = remainder = ""
        for item in _stream_hop(messages, budget, enable_thinking):
            if isinstance(item, tuple):
                raw, reasoning, remainder = item
            else:
                yield item
        if reasoning:
            reasoning_parts.append(reasoning)
        final_answer = remainder or "(geen antwoord ontvangen)"
        if not remainder:
            yield final_answer
        deduped_sources = _dedup(sources)
        yield AdvisorResponse(
            answer=final_answer,
            reasoning="\n\n".join(reasoning_parts),
            tool_calls=tool_calls_made,
            sources=deduped_sources,
            grounding=assess_grounding(final_answer, deduped_sources, tool_calls_made),
        )

    return StreamingAdvisorAnswer(_run)
