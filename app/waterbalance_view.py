"""Waterbalans-weergave: per dag de delta (neerslag + beregening - gewasverdamping) over de gekozen periode, met bodemvoorraad en status.

Gedeeld door het Boomgaard Dashboard (onderaan) en eventuele eigen pagina's; de berekening zelf staat in
``pipeline/orchard_water_balance.py`` (deterministisch, FAO-56, met bronvermelding en "illustratief"-labels).
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from pipeline import orchard_tools
from pipeline.orchard_water_balance import (CITATION, DEFAULT_ROOT_DEPTH_M, DEPLETION_FRACTION, DRY_WARN_FRACTION_OF_RAW,
                                            KNMI_CITATION, ROOT_DEPTH_RANGE_M, SOIL_PRESETS, STATUS_DRY, STATUS_DRY_WARN,
                                            STATUS_OK, STATUS_WET, DayInput, WaterBalanceConfig, cumulative_delta,
                                            knmi_deficit, period_summary, spinup_start, water_balance)

STATUS_ICON = {STATUS_OK: "🟢 ok", STATUS_DRY_WARN: "🟡 droog (let op)", STATUS_DRY: "🔴 te droog", STATUS_WET: "🔵 nat"}
POSITIVE, NEGATIVE = "#2e86c1", "#d35400"


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def fetch_daily_weather(lat: float, lon: float, start: str, end: str) -> list[tuple[str, float, float | None]]:
    """(datum, neerslag mm, ET0 mm) per dag uit de Open-Meteo-archief-API; 3 uur gecachet (de bron werkt maar 1x per dag bij)."""
    rows, _citation = orchard_tools.get_weather_history_detailed(lat, lon, start, end)
    return [(r.date, r.precipitation_mm or 0.0, r.et0_evapotranspiration_mm) for r in rows]


def delta_figure(df: pd.DataFrame) -> go.Figure:
    """Staven = delta per dag (blauw: meer water erbij dan het gewas verbruikt; oranje: tekort), lijn = cumulatief over de periode."""
    fig = go.Figure()
    fig.add_bar(x=df["Datum"], y=df["Delta (mm)"], name="Delta per dag (mm)",
                marker_color=[POSITIVE if v >= 0 else NEGATIVE for v in df["Delta (mm)"]],
                hovertemplate="%{x}<br>delta %{y:+.1f} mm<extra></extra>")
    fig.add_trace(go.Scatter(x=df["Datum"], y=df["Cumulatief (mm)"], name="Cumulatief over de periode (mm)", yaxis="y2",
                             line=dict(color="#555", width=2), hovertemplate="%{x}<br>cumulatief %{y:+.0f} mm<extra></extra>"))
    fig.add_hline(y=0, line_width=1, line_color="#999")
    fig.update_layout(yaxis=dict(title="Delta per dag (mm)", zeroline=True),
                      yaxis2=dict(title="Cumulatief (mm)", overlaying="y", side="right", showgrid=False),
                      legend=dict(orientation="h"), height=380, margin=dict(t=30))
    return fig


def moisture_figure(df: pd.DataFrame, depletion_fraction: float = DEPLETION_FRACTION) -> go.Figure:
    """Bodemvoorraad als % van het beschikbare water; onder de stresslijn neemt de opname van de boom af."""
    stress = 100.0 * (1.0 - depletion_fraction)
    warn = 100.0 * (1.0 - DRY_WARN_FRACTION_OF_RAW * depletion_fraction)
    fig = go.Figure()
    fig.add_hrect(y0=0, y1=stress, fillcolor="#e74c3c", opacity=0.10, line_width=0)
    fig.add_hrect(y0=stress, y1=warn, fillcolor="#f1c40f", opacity=0.10, line_width=0)
    fig.add_trace(go.Scatter(x=df["Datum"], y=df["Bodemvocht (%)"], name="Bodemvocht (% van beschikbaar water)",
                             line=dict(color="#1a5276", width=2)))
    fig.add_hline(y=stress, line_dash="dot", line_color="#c0392b",
                  annotation_text="vanaf hier neemt de opname af (stress)", annotation_position="bottom right")
    fig.update_layout(yaxis=dict(title="% van beschikbaar water", range=[0, 105]), height=260, margin=dict(t=20), showlegend=False)
    return fig


def build_frame(shown, knmi: dict[str, float | None]) -> pd.DataFrame:
    cum = cumulative_delta(shown)
    return pd.DataFrame([{
        "Datum": r.date, "Neerslag (mm)": round(r.precipitation_mm, 1), "Beregening (mm)": round(r.irrigation_mm, 1),
        "ET0 (mm)": round(r.et0_mm, 1) if not r.et0_missing else None, "Kc": round(r.kc, 2),
        "Gewasverdamping (mm)": round(r.etc_mm, 1), "Delta (mm)": round(r.delta_mm, 1), "Cumulatief (mm)": round(c, 1),
        "Afvoer (mm)": round(r.drainage_mm, 1), "Bodemvocht (%)": round(r.soil_moisture_pct, 0),
        "Neerslagtekort KNMI-stijl (mm)": None if knmi.get(r.date) is None else round(knmi[r.date], 0),
        "Status": STATUS_ICON[r.status],
    } for r, c in zip(shown, cum)])


def render_waterbalance_section(lat: float, lon: float, today: date | None = None) -> None:
    today = today or date.today()
    st.subheader("Waterbalans: te droog of te nat?")
    st.caption(
        "Per dag de **delta** = neerslag (+ beregening) min wat het gewas aan water vraagt (gewasverdamping = gewasfactor × referentieverdamping ET0). "
        "Boven 0: er kwam meer water bij dan de boom verbruikte; onder 0: de bodemvoorraad slinkt. De bodemvoorraad (een 'emmer' in de wortelzone) "
        "loopt vanaf 1 maart mee, zodat te nat (afvoer) en te droog (stress) zichtbaar worden."
    )
    with st.expander("Instellingen waterbalans (grondsoort, wortelzone, ondergroei, periode)", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        soil = c1.selectbox("Grondsoort", list(SOIL_PRESETS), index=list(SOIL_PRESETS).index("leem"), key="wb_soil",
                            help="Beschikbaar bodemwater per grondsoort uit FAO-56 tabel 19. Zonder bodemanalyse is dit een aanname.")
        root = c2.slider("Wortelzone (m)", ROOT_DEPTH_RANGE_M[0] - 0.5, ROOT_DEPTH_RANGE_M[1], DEFAULT_ROOT_DEPTH_M, 0.1, key="wb_root",
                         help="FAO-56 noemt 1,0-2,0 m voor kers; een zwakgroeiende onderstam (bijv. Gisela) wortelt ondieper.")
        cover = c3.radio("Ondergroei", ["gras", "kaal"], index=0, key="wb_cover", horizontal=True,
                         help="Gras tussen de rijen verhoogt de verdamping (FAO-56 tabel 12: actieve ondergroei).")
        period = c4.slider("Periode (dagen terug)", 7, 120, 30, 1, key="wb_period")
    with st.expander("Beregening of andere aanvoer invoeren (mm per dag)", expanded=False):
        st.caption("Het logboek bevat geen beregening; vul hier in wat er bij kwam (mm op de boomstrook, alleen voor deze sessie).")
        irr_df = st.data_editor(pd.DataFrame({"Datum": pd.Series(dtype="object"), "Beregening (mm)": pd.Series(dtype="float")}),
                                num_rows="dynamic", key="wb_irrigation", width="stretch",
                                column_config={"Datum": st.column_config.DateColumn("Datum", format="YYYY-MM-DD"),
                                               "Beregening (mm)": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, format="%.1f")})

    end = min(today - timedelta(days=1), orchard_tools.latest_available_archive_date())
    start = spinup_start(end, period)
    try:
        with st.spinner("Weerdata voor de waterbalans ophalen (Open-Meteo)..."):
            raw = fetch_daily_weather(round(lat, 4), round(lon, 4), start.isoformat(), end.isoformat())
    except Exception as exc:  # noqa: BLE001 -- fail visibly, never show invented data
        st.error(f"Kon de weerdata voor de waterbalans niet ophalen: {exc}")
        return
    if not raw:
        st.info("Geen weerdata beschikbaar voor deze periode.")
        return

    irrigation: dict[str, float] = {}
    for _, row in irr_df.dropna(subset=["Datum", "Beregening (mm)"]).iterrows():
        irrigation[str(row["Datum"])[:10]] = irrigation.get(str(row["Datum"])[:10], 0.0) + float(row["Beregening (mm)"])
    inputs = [DayInput(d, p, e, irrigation.get(d, 0.0)) for d, p, e in raw]
    cfg = WaterBalanceConfig(soil=soil, root_depth_m=float(root), ground_cover=cover)
    results = water_balance(inputs, cfg)
    shown = results[-period:]
    knmi = dict(knmi_deficit(inputs))
    df = build_frame(shown, knmi)
    summary = period_summary(shown)
    last = shown[-1]

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric(f"Neerslag ({summary['days']} d)", f"{summary['precipitation_mm']:.0f} mm",
              f"+ {summary['irrigation_mm']:.0f} mm beregening" if summary["irrigation_mm"] else None, delta_color="off")
    m2.metric("Gewasverdamping", f"{summary['etc_mm']:.0f} mm")
    m3.metric("Delta periode", f"{summary['delta_mm']:+.0f} mm", "overschot" if summary["delta_mm"] >= 0 else "tekort",
              delta_color="normal" if summary["delta_mm"] >= 0 else "inverse")
    m4.metric("Afvoer naar diepere lagen", f"{summary['drainage_mm']:.0f} mm")
    m5.metric("Bodemvocht nu", f"{last.soil_moisture_pct:.0f}%", STATUS_ICON[last.status], delta_color="off")
    deficit_now = knmi.get(last.date)
    if deficit_now is not None:
        m6.metric("Neerslagtekort sinds 1 apr", f"{deficit_now:.0f} mm", "KNMI-stijl, referentiegewas", delta_color="off")
    else:  # outside 1 April - 30 September: show the final value of the season that just ended
        season_end = next(((d, v) for d, v in reversed(list(knmi.items())) if v is not None), None)
        m6.metric("Neerslagtekort sinds 1 apr", "n.v.t." if season_end is None else f"{season_end[1]:.0f} mm",
                  "buiten 1 apr-30 sep" if season_end is None else f"eindstand {season_end[0]}", delta_color="off")

    st.plotly_chart(delta_figure(df), width="stretch")
    st.plotly_chart(moisture_figure(df, cfg.depletion_fraction), width="stretch")
    if summary["stress_days"] or summary["wet_days"]:
        st.caption(f"In deze periode: {summary['stress_days']} dag(en) droogtestress en {summary['wet_days']} dag(en) nat (afvoer).")
    if summary["et0_missing_days"]:
        st.warning(f"Voor {summary['et0_missing_days']} dag(en) ontbreekt de verdamping in de bron; die dagen tellen als 0 mm verdamping.")

    with st.expander("Dagtabel (neerslag, verdamping, delta, bodemvocht, status)"):
        st.dataframe(df.iloc[::-1], width="stretch", hide_index=True, height=360,
                     column_config={c: st.column_config.NumberColumn(format="%.1f") for c in
                                    ("Neerslag (mm)", "Beregening (mm)", "ET0 (mm)", "Gewasverdamping (mm)", "Delta (mm)",
                                     "Cumulatief (mm)", "Afvoer (mm)")})
    st.caption(
        f"Opgebouwd vanaf {start.isoformat()}. TAW {cfg.taw_mm:.0f} mm, RAW {cfg.raw_mm:.0f} mm. "
        "**Let op:** dit is een indicatie. Zonder capillaire opstijging uit het grondwater (veel Nederlandse percelen hebben die) en zonder ingevoerde beregening "
        "is de schatting pessimistisch; grondsoort en wortelzone zijn aannames tot er een bodemanalyse of vochtsensor is. "
        f"{CITATION} {KNMI_CITATION} Bron weerdata: Open-Meteo."
    )
