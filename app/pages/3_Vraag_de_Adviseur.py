"""Vraag de Adviseur -- chat-demo (design doc Sec A.6/B.5).

Deterministische tool-routing (vorst/regen/koude-uren/kersenvlieg/vruchtbarsten/
Ctgb-guardrail) blijft de eerste, betrouwbare laag -- die antwoorden zijn altijd gegrond
op echte tool-output en worden NOOIT aan het LLM overgelaten. Voor alles daarbuiten gaat de
vraag nu (Fase 2/3) naar `pipeline.orchard_agent.ask_orchard_advisor_stream()`: Qwen3-8B-AWQ
via vLLM (`cloud/qwen_inference_server.py` op de pod, via `pipeline.qwen_remote.stream_remote()`,
sinds 2026-10-09 -- zie design doc Sec G.21) met (1) altijd een
Track 1-kennisbank-zoekopdracht vooraf (dense retrieval + cross-encoder reranking, zie
`pipeline/orchard_rag.py`), (2) een ReACT-lus waarin het model dezelfde deterministische
tools (weer, koude-uren, vorst, suzuki, vruchtbarsten, Ctgb-guardrail) zelf mag aanroepen
(`pipeline/orchard_tool_catalog.py`), en (3) Qwen3's eigen `<think>`-redenering zichtbaar
gemaakt in een inklapbare "Redenering (CoT)"-sectie. Dit is nog het ONGETRAINDE basismodel
(geen SFT/DPO) -- elk antwoord krijgt daarom nog een expliciete waarschuwing. Elk antwoord
krijgt ook een rood/groen hallucinatie-indicator (`pipeline.orchard_agent.assess_grounding()` --
een HEURISTIEK, zie design doc Deel F #12, geen garantie) en duim-omhoog/omlaag-knoppen die
een voorkeurssignaal opslaan voor een toekomstige DPO-trainingsronde
(`pipeline/orchard_feedback.py`, zie Deel E stap 7/Deel F #11). Zie ontwerp Deel E voor de
trainingsroadmap.

Chats worden -- net als bij ChatGPT -- bewaard per sessie (`pipeline/orchard_chats.py`, een
JSON-bestand per chat in `Data/Orchard/OrchardChats/`). De pagina opent altijd met een
nieuwe, lege chat; eerdere chats staan in de zijbalk (automatisch getitelde knop) en kunnen
met een klik hervat worden, inclusief volledige vraag/antwoord-geschiedenis en voorkeuren.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchard_common import compute_season_snapshot, render_sidebar  # noqa: E402

import streamlit as st

from pipeline.orchard_agent import ADVISOR_WEIGHTS, ask_orchard_advisor_stream, build_history_messages  # noqa: E402
from pipeline.orchard_chats import (  # noqa: E402
    ChatSession,
    ChatTurn,
    delete_chat,
    derive_title,
    list_chats,
    load_chat,
    new_chat_session,
    save_chat,
)
from pipeline.orchard_feedback import build_feedback_record, save_feedback  # noqa: E402
from pipeline.orchard_rag import load_index  # noqa: E402
from pipeline.orchard_tools import get_rain_nowcast  # noqa: E402
from pipeline.qwen_remote import (round_up_s, get_status, is_remote_server_up, model_state, reconnect_tunnel,  # noqa: E402
                                  wait_notice)
from datetime import datetime, timezone  # noqa: E402

st.set_page_config(page_title="Vraag de Adviseur", layout="wide")
st.title("Vraag de Adviseur")
st.caption("Typ je vraag hieronder in het invoerveld (altijd onderaan dit scherm zichtbaar).")

ctx = render_sidebar(st)


def _new_session_state(session) -> None:
    st.session_state["current_chat_id"] = session.id
    st.session_state["current_chat_title"] = session.title
    st.session_state["current_chat_created_at"] = session.created_at
    st.session_state["chat_history"] = [(t.role, t.content, t.meta) for t in session.turns]


if "chat_history" not in st.session_state:
    # Zelfde gewoonte als ChatGPT: de pagina opent altijd op een VERSE, lege chat -- eerdere
    # chats staan in de zijbalk en moeten expliciet aangeklikt worden om te hervatten.
    _new_session_state(new_chat_session())


def _save_current_chat() -> None:
    history = st.session_state["chat_history"]
    if not history:
        return  # nog niets om te bewaren
    if st.session_state["current_chat_title"] == "Nieuwe chat":
        first_question = next((m for r, m, _ in history if r == "user"), "")
        if first_question:
            st.session_state["current_chat_title"] = derive_title(first_question)
    session = ChatSession(
        id=st.session_state["current_chat_id"], title=st.session_state["current_chat_title"],
        created_at=st.session_state["current_chat_created_at"],
        updated_at=datetime.now(timezone.utc).isoformat(),
        turns=[ChatTurn(role=r, content=m, meta=meta) for r, m, meta in history],
    )
    save_chat(session)


# Direct boven aan de zijbalk (vóór de technische status-captions), zodat de chatlijst ook
# bij een lager browservenster meteen zichtbaar is zonder te scrollen.
with st.sidebar:
    st.divider()
    st.subheader("Chats")
    if st.button("Nieuwe chat", width="stretch"):
        _save_current_chat()
        _new_session_state(new_chat_session())
        st.rerun()
    for chat_meta in list_chats():
        is_current = chat_meta["id"] == st.session_state["current_chat_id"]
        col_a, col_b = st.columns([4, 1])
        if col_a.button(
            chat_meta["title"] or "Chat", key=f"open_{chat_meta['id']}", width="stretch",
            type="primary" if is_current else "secondary",
        ):
            _save_current_chat()
            resumed = load_chat(chat_meta["id"])
            if resumed is not None:
                _new_session_state(resumed)
                st.rerun()
        if col_b.button("Verwijder", key=f"del_{chat_meta['id']}"):
            delete_chat(chat_meta["id"])
            if is_current:
                _new_session_state(new_chat_session())
            st.rerun()
    st.divider()

with st.sidebar:
    reconnect_tunnel()  # no-op if already reachable (e.g. running on the pod itself)
    if is_remote_server_up():
        _state = model_state(get_status(), ADVISOR_WEIGHTS)
        st.caption("Qwen3-8B-server: bereikbaar" + {
            "ready": " (model geladen, antwoord binnen enkele seconden)",
            "loading": " (model wordt nu geladen)",
            "unloaded": f" (model niet geladen: de eerste vraag duurt ± {round_up_s(_state['eta_s'])} s extra)",
        }.get(_state["state"], ""))
    else:
        st.caption(
            "Qwen3-8B-server: niet bereikbaar. Lokaal? Zet eerst een SSH-tunnel op "
            "(zie `pipeline/qwen_remote.py`) of vul `.env` (ORCHARD_CLOUD_SSH_HOST/KEY) in."
        )

_rag_index = load_index()
with st.sidebar:
    if _rag_index is not None:
        st.caption(f"Kennisbank-index: {_rag_index.n_chunks} fragmenten geladen.")
    else:
        st.caption(
            "Kennisbank-index nog niet gebouwd. Draai lokaal: "
            "`.venv\\Scripts\\python.exe -m pipeline.ingest.build_orchard_rag`"
        )


def _disclaimer_suffix(answer: str, sources: list[str]) -> str:
    """Appends the "Bronnen:"-footer (if not already present) and the standard untrained-model
    disclaimer -- shared tail for both the deterministic-tool answers and the streamed LLM
    answer, so a reloaded chat looks identical either way."""
    if sources and "Bronnen:" not in answer:
        answer += "\n\n**Bronnen:**\n" + "\n".join(f"- {s}" for s in sources)
    answer += (
        "\n\n*Let op: dit antwoord komt van het ongetrainde Qwen3-8B-basismodel "
        "(wel met kennisbank/RAG, nog geen SFT/DPO-training) -- controleer specifieke "
        "feiten altijd tegen de genoemde bron.*"
    )
    return answer


def _try_deterministic_route(question: str) -> dict | None:
    """Deterministic tool-routed answers (vorst/regen/koude-uren/kersenvlieg/vruchtbarsten/
    Ctgb-guardrail) -- always instant, always grounded on real tool output, never the LLM.
    Returns None if nothing matched, meaning the caller should fall back to the streamed
    `ask_orchard_advisor_stream()` path instead."""
    q = question.lower()
    try:
        snap = compute_season_snapshot(ctx)
    except Exception as exc:
        return _plain(f"Kon geen live weerdata ophalen: {exc}", grounding="red")

    if any(k in q for k in ("middel", "dosering", "toegelaten", "ctgb", "spuiten met")):
        return _ctgb_route(question)

    if any(k in q for k in ("vorst", "nachtvorst", "koud vannacht")):
        risky = [f for d, f in snap["frost_by_day"] if f.risk in ("hoog", "kritiek")]
        if risky:
            lines = "\n".join(f"- {f.note}" for f in risky)
            return _plain(f"**Vorstrisico gevonden** voor fase '{ctx.stage}':\n{lines}\n\nBron: {risky[0].source_citation}")
        return _plain(f"Geen verhoogd vorstrisico voor fase '{ctx.stage}' in de komende 7 dagen (bron: {snap['forecast'].source_citation}).")

    if any(k in q for k in ("regen", "neerslag", "bui")):
        try:
            nowcast = get_rain_nowcast(ctx.lat, ctx.lon)
            upcoming = [v for _, v in nowcast.values_mm_per_h if v > 0]
            if upcoming:
                return _plain(
                    f"Buienradar verwacht de komende 2 uur neerslag (piek ~{max(upcoming):.1f} mm/u). "
                    f"Bron: {nowcast.source_citation}"
                )
            return _plain(f"Geen neerslag verwacht in de komende 2 uur (bron: {nowcast.source_citation}).")
        except Exception as exc:
            return _plain(f"Buienradar-nowcast niet beschikbaar: {exc}", grounding="red")

    if any(k in q for k in ("koude-uren", "chill", "rust-uren")):
        c = snap["chill"]
        if c.required_hours:
            return _plain(
                f"**{ctx.variety}** heeft nu {c.accumulated_hours:.0f} van de {c.required_hours:.0f} "
                f"benodigde koude-uren ({c.fraction_complete*100:.0f}%). Bron: {c.source_citation}"
            )
        return _plain(f"{c.accumulated_hours:.0f} koude-uren opgebouwd, maar drempel voor '{ctx.variety}' nog niet gesourced.", grounding="red")

    if any(k in q for k in ("suzuki", "kersenvlieg", "fruitvlieg", "drosophila")):
        s = snap["suzukii"]
        return _plain(f"Suzuki-fruitvlieg-risico: **{s.risk.upper()}**. Bron: {s.source_citation}")

    if any(k in q for k in ("barst", "oogst", "vruchtrot")):
        r = snap["rain_crack"]
        return _plain(
            f"Vruchtbarsten-risico voor fase '{ctx.stage}': **{r.risk.upper()}** "
            f"({r.forecast_precip_mm_48h:.1f} mm verwacht komende 48u). Bron: {r.source_citation}"
        )

    return None


def _ctgb_route(question: str) -> dict:
    """Middel-/dosering-/toelatingsvragen: de officiele Ctgb-kaart (letterlijk uit de API, nooit door het model geschreven). Zonder herkenbare
    merknaam blijft het bij de compliance-guardrail met de vraag om de merknaam."""
    from pipeline.orchard_ctgb import SOURCE, CtgbUnavailable, detect_product_names, fold, format_card, lookup
    from pipeline.orchard_middelen import _ALIAS_INDEX
    names = detect_product_names(question, {fold(k) for k in _ALIAS_INDEX})
    if not names:
        return _plain(
            "**Compliance-guardrail**: ik noem geen dosering of toelatingsstatus uit mijn hoofd. Noem de **merknaam** van het middel (bijv. 'Syllit') en ik "
            "toon het officiële Ctgb-voorschrift voor kers (dosering, aantal toepassingen, interval, veiligheidstermijn), of zoek het op via "
            "*Gebruik van Middelen → Middel opzoeken*. Controleer altijd ook de gebruiksaanwijzing/het etiket."
        )
    try:
        lookups = [lookup(name) for name in names]
    except CtgbUnavailable as exc:
        return _plain(f"De Ctgb-databank is nu niet te bereiken ({exc}). Ik toon geen dosering of toelatingsstatus zonder die bron; probeer het later nog "
                      "eens of kijk op ctgb.nl.", grounding="red")
    shown = [lk for lk in lookups if lk.products] or lookups[:1]   # a second capitalised word (a disease) must not add an empty card
    return {"answer": "Hieronder staat het **officiële Ctgb-voorschrift voor kers** voor " + " en ".join(f"'{lk.query}'" for lk in shown) + ", letterlijk uit de "
            "Ctgb-databank (niet door het taalmodel geschreven). Dit is het wettelijke maximum en geen spuitadvies; de gebruiksaanwijzing/het etiket is leidend.",
            "reasoning": "", "tool_calls": ["ctgb_toelating"], "sources": [SOURCE], "grounding": "green", "cards": [format_card(lk) for lk in shown]}


def _plain(text: str, grounding: str = "green") -> dict:
    return {"answer": text, "reasoning": "", "tool_calls": [], "sources": [], "grounding": grounding}


_GROUNDING_BADGE = {
    "green": ("GEGROND", "Dit antwoord citeert een kennisbank-fragment, tool-resultaat of bron."),
    "red": ("GEEN GROUNDING GEVONDEN", "Dit antwoord citeert geen bron/tool-resultaat -- "
                                       "controleer feitelijke beweringen extra kritisch (mogelijke hallucinatie)."),
}


def _render_assistant_extras(meta: dict, answer: str, key_prefix: str) -> None:
    """Everything BESIDES the answer text itself: CoT expander, tool-use caption, grounding
    badge, feedback buttons. Split out from the answer markdown so the streamed path can
    `st.write_stream()` the answer live and only call this afterwards (avoids re-rendering
    -- and so duplicating -- text that was already streamed to the screen)."""
    if meta.get("reasoning"):
        with st.expander("Redenering (CoT)"):
            st.text(meta["reasoning"])
    for j, card in enumerate(meta.get("cards") or []):
        with st.expander("Officiële gegevens (letterlijk uit de bron, niet door het model geschreven)", expanded=True):
            st.markdown(card)
    if meta.get("tool_calls"):
        st.caption("Tools gebruikt: " + ", ".join(meta["tool_calls"]))

    label, uitleg = _GROUNDING_BADGE.get(meta.get("grounding", "red"), _GROUNDING_BADGE["red"])
    if meta.get("grounding") == "green":
        st.success(f"{label}: {uitleg}")
    else:
        st.error(f"{label}: {uitleg}")

    feedback = meta.get("feedback")
    if feedback:
        st.caption(f"Feedback opgeslagen: {'👍' if feedback == 'chosen' else '👎'} (dank je!)")
        return

    col1, col2, _rest = st.columns([1, 1, 6])

    def _give_feedback(preference: str) -> None:
        record = build_feedback_record(
            question=meta.get("question", ""), answer=answer, reasoning=meta.get("reasoning", ""),
            sources=meta.get("sources", []), tool_calls=meta.get("tool_calls", []),
            grounding=meta.get("grounding", "red"), preference=preference,
        )
        save_feedback(record)
        meta["feedback"] = preference
        _save_current_chat()

    col1.button("👍", key=f"{key_prefix}_up", help="Nuttig", on_click=_give_feedback, args=("chosen",))
    col2.button("👎", key=f"{key_prefix}_down", help="Niet nuttig", on_click=_give_feedback, args=("rejected",))


def _render_assistant_message(answer: str, meta: dict, key_prefix: str) -> None:
    """Full render (answer text + extras) -- used for chat-history replay, where nothing was
    streamed live and the complete answer is already known."""
    st.markdown(answer)
    _render_assistant_extras(meta, answer, key_prefix)


for i, entry in enumerate(st.session_state["chat_history"]):
    role, msg, meta = entry
    with st.chat_message(role):
        if role == "assistant":
            _render_assistant_message(msg, meta, key_prefix=f"hist_{i}")
        else:
            st.markdown(msg)

if prompt := st.chat_input("Stel een vraag, bijv. 'is er vorstrisico deze week?'"):
    st.session_state["chat_history"].append(("user", prompt, {}))
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        result = _try_deterministic_route(prompt)
        if result is not None:
            st.markdown(result["answer"])
        else:
            prior_turns = [(role, msg) for role, msg, _meta in st.session_state["chat_history"][:-1]]
            history = build_history_messages(prior_turns)
            try:
                notice = wait_notice(model_state(get_status(), ADVISOR_WEIGHTS))
                with st.spinner(notice):
                    streamer = ask_orchard_advisor_stream(prompt, ctx, rag_index=_rag_index, history=history)
                    st.write_stream(streamer)
                resp = streamer.response
                final_answer = _disclaimer_suffix(resp.answer, resp.sources)
                result = {
                    "answer": final_answer, "reasoning": resp.reasoning, "tool_calls": resp.tool_calls,
                    "sources": resp.sources, "grounding": resp.grounding, "cards": resp.cards,
                }
                st.markdown(final_answer[len(resp.answer):])  # the sources/disclaimer tail, appended after the live-streamed text
            except (ConnectionError, RuntimeError) as exc:
                result = {
                    "answer": f"Kon het Qwen3-8B-model niet bereiken: {exc}",
                    "reasoning": "", "tool_calls": [], "sources": [], "grounding": "red",
                }
                st.markdown(result["answer"])
        result["question"] = prompt
        result["feedback"] = None
        st.session_state["chat_history"].append(("assistant", result["answer"], result))
        _save_current_chat()
        _render_assistant_extras(result, result["answer"], key_prefix=f"new_{len(st.session_state['chat_history'])}")
