"""Vraag de Adviseur -- chat-demo (design doc Sec A.6/B.5).

Deterministische tool-routing (vorst/regen/koude-uren/kersenvlieg/vruchtbarsten/
Ctgb-guardrail) blijft de eerste, betrouwbare laag -- die antwoorden zijn altijd gegrond
op echte tool-output en worden NOOIT aan het LLM overgelaten. Voor alles daarbuiten gaat de
vraag nu (Fase 2/3) naar `pipeline.orchard_agent.ask_orchard_advisor()`: Qwen3-8B
(`cloud/qwen_inference_server.py` op de pod, via `pipeline.qwen_remote`) met (1) altijd een
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

from pipeline.orchard_agent import ask_orchard_advisor, build_history_messages  # noqa: E402
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
from pipeline.orchard_tools import check_ctgb_toelating, get_rain_nowcast  # noqa: E402
from pipeline.qwen_remote import is_remote_server_up, reconnect_tunnel  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

st.set_page_config(page_title="Vraag de Adviseur", layout="wide")
st.title("Vraag de Adviseur")

with st.form("ask_form_top", clear_on_submit=True):
    prompt_top = st.text_input(
        "Stel een vraag",
        placeholder=(
            'Typ je vraag helemaal onderaan dit scherm, bijvoorbeeld "is er vorstrisico deze '
            'week?" of "wat zegt de kennisbank over Monilia?".'
        ),
        label_visibility="collapsed",
    )
    submitted_top = st.form_submit_button("Vraag stellen")

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
        st.caption("Qwen3-8B-server: bereikbaar")
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


def _ask_advisor(question: str, snapshot: dict | None) -> dict:
    # Eerdere beurten (exclusief de net toegevoegde user-prompt van nu) als gespreksgeschiedenis,
    # zodat vervolgvragen ("en hoe zit dat met...?") met echte context beantwoord worden i.p.v.
    # als een volledig losse, nieuwe vraag behandeld te worden.
    prior_turns = [(role, msg) for role, msg, _meta in st.session_state["chat_history"][:-1]]
    history = build_history_messages(prior_turns)
    try:
        resp = ask_orchard_advisor(question, ctx, snapshot=snapshot, rag_index=_rag_index, history=history)
    except (ConnectionError, RuntimeError) as exc:
        return {
            "answer": f"Kon het Qwen3-8B-model niet bereiken: {exc}",
            "reasoning": "", "tool_calls": [], "sources": [], "grounding": "red",
        }
    answer = resp.answer
    if resp.sources and "Bronnen:" not in answer:
        answer += "\n\n**Bronnen:**\n" + "\n".join(f"- {s}" for s in resp.sources)
    answer += (
        "\n\n*Let op: dit antwoord komt van het ongetrainde Qwen3-8B-basismodel "
        "(wel met kennisbank/RAG, nog geen SFT/DPO-training) -- controleer specifieke "
        "feiten altijd tegen de genoemde bron.*"
    )
    return {
        "answer": answer, "reasoning": resp.reasoning, "tool_calls": resp.tool_calls,
        "sources": resp.sources, "grounding": resp.grounding,
    }


def _route_question(question: str) -> dict:
    q = question.lower()
    try:
        snap = compute_season_snapshot(ctx)
    except Exception as exc:
        snap = None
        snap_error = f"Kon geen live weerdata ophalen: {exc}"
    else:
        snap_error = None

    def _plain(text: str, grounding: str = "green") -> dict:
        return {"answer": text, "reasoning": "", "tool_calls": [], "sources": [], "grounding": grounding}

    if snap is None:
        return _plain(snap_error, grounding="red")

    if any(k in q for k in ("middel", "dosering", "toegelaten", "ctgb", "spuiten met")):
        try:
            check_ctgb_toelating(middel="onbekend", gewas="kers")
        except NotImplementedError as exc:
            return _plain(
                "**Compliance-guardrail**: ik kan en mag geen middelnaam/dosering verzinnen. "
                f"{exc}\n\nRaadpleeg handmatig ctgb.nl/toelatingen totdat deze tool is aangesloten "
                "(zie ontwerp Sec C.5)."
            )

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

    return _ask_advisor(question, snap)


_GROUNDING_BADGE = {
    "green": ("GEGROND", "Dit antwoord citeert een kennisbank-fragment, tool-resultaat of bron."),
    "red": ("GEEN GROUNDING GEVONDEN", "Dit antwoord citeert geen bron/tool-resultaat -- "
                                       "controleer feitelijke beweringen extra kritisch (mogelijke hallucinatie)."),
}


def _render_assistant_message(answer: str, meta: dict, key_prefix: str) -> None:
    st.markdown(answer)
    if meta.get("reasoning"):
        with st.expander("Redenering (CoT)"):
            st.text(meta["reasoning"])
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


for i, entry in enumerate(st.session_state["chat_history"]):
    role, msg, meta = entry
    with st.chat_message(role):
        if role == "assistant":
            _render_assistant_message(msg, meta, key_prefix=f"hist_{i}")
        else:
            st.markdown(msg)

if submitted_top and prompt_top:
    st.session_state["chat_history"].append(("user", prompt_top, {}))
    with st.chat_message("user"):
        st.markdown(prompt_top)
    with st.chat_message("assistant"):
        with st.spinner(
            "De adviseur denkt na... (bij een vraag die niet direct door een tool wordt "
            "beantwoord, raadpleegt het AI-model eerst de kennisbank en kan het 30-60 "
            "seconden duren)"
        ):
            result = _route_question(prompt_top)
        result["question"] = prompt_top
        result["feedback"] = None
        st.session_state["chat_history"].append(("assistant", result["answer"], result))
        _save_current_chat()
        _render_assistant_message(result["answer"], result, key_prefix=f"new_{len(st.session_state['chat_history'])}")
