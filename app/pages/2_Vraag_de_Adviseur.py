"""Vraag de Adviseur -- chat-demo (design doc Sec A.6/B.5).

FASE 1: deterministische tool-routing (vorst/regen/koude-uren/kersenvlieg/vruchtbarsten/
Ctgb-guardrail) blijft de eerste, betrouwbare laag -- die antwoorden zijn altijd gegrond
op echte tool-output en worden NOOIT aan het LLM overgelaten. Voor alles daarbuiten wordt
nu (nieuw) het echte Qwen3-8B-basismodel aangeroepen (`cloud/qwen_inference_server.py` op
de pod, via `pipeline.qwen_remote`) in plaats van de oude "ik heb hier geen tool-route
voor"-placeholder. BELANGRIJK: dit is nog het ONGETRAINDE basismodel, zonder RAG --het
WEET dus nog niets gegronds over kersenteelt specifiek en kan hallucineren. Elk
Qwen-gegenereerd antwoord krijgt daarom een expliciete waarschuwing. Fase 2+ (RAG op
echte vakkennis, SFT/DPO-training) is het vervolgwerk dat dit moet grond maken -- zie
ontwerp Deel E.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchard_common import compute_season_snapshot, render_sidebar  # noqa: E402

import streamlit as st

from pipeline.orchard_tools import check_ctgb_toelating, get_rain_nowcast  # noqa: E402
from pipeline.qwen_remote import generate_remote, is_remote_server_up, reconnect_tunnel  # noqa: E402

st.set_page_config(page_title="Vraag de Adviseur", layout="wide")
st.title("Vraag de Adviseur")
st.warning(
    "**Fase 1**: vorst/regen/koude-uren/kersenvlieg/vruchtbarsten/middel-vragen gaan via "
    "betrouwbare, gegronde tools. Alle overige vragen gaan nu naar het **ongetrainde** "
    "Qwen3-8B-basismodel (nog geen kennisbank/RAG) -- dat kan dus nog hallucineren over "
    "specifieke kersenteelt-feiten. Zie ontwerp Deel E voor de trainingsroadmap."
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

_SYSTEM_PROMPT = (
    "Je bent een Nederlandstalige assistent voor een kersenteler (zoete kersen, "
    "Prunus avium). Antwoord kort, praktisch en in het Nederlands. Als je iets niet "
    "zeker weet, zeg dat expliciet in plaats van te verzinnen. Noem nooit een concreet "
    "gewasbeschermingsmiddel of dosering als harde aanbeveling -- verwijs daarvoor naar "
    "de Ctgb-databank."
)


def _ask_qwen(question: str) -> str:
    try:
        text = generate_remote(
            messages=[{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": question}],
            max_new_tokens=300,
        )
        return (
            f"{text}\n\n*Let op: dit antwoord komt van het ongetrainde Qwen3-8B-basismodel "
            "(nog geen kennisbank/RAG) -- controleer specifieke feiten (middelen, doseringen, "
            "rasnamen) altijd tegen een betrouwbare bron.*"
        )
    except (ConnectionError, RuntimeError) as exc:
        return (
            f"Kon het Qwen3-8B-model niet bereiken: {exc}\n\n"
            "Fase-0-fallback: ik heb hier nog geen tool-route voor (ken alleen: vorst, regen, "
            "koude-uren, suzuki-fruitvlieg, vruchtbarsten, middel/toelating)."
        )


def _route_question(question: str) -> str:
    q = question.lower()
    try:
        snap = compute_season_snapshot(ctx)
    except Exception as exc:
        return f"Kon geen live weerdata ophalen om je vraag te beantwoorden: {exc}"

    if any(k in q for k in ("middel", "dosering", "toegelaten", "ctgb", "spuiten met")):
        try:
            check_ctgb_toelating(middel="onbekend", gewas="kers")
        except NotImplementedError as exc:
            return (
                "**Compliance-guardrail**: ik kan en mag geen middelnaam/dosering verzinnen. "
                f"{exc}\n\nRaadpleeg handmatig ctgb.nl/toelatingen totdat deze tool is aangesloten "
                "(zie ontwerp Sec C.5)."
            )

    if any(k in q for k in ("vorst", "nachtvorst", "koud vannacht")):
        risky = [f for d, f in snap["frost_by_day"] if f.risk in ("hoog", "kritiek")]
        if risky:
            lines = "\n".join(f"- {f.note}" for f in risky)
            return f"**Vorstrisico gevonden** voor fase '{ctx.stage}':\n{lines}\n\nBron: {risky[0].source_citation}"
        return f"Geen verhoogd vorstrisico voor fase '{ctx.stage}' in de komende 7 dagen (bron: {snap['forecast'].source_citation})."

    if any(k in q for k in ("regen", "neerslag", "bui")):
        try:
            nowcast = get_rain_nowcast(ctx.lat, ctx.lon)
            upcoming = [v for _, v in nowcast.values_mm_per_h if v > 0]
            if upcoming:
                return (
                    f"Buienradar verwacht de komende 2 uur neerslag (piek ~{max(upcoming):.1f} mm/u). "
                    f"Bron: {nowcast.source_citation}"
                )
            return f"Geen neerslag verwacht in de komende 2 uur (bron: {nowcast.source_citation})."
        except Exception as exc:
            return f"Buienradar-nowcast niet beschikbaar: {exc}"

    if any(k in q for k in ("koude-uren", "chill", "rust-uren")):
        c = snap["chill"]
        if c.required_hours:
            return (
                f"**{ctx.variety}** heeft nu {c.accumulated_hours:.0f} van de {c.required_hours:.0f} "
                f"benodigde koude-uren ({c.fraction_complete*100:.0f}%). Bron: {c.source_citation}"
            )
        return f"{c.accumulated_hours:.0f} koude-uren opgebouwd, maar drempel voor '{ctx.variety}' nog niet gesourced."

    if any(k in q for k in ("suzuki", "kersenvlieg", "fruitvlieg", "drosophila")):
        s = snap["suzukii"]
        return f"Suzuki-fruitvlieg-risico: **{s.risk.upper()}**. Bron: {s.source_citation}"

    if any(k in q for k in ("barst", "oogst", "vruchtrot")):
        r = snap["rain_crack"]
        return (
            f"Vruchtbarsten-risico voor fase '{ctx.stage}': **{r.risk.upper()}** "
            f"({r.forecast_precip_mm_48h:.1f} mm verwacht komende 48u). Bron: {r.source_citation}"
        )

    return _ask_qwen(question)


for role, msg in st.session_state["chat_history"]:
    with st.chat_message(role):
        st.markdown(msg)

if prompt := st.chat_input("Stel een vraag, bijv. 'is er vorstrisico deze week?'"):
    st.session_state["chat_history"].append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)
    answer = _route_question(prompt)
    st.session_state["chat_history"].append(("assistant", answer))
    with st.chat_message("assistant"):
        st.markdown(answer)
