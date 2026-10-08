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
(geen SFT/DPO) -- elk antwoord krijgt daarom nog een expliciete waarschuwing. Zie ontwerp
Deel E voor de trainingsroadmap.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchard_common import compute_season_snapshot, render_sidebar  # noqa: E402

import streamlit as st

from pipeline.orchard_agent import ask_orchard_advisor  # noqa: E402
from pipeline.orchard_rag import load_index  # noqa: E402
from pipeline.orchard_tools import check_ctgb_toelating, get_rain_nowcast  # noqa: E402
from pipeline.qwen_remote import is_remote_server_up, reconnect_tunnel  # noqa: E402

st.set_page_config(page_title="Vraag de Adviseur", layout="wide")
st.title("Vraag de Adviseur")
st.warning(
    "**Fase 1**: vorst/regen/koude-uren/kersenvlieg/vruchtbarsten/middel-vragen gaan via "
    "betrouwbare, gegronde tools. Alle overige vragen gaan nu naar Qwen3-8B **met** de Track "
    "1-kennisbank (RAG + reranking) en toegang tot dezelfde tools, in een stap-voor-stap "
    "(ReACT) redeneerlus met zichtbare tussenstappen. Dit is nog het ongetrainde basismodel "
    "(geen SFT/DPO) -- het kan dus nog steeds fouten maken buiten wat de kennisbank/tools "
    "dekken. Zie ontwerp Deel E voor de trainingsroadmap."
)

ctx = render_sidebar(st)

with st.sidebar:
    reconnect_tunnel()  # no-op if already reachable (e.g. running on the pod itself)
    if is_remote_server_up():
        st.caption("Qwen3-8B-server: bereikbaar")
    else:
        st.caption(
            "Qwen3-8B-server: niet bereikbaar. Lokaal? Zet eerst een SSH-tunnel op "
            "(zie `pipeline/qwen_remote.py`) of vul `.env` (ORCHARD_CLOUD_SSH_HOST/KEY) in."
        )

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []

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
    try:
        resp = ask_orchard_advisor(question, ctx, snapshot=snapshot, rag_index=_rag_index)
    except (ConnectionError, RuntimeError) as exc:
        return {
            "answer": f"Kon het Qwen3-8B-model niet bereiken: {exc}",
            "reasoning": "", "tool_calls": [], "sources": [],
        }
    answer = resp.answer
    if resp.sources and "Bronnen:" not in answer:
        answer += "\n\n**Bronnen:**\n" + "\n".join(f"- {s}" for s in resp.sources)
    answer += (
        "\n\n*Let op: dit antwoord komt van het ongetrainde Qwen3-8B-basismodel "
        "(wel met kennisbank/RAG, nog geen SFT/DPO-training) -- controleer specifieke "
        "feiten altijd tegen de genoemde bron.*"
    )
    return {"answer": answer, "reasoning": resp.reasoning, "tool_calls": resp.tool_calls, "sources": resp.sources}


def _route_question(question: str) -> dict:
    q = question.lower()
    try:
        snap = compute_season_snapshot(ctx)
    except Exception as exc:
        snap = None
        snap_error = f"Kon geen live weerdata ophalen: {exc}"
    else:
        snap_error = None

    def _plain(text: str) -> dict:
        return {"answer": text, "reasoning": "", "tool_calls": [], "sources": []}

    if snap is None:
        return _plain(snap_error)

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
            return _plain(f"Buienradar-nowcast niet beschikbaar: {exc}")

    if any(k in q for k in ("koude-uren", "chill", "rust-uren")):
        c = snap["chill"]
        if c.required_hours:
            return _plain(
                f"**{ctx.variety}** heeft nu {c.accumulated_hours:.0f} van de {c.required_hours:.0f} "
                f"benodigde koude-uren ({c.fraction_complete*100:.0f}%). Bron: {c.source_citation}"
            )
        return _plain(f"{c.accumulated_hours:.0f} koude-uren opgebouwd, maar drempel voor '{ctx.variety}' nog niet gesourced.")

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


for entry in st.session_state["chat_history"]:
    role, msg, meta = entry
    with st.chat_message(role):
        st.markdown(msg)
        if meta.get("reasoning"):
            with st.expander("Redenering (CoT)"):
                st.text(meta["reasoning"])
        if meta.get("tool_calls"):
            st.caption("Tools gebruikt: " + ", ".join(meta["tool_calls"]))

if prompt := st.chat_input("Stel een vraag, bijv. 'is er vorstrisico deze week?'"):
    st.session_state["chat_history"].append(("user", prompt, {}))
    with st.chat_message("user"):
        st.markdown(prompt)
    result = _route_question(prompt)
    st.session_state["chat_history"].append(("assistant", result["answer"], result))
    with st.chat_message("assistant"):
        st.markdown(result["answer"])
        if result.get("reasoning"):
            with st.expander("Redenering (CoT)"):
                st.text(result["reasoning"])
        if result.get("tool_calls"):
            st.caption("Tools gebruikt: " + ", ".join(result["tool_calls"]))
