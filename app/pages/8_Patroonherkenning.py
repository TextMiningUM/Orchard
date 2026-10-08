"""Patroonherkenning (design doc Sec A.6/B.4 vervolg) -- herkent automatisch de meest
opvallende, oogst-relevante patronen in de eigen logboeken (2013-2026) en laat vanuit elk
patroon direct doorklikken naar de onderliggende data.

Puur lezend, gebaseerd op `pipeline/orchard_patterns.py` (alle detectie-logica zit daar,
los getest met synthetische data -- deze pagina doet alleen het ophalen/cachen en tonen).
Geschikt voor de publieke read-only pod-deployment (geen schrijfacties).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchard_common import PATHS, render_sidebar  # noqa: E402

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from pipeline.orchard_patterns import LogEntry, Pattern, TARGET_CATEGORIES, detect_patterns, load_entries  # noqa: E402
from pipeline.orchard_disease_weather_links import compute_disease_weather_early_warnings  # noqa: E402
from pipeline.orchard_season_watch import (  # noqa: E402
    SeasonSignal,
    compute_pollination_season_watch,
    compute_weather_season_watch,
    detect_logbook_season_spikes,
    soil_ph_status_note,
)

st.set_page_config(page_title="Patroonherkenning", layout="wide")
st.title("Patroonherkenning")
st.caption(
    "Het systeem doorzoekt zelf de 14 jaar logboeken op de meest in het oog springende, "
    "oogst-relevante patronen: meerjaren-trends (seizoenstiming, behandelfrequentie, "
    "dosering) EN seizoenswaarschuwingen (wijkt het lopende/meest recente seizoen tot nu "
    "toe af van voorgaande jaren -- te warm, te droog/nat, een plaagexplosie, slecht "
    "bestuivingsweer?). Klik een patroon of waarschuwing open om de onderliggende "
    "logboek-regels te bekijken."
)

ctx = render_sidebar(st)

DB_PATH = PATHS.logbooks_dir / "orchard_logbook.db"
if not DB_PATH.exists():
    st.error(
        f"Database niet gevonden op `{DB_PATH}`. Bouw 'm eerst met:\n\n"
        "`.venv\\Scripts\\python.exe -m pipeline.ingest.build_logbook_database`"
    )
    st.stop()


@st.cache_data(show_spinner="Patronen herkennen in het logboek...")
def _cached_detect_patterns(db_path: str, mtime: float, top_n: int):
    conn = sqlite3.connect(db_path)
    try:
        return detect_patterns(conn, top_n=top_n)
    finally:
        conn.close()


def _fetch_entry_rows(entry_ids: list[int]) -> pd.DataFrame:
    """Drill-down helper: fetches the full logbook rows (date, opmerkingen, toepassingen,
    bronverwijzing) for a pattern's contributing entries, newest first."""
    if not entry_ids:
        return pd.DataFrame()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(entry_ids))
    rows = conn.execute(
        f"""SELECT e.id AS entry_id, p.jaar, p.bestand, p.pagina, e.datum_iso, e.datum_ruw,
                   e.opmerkingen, e.onzeker
            FROM entries e JOIN pages p ON e.page_id = p.id
            WHERE e.id IN ({placeholders})
            ORDER BY e.datum_iso IS NULL, e.datum_iso DESC""",
        entry_ids,
    ).fetchall()
    toep_by_entry: dict[int, list[str]] = {}
    for t in conn.execute(
        f"SELECT entry_id, middel, hoeveelheid FROM toepassingen WHERE entry_id IN ({placeholders}) ORDER BY entry_id, volgorde",
        entry_ids,
    ):
        toep_by_entry.setdefault(t["entry_id"], []).append(f"{t['middel']} ({t['hoeveelheid']})")
    conn.close()
    return pd.DataFrame([
        {
            "Datum": r["datum_iso"] or r["datum_ruw"], "Jaar": r["jaar"],
            "Toepassingen": ", ".join(toep_by_entry.get(r["entry_id"], [])) or "—",
            "Opmerkingen": r["opmerkingen"], "Onzeker": "ja" if r["onzeker"] else "",
            "Bron": f"{r['bestand']} p.{r['pagina']}",
        }
        for r in rows
    ])


def _render_trend_chart(pattern: Pattern) -> None:
    chart = pattern.chart
    fig = go.Figure()
    if chart["type"] == "bar_trend":
        fig.add_trace(go.Bar(x=chart["x"], y=chart["y"], name="Waargenomen", marker_color="#4C78A8"))
        fig.add_trace(go.Scatter(x=chart["x"], y=chart["trend_y"], name="Trend", line=dict(color="#E45756", dash="dash")))
    else:  # scatter_trend / line_trend
        mode = "markers" if chart["type"] == "scatter_trend" else "lines+markers"
        fig.add_trace(go.Scatter(x=chart["x"], y=chart["y"], mode=mode, name="Waargenomen", marker=dict(color="#4C78A8")))
        fig.add_trace(go.Scatter(x=chart["x"], y=chart["trend_y"], mode="lines", name="Trend", line=dict(color="#E45756", dash="dash")))
    fig.update_layout(
        height=280, margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Jaar", yaxis_title=chart.get("y_axis_title", ""),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, width="stretch")


_MAAND_LABELS = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


def _render_calendar_chart(pattern: Pattern) -> None:
    chart = pattern.chart
    fig = go.Figure(data=go.Heatmap(
        z=chart["z"], x=_MAAND_LABELS, y=chart["y"],
        colorscale="YlOrRd", colorbar=dict(title="Aantal"),
    ))
    fig.update_layout(height=80 + 28 * len(chart["y"]), margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, width="stretch")


KIND_LABELS = {
    "seizoenstiming": "Seizoenstiming verschuift",
    "frequentie": "Behandelfrequentie-trend",
    "dosering": "Doseringstrend",
}

SEVERITY_ORDER = {"hoog": 2, "matig": 1, "info": 0}
SEVERITY_ICON = {"hoog": "🔴", "matig": "🟠", "info": "ℹ️"}


@st.cache_data(show_spinner=False)
def _cached_load_entries(db_path: str, mtime: float) -> list[LogEntry]:
    conn = sqlite3.connect(db_path)
    try:
        return load_entries(conn)
    finally:
        conn.close()


@st.cache_data(show_spinner="Dit seizoen vergelijken met voorgaande jaren (weer)...", ttl="6h")
def _cached_weather_season_watch(lat: float, lon: float, target_year: int):
    return compute_weather_season_watch(lat, lon, target_year)


@st.cache_data(show_spinner="Bestuivingsweer tijdens de bloei controleren...", ttl="6h")
def _cached_pollination_season_watch(lat: float, lon: float, _entries: list[LogEntry], target_year: int):
    return compute_pollination_season_watch(lat, lon, _entries, target_year)


@st.cache_data(show_spinner="Weer van de laatste dagen vergelijken met eerdere uitbraken...", ttl="6h")
def _cached_disease_weather_early_warnings(lat: float, lon: float, _entries: list[LogEntry]):
    return compute_disease_weather_early_warnings(lat, lon, _entries)


def _render_signal_card(signal: SeasonSignal) -> None:
    with st.container(border=True):
        st.markdown(f"{SEVERITY_ICON.get(signal.severity, '')} **{signal.title}**")
        st.write(signal.summary)
        if signal.source_citation:
            st.caption(f"Bron: {signal.source_citation}")
        if signal.entry_ids:
            with st.expander(f"Onderliggende logboek-regels bekijken ({len(signal.entry_ids)})"):
                st.dataframe(_fetch_entry_rows(signal.entry_ids), width="stretch", hide_index=True)


all_entries = _cached_load_entries(str(DB_PATH), DB_PATH.stat().st_mtime)

st.subheader("Seizoenswaarschuwingen (dit seizoen vs. voorgaande jaren)")
jaren_met_data = sorted({e.date.year for e in all_entries if e.date is not None})
default_jaar = next(
    (j for j in reversed(jaren_met_data) if sum(1 for e in all_entries if e.date and e.date.year == j) >= 5),
    jaren_met_data[-1] if jaren_met_data else None,
)
if default_jaar is None:
    st.info("Geen gedateerde logboekregels gevonden om een seizoen mee te vergelijken.")
else:
    gekozen_jaar = st.selectbox(
        "Seizoen om te controleren", jaren_met_data, index=jaren_met_data.index(default_jaar),
        help="Standaard het meest recente jaar met voldoende logboekregels. Oudere jaren worden "
             "vergeleken alsof het hele seizoen (tot 1 november) al voorbij is.",
    )
    weer_signalen = _cached_weather_season_watch(ctx.lat, ctx.lon, gekozen_jaar)
    logboek_signalen = detect_logbook_season_spikes(all_entries, target_year=gekozen_jaar)
    bestuiving_signaal = _cached_pollination_season_watch(ctx.lat, ctx.lon, all_entries, gekozen_jaar)

    signalen = list(weer_signalen) + list(logboek_signalen)
    if bestuiving_signaal is not None:
        signalen.append(bestuiving_signaal)
    signalen.sort(key=lambda s: SEVERITY_ORDER.get(s.severity, 0), reverse=True)

    if not signalen:
        st.success(f"Geen afwijkende seizoenssignalen gevonden voor {gekozen_jaar} t.o.v. voorgaande jaren.")
    else:
        for s in signalen:
            _render_signal_card(s)
    _render_signal_card(soil_ph_status_note())

st.divider()
st.subheader("Preventieve risico-waarschuwingen (weer van de laatste dagen vs. wat vroeger een uitbraak voorafging)")
st.caption(
    "Anders dan hierboven (is dit seizoen anders dan normaal?) kijkt dit naar een directe "
    "relatie: voor elke categorie wordt het weer in de dagen vóór elke eerdere behandeling "
    "opgezocht, en vergeleken met het weer van de laatste 10 dagen nu. Alleen als de "
    "omstandigheden zowel qua weer ALS qua tijd-van-het-jaar overeenkomen met eerdere "
    "aanleidingen, wordt dit gemeld -- bedoeld om er eerder bij te zijn dan de eerste "
    "symptomen (zie `pipeline/orchard_disease_weather_links.py` voor de volledige methode "
    "en de beperkingen daarvan bij deze hoeveelheid data)."
)
preventieve_signalen = _cached_disease_weather_early_warnings(ctx.lat, ctx.lon, all_entries)
if not preventieve_signalen:
    st.success("Geen enkele categorie heeft nu weer dat lijkt op een eerdere aanleiding tot behandelen.")
else:
    for s in preventieve_signalen:
        _render_signal_card(s)

st.divider()
ranked_patterns, calendar_pattern = _cached_detect_patterns(str(DB_PATH), DB_PATH.stat().st_mtime, 8)

st.subheader("Automatisch gedetecteerde meerjaren-patronen (gerangschikt op belang voor de oogst)")
if not ranked_patterns:
    st.info(
        "Nog geen trendpatroon gevonden met voldoende jaren data "
        f"(minimaal {4} jaar met vermeldingen is nodig per categorie)."
    )
else:
    for i, pattern in enumerate(ranked_patterns, 1):
        with st.container(border=True):
            col_title, col_badge = st.columns([5, 1])
            col_title.markdown(f"**{i}. {pattern.title}**")
            col_badge.caption(f"{KIND_LABELS.get(pattern.kind, pattern.kind)} · belang {pattern.importance:.2f}")
            st.write(pattern.summary)
            chart_col, _ = st.columns([3, 1])
            with chart_col:
                _render_trend_chart(pattern)
            with st.expander(f"Onderliggende logboek-regels bekijken ({len(pattern.entry_ids)})"):
                st.dataframe(_fetch_entry_rows(pattern.entry_ids), width="stretch", hide_index=True)

st.divider()
st.subheader("Teeltkalender (altijd getoond, geen trend -- alle jaren samen)")
if calendar_pattern is None:
    st.info("Nog geen data om een kalenderoverzicht van te maken.")
else:
    st.caption(calendar_pattern.summary)
    _render_calendar_chart(calendar_pattern)
    with st.expander(f"Onderliggende logboek-regels bekijken ({len(calendar_pattern.entry_ids)})"):
        st.dataframe(_fetch_entry_rows(calendar_pattern.entry_ids), width="stretch", hide_index=True)

with st.expander("Hoe wordt 'belang voor de oogst' bepaald?"):
    st.markdown(
        "Elke categorie heeft een eigen, aanpasbare **belang-gewicht** (0-1) dat inschat hoe "
        "rechtstreeks het onderwerp de kersenoogst raakt (fruitvliegen/vruchtrot/bestuiving "
        "hoog, algemene bladvoeding laag) -- dit is een eigen inschatting van dit project, "
        "geen uit de literatuur overgenomen ranking (zie `pipeline/orchard_patterns.py`). "
        "Dat gewicht wordt vermenigvuldigd met de sterkte van de trend en hoeveel jaren data "
        "erachter zitten, zodat zowel 'belangrijk voor de oogst' als 'een echt robuust "
        "patroon' meetellen."
    )
    rows = [
        {"Categorie": spec["label"], "Belang-gewicht": spec["harvest_weight"], "Waarom": spec["why"]}
        for spec in TARGET_CATEGORIES.values()
    ]
    st.dataframe(pd.DataFrame(rows).sort_values("Belang-gewicht", ascending=False), width="stretch", hide_index=True)
