"""Waarschuwingen -- geaggregeerde risico-alerts (design doc Sec A.6 'brown envelope' monitors)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchard_common import RISK_ORDER_WEIGHT, compute_season_snapshot, render_sidebar  # noqa: E402

import streamlit as st

st.set_page_config(page_title="Waarschuwingen", layout="wide")
st.title("Waarschuwingen")

ctx = render_sidebar(st)

with st.spinner("Live weerdata ophalen (Open-Meteo/Buienradar)..."):
    try:
        snap = compute_season_snapshot(ctx)
    except Exception as exc:
        st.error(f"Kon geen live weerdata ophalen: {exc}")
        st.stop()

alerts = []
for daily, frost in snap["frost_by_day"]:
    if RISK_ORDER_WEIGHT[frost.risk] >= RISK_ORDER_WEIGHT["hoog"]:
        alerts.append(("Nachtvorst", frost.risk, f"{daily.date}: {frost.note}", frost.source_citation))

suzukii = snap["suzukii"]
if RISK_ORDER_WEIGHT[suzukii.risk] >= RISK_ORDER_WEIGHT["hoog"]:
    alerts.append(("Suzuki-fruitvlieg", suzukii.risk, "Verhoogde kans op eiafzet komende 7 dagen.", suzukii.source_citation))

rain_crack = snap["rain_crack"]
if RISK_ORDER_WEIGHT[rain_crack.risk] >= RISK_ORDER_WEIGHT["hoog"]:
    alerts.append((
        "Vruchtbarsten", rain_crack.risk,
        f"{rain_crack.forecast_precip_mm_48h:.1f} mm verwacht binnen 48u tijdens fase '{ctx.stage}'.",
        rain_crack.source_citation,
    ))

chill = snap["chill"]
if chill.required_hours and chill.fraction_complete is not None and chill.fraction_complete < 0.5 and ctx.stage not in ("rust",):
    alerts.append((
        "Koude-uren achterstand", "matig",
        f"Slechts {chill.fraction_complete*100:.0f}% van de benodigde koude-uren voor {ctx.variety} is "
        "opgebouwd, terwijl de rustfase al voorbij lijkt te zijn — controleer dit handmatig.",
        chill.source_citation,
    ))

if not alerts:
    st.success("Geen actieve hoog/kritiek-risico waarschuwingen voor de komende 7 dagen.")
else:
    alerts.sort(key=lambda a: RISK_ORDER_WEIGHT[a[1]], reverse=True)
    for titel, risk, beschrijving, bron in alerts:
        st.markdown(f"### {titel} — {risk.upper()}")
        st.write(beschrijving)
        st.caption(f"Bron: {bron}")
        st.divider()

st.caption(
    "Dit is een pull-gebaseerde demo (ververs de pagina). Een echte proactieve push-melding "
    "(bijv. e-mail/sms zodra een monitor over de drempel gaat) staat als vervolgstap op de "
    "roadmap (ontwerp Deel E)."
)
