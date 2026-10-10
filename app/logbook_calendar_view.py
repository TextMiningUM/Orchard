"""Sectie "Wat deed ik rond deze tijd?": de logboek-kalender (ontwerp G.30), gedeeld door de pagina Gebruik van Middelen en eventuele andere pagina's.
Alle tellingen komen uit ``pipeline/orchard_logbook_calendar.py``; deze module toont alleen."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from pipeline.orchard_logbook_calendar import (CAVEAT, DEFAULT_WINDOW_DAYS, build_calendar, load_calendar_data)


@st.cache_data(show_spinner=False)
def cached_calendar_data(db_path: str, mtime: float):
    return load_calendar_data(Path(db_path))


def render_logbook_calendar(db_path: Path, today: date | None = None) -> None:
    today = today or date.today()
    st.subheader("Wat deed ik rond deze tijd?")
    st.caption("Per middel: in hoeveel jaren van je eigen logboek je het rond deze datum toepaste, het gebruikelijke interval en het doel uit je opmerkingen. "
               "Eigen historie, geen advies; hoeveelheden en toelatingsstatus staan hier bewust niet.")
    c1, c2 = st.columns([1, 2])
    ref = c1.date_input("Rond datum", value=today, key="lbcal_date", format="YYYY-MM-DD")
    window = c2.slider("Venster (± dagen)", 7, 30, DEFAULT_WINDOW_DAYS, 1, key="lbcal_window")
    data = cached_calendar_data(str(db_path), Path(db_path).stat().st_mtime)
    rep = build_calendar(data.entries, ref, window, removed_duplicates=data.removed_duplicates, verified=data.verified, total=data.total)
    nh = len(rep.history_years)
    if nh == 0:
        st.info("Te weinig jaren met logboekregels om een kalender te maken.")
        return
    if not rep.products:
        st.info("In dit venster staat in geen enkel jaar iets in het logboek.")
    else:
        st.dataframe(pd.DataFrame([{
            "Middel": p.middel, "Categorie": p.category_label, "Jaren": f"{len(p.years)} van {nh}", "Toepassingen": p.applications,
            "Interval (dagen)": p.median_interval_days, "Doel (opmerkingen)": ", ".join(f"{t} ({n}×)" for t, n in p.purposes),
            "Dit jaar": p.this_year,
        } for p in rep.products]), width="stretch", hide_index=True,
            column_config={"Toepassingen": st.column_config.NumberColumn(format="%d"), "Interval (dagen)": st.column_config.NumberColumn(format="%d"),
                           "Dit jaar": st.column_config.NumberColumn(format="%d")})
    if rep.this_year_comparable and rep.missing_this_year:
        st.warning("Gebruikelijk rond deze tijd, maar dit jaar nog niet in het logboek: "
                   + ", ".join(f"{p.middel} ({len(p.years_back)} van {nh} jaar)" for p in rep.missing_this_year[:8]))
    elif not rep.this_year_comparable:
        st.caption(f"Dit jaar ({ref.year}) staan er {rep.this_year_entries} regels in het logboek; te weinig om te zeggen wat er nog ontbreekt.")
    st.caption(f"Gebaseerd op {nh} jaar met logboek ({rep.history_years[0]}-{rep.history_years[-1]}); {rep.removed_duplicates} dubbel ingescande regels zijn "
               f"één keer geteld; {rep.verified} van {rep.total} regels zijn handmatig geverifieerd. {CAVEAT}")
