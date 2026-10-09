"""Shared helpers for the Cherry Orchard Advisor Streamlit app.

Imported by every page in ``app/pages/`` -- keeps the sys.path bootstrap, default
location/variety config, and small formatting helpers in exactly one place (same
"never fork a second copy" discipline as the rest of this project).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

# ``app/`` and ``app/pages/`` both need the repo root on sys.path to import
# ``core``/``pipeline`` as normal packages -- Streamlit runs each page as a standalone
# script, so this must run at the top of every entry point, not just once.
_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

import json
import re
import sqlite3

from core.paths import AgentPaths  # noqa: E402
from pipeline.orchard_phenology_spec import (  # noqa: E402
    evaluate_chill_hours,
    evaluate_frost_risk,
    evaluate_gdd,
    evaluate_rain_crack_risk,
    evaluate_suzukii_risk,
)
from pipeline.orchard_tools import (  # noqa: E402
    get_rain_nowcast,
    get_weather_forecast,
    get_weather_history,
    get_weather_window,
)

PATHS = AgentPaths.orchard()
LOGBOOK_DB_PATH = PATHS.logbooks_dir / "orchard_logbook.db"
SETTINGS_FILE = PATHS.data_root / "orchard_settings.json"


def load_settings() -> dict:
    """Persisted sidebar settings (lat/lon/address) -- survives across app restarts,
    unlike plain ``st.session_state``. Returns ``{}`` if never saved yet or unreadable."""
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_logbook_image_path(raw_path: str | None) -> Path | None:
    """The logbook database's `image_path` column was written once with an ABSOLUTE path from
    wherever the OCR/vision-transcriptie-stap oorspronkelijk draaide (altijd Windows, zie
    `Data/Orchard/OrchardLogbooks/_transcripts/*.json`) -- dat exacte pad lost alleen op DIE
    ene machine op. Elke andere machine (bv. de cloud-pod, Linux) heeft hetzelfde scanbestand
    onder een ANDERE absolute root nodig (ontdekt doordat de scans op de pod niet zichtbaar
    waren terwijl ze lokaal wel werkten). Leidt een draagbaar pad af door alleen het deel vanaf
    `_raw_page_images` te behouden en dat opnieuw samen te voegen onder DEZE machine's eigen
    `PATHS.logbooks_dir` -- werkt ongeacht welke machine het pad oorspronkelijk wegschreef, en
    ongeacht Windows (`\\`) vs POSIX (`/`) padscheidingstekens in de opgeslagen string. Returns
    ``None`` if the marker isn't found at all (defensive fallback for an unexpected format)."""
    if not raw_path:
        return None
    marker = "_raw_page_images"
    parts = re.split(r"[\\/]", raw_path)
    if marker not in parts:
        return None
    tail = parts[parts.index(marker) + 1:]
    if not tail:
        return None
    return PATHS.logbooks_dir / marker / Path(*tail)


def get_logbook_conn(st):
    """Shared, cached read/write connection to ``orchard_logbook.db`` -- used by both the
    Logboek (search) page and the Logboek Verifiëren (human-review) page, so there is only
    ever one open connection per Streamlit session (see design doc Sec B.4)."""
    @st.cache_resource
    def _connect(db_path_str: str) -> sqlite3.Connection:
        conn = sqlite3.connect(db_path_str, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    if not LOGBOOK_DB_PATH.exists():
        return None
    return _connect(str(LOGBOOK_DB_PATH))


def render_weather_dialog_button(st, lat: float, lon: float, center_date_iso: str, key_suffix: str = "", label: str | None = None) -> None:
    """Shared button + popup: weer van de week ervoor en de week erna rond een
    logboek-datum -- geeft de teler de volledige weerscontext bij een ingreep (niet alleen
    de ene dag zelf), met de variabelen die voor kersenteelt relevant zijn: temperatuur,
    neerslag, wind (snelheid + richting, relevant voor bestuiving/spuitdrift), zonuren
    (rijping) en ET0-referentieverdamping (irrigatiebehoefte). Gebruikt door zowel de
    Logboek- (doorzoeken) als de Logboek Verifiëren-pagina (nooit een tweede kopie, zie
    design doc se eigen "reuse before rebuild"-conventie)."""
    import pandas as pd
    import plotly.graph_objects as go

    from pipeline.orchard_tools import get_weather_window

    @st.dialog("Weer rondom deze datum", width="large")
    def _dialog():
        with st.spinner("Historisch weer ophalen (Open-Meteo)..."):
            try:
                rows, citation = get_weather_window(lat, lon, center_date_iso, days_before=7, days_after=7)
            except Exception as exc:
                st.error(f"Kon weerdata niet ophalen: {exc}")
                return
        if not rows:
            st.warning("Geen weerdata beschikbaar voor dit venster.")
            return

        df = pd.DataFrame([{
            "Datum": r.date,
            "Tmin (°C)": round(r.temp_min_c, 1) if r.temp_min_c is not None else None,
            "Tmax (°C)": round(r.temp_max_c, 1) if r.temp_max_c is not None else None,
            "Neerslag (mm)": round(r.precipitation_mm, 1) if r.precipitation_mm is not None else None,
            "Wind (km/u)": round(r.wind_speed_max_kmh, 1) if r.wind_speed_max_kmh is not None else None,
            "Windrichting": r.wind_direction_compass,
            "Zonuren": round(r.sunshine_duration_h, 1) if r.sunshine_duration_h is not None else None,
            "ET0 (mm)": round(r.et0_evapotranspiration_mm, 2) if r.et0_evapotranspiration_mm is not None else None,
        } for r in rows])

        def _highlight_center(row):
            return ["background-color: #fff3b0" if row["Datum"] == center_date_iso else "" for _ in row]

        styler = df.style.apply(_highlight_center, axis=1).format({
            "Tmin (°C)": "{:.1f}", "Tmax (°C)": "{:.1f}", "Neerslag (mm)": "{:.1f}",
            "Wind (km/u)": "{:.1f}", "Zonuren": "{:.1f}", "ET0 (mm)": "{:.2f}",
        }, na_rep="—")
        st.dataframe(styler, width="stretch", hide_index=True)

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["Datum"], y=df["Tmax (°C)"], name="Tmax", line=dict(color="orange")))
        fig.add_trace(go.Scatter(x=df["Datum"], y=df["Tmin (°C)"], name="Tmin", line=dict(color="blue")))
        fig.add_bar(x=df["Datum"], y=df["Neerslag (mm)"], name="Neerslag (mm)", yaxis="y2", opacity=0.4)
        fig.add_vline(x=center_date_iso, line_dash="dash", line_color="red", annotation_text="logboek-datum")
        fig.update_layout(
            yaxis=dict(title="Temperatuur (°C)"), yaxis2=dict(title="Neerslag (mm)", overlaying="y", side="right"),
            legend=dict(orientation="h"), height=350, margin=dict(t=20, b=20),
        )
        st.plotly_chart(fig, width="stretch")
        st.caption(f"Locatie: {lat:.4f}, {lon:.4f} (sidebar-instelling) · Bron: {citation}")
        if st.button("Sluiten", key=f"close_weather_dialog_{key_suffix}"):
            st.rerun()

    button_label = label or f"Weer rondom {center_date_iso} bekijken (1 week ervoor/erna)"
    if st.button(button_label, key=f"weather_btn_{key_suffix}_{center_date_iso}"):
        _dialog()

# Illustrative default location: Betuwe fruitteeltgebied (geen echte bedrijfslocatie --
# wordt overschreven zodra de teler een adres opzoekt via de sidebar, zie render_sidebar()
# hieronder; dan persisteert orchard_settings.json de echte locatie).
DEFAULT_LAT = 51.88
DEFAULT_LON = 5.57

# Enige rasdrempel die al echt gesourced is (Actua Steenfruit #6, 2026) -- zie
# pipeline.orchard_phenology_spec.KNOWN_CHILL_HOUR_REQUIREMENTS.
KNOWN_VARIETIES = ("Kordia", "Regina", "Sweetheart", "Vanda (nog niet gesourced)")

RISK_ORDER_WEIGHT = {"laag": 0, "matig": 1, "hoog": 2, "kritiek": 3}


def default_stage_for_month(month: int) -> str:
    """Rough calendar-based default phenology stage (design doc Sec A.4 table) -- purely a
    sensible starting value for the sidebar selector, NOT a claim about this orchard's
    actual current stage. The teler should correct this manually until a real
    bloom-date-prediction model exists (backlog, see design doc Sec E)."""
    mapping = {
        11: "rust", 12: "rust", 1: "rust", 2: "knopzwelling",
        3: "bloei", 4: "vruchtzetting", 5: "groei", 6: "groei",
        7: "rijping", 8: "oogst", 9: "nazorg", 10: "nazorg",
    }
    return mapping.get(month, "rust")


@dataclass
class OrchardContext:
    lat: float
    lon: float
    variety: str
    stage: str


def get_context_from_session(st) -> OrchardContext:
    """Read the sidebar-controlled context out of ``st.session_state`` with safe defaults."""
    return OrchardContext(
        lat=st.session_state.get("orchard_lat", DEFAULT_LAT),
        lon=st.session_state.get("orchard_lon", DEFAULT_LON),
        variety=st.session_state.get("orchard_variety", "Kordia"),
        stage=st.session_state.get("orchard_stage", default_stage_for_month(date.today().month)),
    )


def render_sidebar(st) -> OrchardContext:
    """Laadt/seedt de boomgaard-instellingen (locatie/ras/fase) in ``st.session_state`` en
    geeft ze terug als ``OrchardContext`` -- rendert zelf NIETS meer in de zijbalk.

    Vroeger stonden hier de volledige invoervelden zelf (adres zoeken, lat/lon, ras, fase),
    later een compacte samenvatting + link -- beide namen nog ruimte in de zijbalk in,
    terwijl de teler zelf prima weet dat die instellingen onder "Instellingen" in het menu
    staan. De invoervelden zelf staan op `app/pages/11_Instellingen.py`."""
    # First render of this session: seed session_state from the persisted settings file
    # (orchard_settings.json) instead of the hardcoded placeholder, so a geocoded address
    # from a PREVIOUS run/restart is remembered (design doc Sec B.9 request: "onthouden").
    if "orchard_lat" not in st.session_state:
        persisted = load_settings()
        st.session_state["orchard_lat"] = persisted.get("lat", DEFAULT_LAT)
        st.session_state["orchard_lon"] = persisted.get("lon", DEFAULT_LON)
        st.session_state["orchard_address"] = persisted.get("address", "")
    st.session_state.setdefault("orchard_variety", "Kordia")
    st.session_state.setdefault("orchard_stage", default_stage_for_month(date.today().month))

    return OrchardContext(
        lat=st.session_state["orchard_lat"], lon=st.session_state["orchard_lon"],
        variety=st.session_state["orchard_variety"], stage=st.session_state["orchard_stage"],
    )


def compute_season_snapshot(ctx: OrchardContext):
    """One real, live snapshot of everything the Dashboard/Waarschuwingen pages need:
    chill-hours-to-date, forecast-based GDD/frost/suzukii/rain-crack verdicts. Calls the
    real Open-Meteo APIs (pipeline.orchard_tools) -- network required."""
    today = date.today()
    # Chill-hours window: 1 Nov of the relevant dormant season through today.
    chill_start_year = today.year - 1 if today.month >= 7 else today.year - 1
    chill_start = date(chill_start_year, 11, 1) if today.month < 7 else date(today.year, 11, 1)
    if today < chill_start:
        chill_start = date(today.year - 1, 11, 1)
    chill_end = min(today, date(chill_start.year + 1, 2, 28))

    history = get_weather_history(ctx.lat, ctx.lon, chill_start.isoformat(), chill_end.isoformat())
    forecast = get_weather_forecast(ctx.lat, ctx.lon, days=7)

    chill_verdict = evaluate_chill_hours(ctx.variety, accumulated_hours=_count_chill_hours(history.hourly))
    gdd_verdict = evaluate_gdd(forecast.daily)
    frost_verdicts = [
        evaluate_frost_risk(ctx.stage, d.temp_min_c) for d in forecast.daily
    ]
    suzukii_verdict = evaluate_suzukii_risk(forecast.hourly)
    rain_48h = sum(d.precipitation_mm for d in forecast.daily[:2])
    rain_crack_verdict = evaluate_rain_crack_risk(ctx.stage, rain_48h)

    return {
        "history": history, "forecast": forecast,
        "chill": chill_verdict, "gdd": gdd_verdict,
        "frost_by_day": list(zip(forecast.daily, frost_verdicts)),
        "suzukii": suzukii_verdict, "rain_crack": rain_crack_verdict,
        "chill_window": (chill_start, chill_end),
    }


def _count_chill_hours(hourly_readings) -> float:
    from pipeline.orchard_phenology_spec import compute_chill_hours
    return compute_chill_hours(hourly_readings)
