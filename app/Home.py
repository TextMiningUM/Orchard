"""Cherry Orchard Advisor -- Streamlit entry point (Home page).

Run with::

    .venv\\Scripts\\python.exe -m streamlit run app\\Home.py

Walking-skeleton v0 (design_cherry_orchard_advisor.md Deel E) -- deterministic phenology
core + real Open-Meteo/Buienradar tools, NO fine-tuned Mistral model yet (that is Deel E
steps 5-7). The Chat page is an explicitly-labelled rule-based placeholder until then.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchard_common import compute_season_snapshot, render_sidebar  # noqa: E402

import streamlit as st

st.set_page_config(page_title="Kersenboomgaard Adviseur", layout="wide")

st.title("Kersenboomgaard Adviseur")

_HERO_IMAGE = Path(__file__).resolve().parent.parent / "Images" / "kersenboomgaard-e1660373696699-658974110.jpg"
if _HERO_IMAGE.exists():
    st.image(str(_HERO_IMAGE), width="stretch", caption="De boomgaard")

st.caption(
    "Walking-skeleton v0 — deterministische fenologie-/risicokern + live weerdata. "
    "Zie `design_cherry_orchard_advisor.md` voor het volledige ontwerp."
)

ctx = render_sidebar(st)

st.markdown(
    """
Dit is het startpunt van de agentic adviseur voor de zoete-kersenteelt. Gebruik het menu
links (pagina's) om naar een specifieke functie te gaan:

- **Boomgaard Dashboard** — actuele koude-uren/GDD/risico-status (live weerdata)
- **Vraag de Adviseur** — chat-demo (nog regel-gebaseerd, geen getraind model)
- **Seizoensplanning** — de teeltkalender als referentie
- **Logboek** — doorzoek/voeg ingrepen toe (nog niet persistent)
- **Waarschuwingen** — actieve risico-alerts voor de komende dagen
"""
)

st.divider()
st.subheader("Snelle status")

with st.spinner("Live weerdata ophalen (Open-Meteo)..."):
    try:
        snap = compute_season_snapshot(ctx)
    except Exception as exc:  # network hiccup -- fail visibly, never show stale/fake data
        st.error(f"Kon geen live weerdata ophalen: {exc}")
        snap = None

if snap is not None:
    col1, col2, col3 = st.columns(3)
    chill = snap["chill"]
    col1.metric(
        "Koude-uren (sinds 1 nov)",
        f"{chill.accumulated_hours:.0f} u",
        f"{chill.fraction_complete*100:.0f}% van {chill.required_hours:.0f} u" if chill.required_hours else "drempel onbekend voor dit ras",
    )
    col2.metric("GDD (komende 7 dagen, cumulatief)", f"{snap['gdd'].accumulated_gdd:.1f}")
    col3.metric("Suzuki-fruitvlieg risico (7d forecast)", snap["suzukii"].risk.upper())
    st.caption(f"Bronnen: {snap['history'].source_citation} · {snap['forecast'].source_citation}")
