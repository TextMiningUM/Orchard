"""Seizoensplanning -- de teeltkalender als referentie (design doc Sec A.4)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchard_common import render_sidebar  # noqa: E402

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Seizoensplanning", layout="wide")
st.title("Seizoensplanning")

ctx = render_sidebar(st)

CALENDAR = [
    dict(fase="rust", periode="nov–feb", beslissingen="koude-uren bijhouden t.o.v. rasvereiste; winterbemesting/bodemanalyse plannen", risico="te zachte winter → onvoldoende koude-uren → onregelmatige bloei"),
    dict(fase="knopzwelling", periode="half feb–maart", beslissingen="eerste bespuiting (minerale olie tegen spint/luis-eieren); wortelsnoei (uiterlijk 2 weken vóór bloei); inzagen/boomevenwicht herstellen", risico="te vroege bespuiting bij vorst → gewasverbranding"),
    dict(fase="bloei", periode="eind maart–april", beslissingen="bestuivers regelen (≥5 bijenvolken/ha + hommels/metselbijen); géén voor bestuivers schadelijk middel; vorstbewaking", risico="nachtvorst tijdens bloei; regen/kou → slechte bestuiving; bijensterfte"),
    dict(fase="vruchtzetting", periode="april–mei", beslissingen="voedingsbespuitingen (ureum, borium, kalifosfaat); dunnen indien nodig; kersenvlieg-monitoring start", risico="hagel; late vorst; onbalans in boom"),
    dict(fase="groei", periode="mei–juni/juli", beslissingen="irrigatie-/vochtsturing; gewasbescherming o.b.v. kersenvlieg degree-day-model; overkapping/regenkappen", risico="regen vlak vóór oogst → vruchtbarsten; kersenvlieg-uitbraak"),
    dict(fase="rijping", periode="juni–juli", beslissingen="brix/kleur monitoren; weersvoorspelling volgen voor oogstplanning", risico="regen → vruchtbarsten; hagel"),
    dict(fase="oogst", periode="juni–augustus", beslissingen="oogsttiming o.b.v. brix/kleur/weer; arbeidsplanning; logistiek", risico="regen/hagel net voor/tijdens oogst; hitte → kwaliteitsverlies"),
    dict(fase="nazorg", periode="aug–okt", beslissingen="zomersnoei; bodemherstel/bemesting; ziektepreventie (bacterievuur/Pseudomonas)", risico="te late zomersnoei → wondinfectie bij regen"),
]

df = pd.DataFrame(CALENDAR)


def _highlight_current(row):
    is_current = row["fase"] == ctx.stage
    return ["background-color: #fff3b0" if is_current else "" for _ in row]


st.caption(
    f"Huidige fase (sidebar): **{ctx.stage}** — gemarkeerd hieronder. "
    "Bron: Actua Steenfruit #6/#7 2026 (StonefruitConsult) + design doc Sec A.4."
)
st.dataframe(df.style.apply(_highlight_current, axis=1), width="stretch", hide_index=True)

st.divider()
st.subheader("Toelichting")
st.markdown(
    """
Deze kalender is de ruggengraat van het systeem — elke fase heeft een eigen
procedure-/beslissingsregister (shields + verplichte acties, zie ontwerp Sec B.6), dat in
een latere implementatiestap (Deel E, stap 3+) als een Captain-stijl `PROCEDURE_LIBRARY`
wordt gecodeerd.
"""
)
