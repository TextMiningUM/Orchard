"""Boomgaard Dashboard -- actuele fenologie-/risicostatus (design doc Sec B.9)."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchard_common import compute_season_snapshot, render_sidebar  # noqa: E402

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from pipeline.orchard_tools import get_weather_window  # noqa: E402

st.set_page_config(page_title="Boomgaard Dashboard", layout="wide")
st.title("Boomgaard Dashboard")

ctx = render_sidebar(st)

with st.spinner("Live weerdata ophalen (Open-Meteo)..."):
    try:
        snap = compute_season_snapshot(ctx)
    except Exception as exc:
        st.error(f"Kon geen live weerdata ophalen: {exc}")
        st.stop()

chill_start, chill_end = snap["chill_window"]
chill = snap["chill"]
gdd = snap["gdd"]
suzukii = snap["suzukii"]
rain_crack = snap["rain_crack"]

st.subheader(f"Fase: **{ctx.stage}** · Ras: **{ctx.variety}** · Locatie: {ctx.lat:.3f}, {ctx.lon:.3f}")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown("### Koude-uren")
    st.metric("Opgebouwd", f"{chill.accumulated_hours:.0f} u", f"sinds {chill_start.isoformat()}")
    if chill.required_hours:
        st.progress(min(1.0, chill.fraction_complete))
        st.caption(f"{chill.fraction_complete*100:.0f}% van de {chill.required_hours:.0f} u die {ctx.variety} nodig heeft.")
    else:
        st.warning(f"Koude-uren-drempel voor '{ctx.variety}' nog niet gesourced (zie ontwerp Sec C.7).")
    st.caption(chill.source_citation)

with col2:
    st.markdown("### Groei (GDD)")
    st.metric("Cumulatief, komende 7 dagen", f"{gdd.accumulated_gdd:.1f}")
    st.caption(gdd.source_citation)

with col3:
    st.markdown("### Suzuki-fruitvlieg")
    st.metric("Risico (7d forecast)", suzukii.risk.upper())
    st.caption(suzukii.source_citation)

with col4:
    st.markdown("### Vruchtbarsten (regen)")
    st.metric("Risico (48u vooruit)", rain_crack.risk.upper())
    st.caption(f"{rain_crack.forecast_precip_mm_48h:.1f} mm verwacht · {rain_crack.source_citation}")

st.divider()
st.subheader("Nachtvorst-risico per dag (komende week)")
rows = []
for daily, frost in snap["frost_by_day"]:
    rows.append({
        "Datum": daily.date,
        "Tmin (°C)": round(daily.temp_min_c, 1) if daily.temp_min_c is not None else None,
        "Tmax (°C)": round(daily.temp_max_c, 1) if daily.temp_max_c is not None else None,
        "Neerslag (mm)": round(daily.precipitation_mm, 1) if daily.precipitation_mm is not None else None,
        "Vorstrisico": frost.risk, "Toelichting": frost.note,
    })
df = pd.DataFrame(rows)
st.dataframe(df, width="stretch", hide_index=True)

fig = go.Figure()
fig.add_trace(go.Scatter(x=df["Datum"], y=df["Tmax (°C)"], name="Tmax", line=dict(color="orange")))
fig.add_trace(go.Scatter(x=df["Datum"], y=df["Tmin (°C)"], name="Tmin", line=dict(color="blue")))
fig.add_bar(x=df["Datum"], y=df["Neerslag (mm)"], name="Neerslag (mm)", yaxis="y2", opacity=0.4)
fig.update_layout(
    yaxis=dict(title="Temperatuur (°C)"),
    yaxis2=dict(title="Neerslag (mm)", overlaying="y", side="right"),
    legend=dict(orientation="h"), height=400,
)
st.plotly_chart(fig, width="stretch")

st.caption(
    "Let op: alle drempels/thresholds op deze pagina zijn — tenzij anders vermeld — illustratief/generiek "
    "en nog niet gekalibreerd op dit specifieke bedrijf. Zie `design_cherry_orchard_advisor.md` Sec C.7."
)

st.divider()
st.subheader("Weer van de afgelopen periode")
st.caption(
    "Het komende weer (hierboven) is voor dagelijkse beslissingen belangrijker dan het "
    "verleden — deze sectie staat daarom onderaan, puur ter referentie/context."
)
period_days = st.slider(
    "Periode (aantal dagen terug vanaf vandaag)", min_value=7, max_value=90, value=30, step=1,
    help="Standaard 30 dagen ('afgelopen maand'), aanpasbaar.",
)
with st.spinner(f"Historisch weer ophalen (laatste {period_days} dagen)..."):
    try:
        past_rows, past_citation = get_weather_window(
            ctx.lat, ctx.lon, date.today().isoformat(), days_before=period_days, days_after=0,
        )
    except Exception as exc:
        past_rows, past_citation = [], None
        st.error(f"Kon historisch weer niet ophalen: {exc}")

if past_rows:
    past_df = pd.DataFrame([{
        "Datum": r.date,
        "Tmin (°C)": round(r.temp_min_c, 1) if r.temp_min_c is not None else None,
        "Tmax (°C)": round(r.temp_max_c, 1) if r.temp_max_c is not None else None,
        "Neerslag (mm)": round(r.precipitation_mm, 1) if r.precipitation_mm is not None else None,
        "Wind (km/u)": round(r.wind_speed_max_kmh, 1) if r.wind_speed_max_kmh is not None else None,
        "Windrichting": r.wind_direction_compass,
        "Zonuren": round(r.sunshine_duration_h, 1) if r.sunshine_duration_h is not None else None,
        "ET0 (mm)": round(r.et0_evapotranspiration_mm, 2) if r.et0_evapotranspiration_mm is not None else None,
    } for r in past_rows])

    pc1, pc2, pc3, pc4 = st.columns(4)
    pc1.metric(f"Totale neerslag ({period_days}d)", f"{past_df['Neerslag (mm)'].sum():.0f} mm")
    pc2.metric("Gem. Tmax", f"{past_df['Tmax (°C)'].mean():.1f} °C")
    pc3.metric("Gem. Tmin", f"{past_df['Tmin (°C)'].mean():.1f} °C")
    som_zonuren = past_df["Zonuren"].sum()
    pc4.metric("Totaal zonuren", f"{som_zonuren:.0f} u" if pd.notna(som_zonuren) else "n.v.t.")

    past_fig = go.Figure()
    past_fig.add_trace(go.Scatter(x=past_df["Datum"], y=past_df["Tmax (°C)"], name="Tmax", line=dict(color="orange")))
    past_fig.add_trace(go.Scatter(x=past_df["Datum"], y=past_df["Tmin (°C)"], name="Tmin", line=dict(color="blue")))
    past_fig.add_bar(x=past_df["Datum"], y=past_df["Neerslag (mm)"], name="Neerslag (mm)", yaxis="y2", opacity=0.4)
    past_fig.update_layout(
        yaxis=dict(title="Temperatuur (°C)"), yaxis2=dict(title="Neerslag (mm)", overlaying="y", side="right"),
        legend=dict(orientation="h"), height=350,
    )
    st.plotly_chart(past_fig, width="stretch")

    with st.expander("Volledige dagtabel (incl. wind/zon/ET0)"):
        st.dataframe(past_df, width="stretch", hide_index=True, height=300)
    st.caption(f"Bron: {past_citation}")
else:
    st.info("Geen historische weerdata beschikbaar voor deze periode.")
