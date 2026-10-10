"""Waterbalans-service: haalt weer op (verleden + verwachting), rekent de bodemvoorraad door en vat het samen.

Eén plek die zowel de Streamlit-weergave (``app/waterbalance_view.py``) als de adviseur-tool (``waterbalans`` in
``pipeline/orchard_tool_catalog.py``) gebruiken, zodat beide dezelfde, deterministische getallen tonen -- het taalmodel rekent nooit zelf
(ontwerp B.1/B.11). Het weer komt via injecteerbare ophaalfuncties binnen (test zonder netwerk; de pagina geeft gecachete varianten mee).

De bodemvoorraad wordt doorgerekend tot en met GISTEREN (de archief-API heeft vandaag nog niets) en daarna met de forecast (vandaag + 6 dagen):
de verwachting start dus met de werkelijke eindstand van het verleden.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from pipeline.orchard_water_balance import (CITATION, STATUS_DRY, STATUS_DRY_WARN, STATUS_WET, DayInput, DayResult, WaterBalanceConfig,
                                            knmi_deficit, period_summary, spinup_start, water_balance)

Rows = list[tuple[str, float, float | None]]   # (datum, neerslag mm, ET0 mm)


@dataclass(frozen=True)
class WaterState:
    results: list[DayResult]          # spin-up + verleden + verwachting, op datum
    forecast_from: str | None         # eerste verwachte dag (None = geen forecast)
    cfg: WaterBalanceConfig
    knmi: dict[str, float | None]
    start: str                        # eerste opgehaalde dag (begin van de opwarmperiode)
    end: str                          # laatste waargenomen dag
    forecast_error: str | None = None

    @property
    def observed(self) -> list[DayResult]:
        return [r for r in self.results if self.forecast_from is None or r.date < self.forecast_from]

    @property
    def forecast(self) -> list[DayResult]:
        return [r for r in self.results if self.forecast_from is not None and r.date >= self.forecast_from]


def compute_water_state(lat: float, lon: float, *, history_fetch: Callable[[float, float, str, str], Rows],
                        forecast_fetch: Callable[[float, float, int], Rows] | None = None, today: date | None = None,
                        period_days: int = 30, forecast_days: int = 7, cfg: WaterBalanceConfig | None = None,
                        irrigation: dict[str, float] | None = None, latest_archive: date | None = None) -> WaterState:
    """``history_fetch(lat, lon, start_iso, end_iso)`` en ``forecast_fetch(lat, lon, days)`` leveren (datum, neerslag, ET0)-rijen.
    Een mislukte forecast maakt de waterbalans van het verleden niet ongeldig: ``forecast_error`` meldt het."""
    today = today or date.today()
    end = min(today - timedelta(days=1), latest_archive or today - timedelta(days=1))
    start = spinup_start(end, period_days)
    history = history_fetch(round(lat, 4), round(lon, 4), start.isoformat(), end.isoformat())
    if not history:
        raise ValueError("geen weerdata voor de waterbalans")
    forecast: Rows = []
    error = None
    if forecast_fetch is not None and forecast_days > 0:
        try:
            forecast = [r for r in forecast_fetch(round(lat, 4), round(lon, 4), forecast_days) if r[0] > end.isoformat()]
        except Exception as exc:  # noqa: BLE001 -- the past is still valid
            error = f"{type(exc).__name__}: {exc}"
    irrigation = irrigation or {}
    inputs = [DayInput(d, p, e, irrigation.get(d, 0.0)) for d, p, e in history + forecast]
    cfg = cfg or WaterBalanceConfig()
    return WaterState(results=water_balance(inputs, cfg), forecast_from=forecast[0][0] if forecast else None, cfg=cfg,
                      knmi=dict(knmi_deficit(inputs)), start=start.isoformat(), end=end.isoformat(), forecast_error=error)


def outlook(forecast: list[DayResult]) -> dict:
    """Samenvatting van de verwachte dagen: totalen, bodemvocht aan het eind en de eerste dag met stress / te nat."""
    if not forecast:
        return {}
    s = period_summary(forecast)
    first = lambda statuses: next((r.date for r in forecast if r.status in statuses), None)  # noqa: E731
    return {"days": s["days"], "precipitation_mm": s["precipitation_mm"], "etc_mm": s["etc_mm"], "delta_mm": s["delta_mm"],
            "drainage_mm": s["drainage_mm"], "moisture_end_pct": forecast[-1].soil_moisture_pct, "status_end": forecast[-1].status,
            "first_stress_date": first({STATUS_DRY}), "first_warn_date": first({STATUS_DRY_WARN, STATUS_DRY}),
            "first_wet_date": first({STATUS_WET})}


def advisor_summary(state: WaterState) -> str:
    """Nederlandse feitentekst voor de adviseur-tool: alles komt uit de deterministische berekening; geen getal wordt door het model verzonnen."""
    obs = state.observed
    last = obs[-1]
    cfg = state.cfg

    def line(n: int) -> str:
        s = period_summary(obs[-n:])
        return (f"laatste {s['days']} dagen: neerslag {s['precipitation_mm']:.0f} mm"
                + (f" + beregening {s['irrigation_mm']:.0f} mm" if s["irrigation_mm"] else "")
                + f", gewasverdamping {s['etc_mm']:.0f} mm, delta {s['delta_mm']:+.0f} mm"
                + (f", afvoer {s['drainage_mm']:.0f} mm" if s["drainage_mm"] else ""))

    parts = [f"Waterbalans per {last.date} (FAO-56, indicatief; delta = neerslag + beregening - gewasverdamping):",
             f"- {line(7)}", f"- {line(30)}",
             f"- Bodemvocht nu: {last.soil_moisture_pct:.0f}% van het beschikbare water in de wortelzone, status: {last.status}"
             f" (stress begint onder {100 * (1 - cfg.depletion_fraction):.0f}%)."]
    deficit = state.knmi.get(last.date)
    if deficit is not None:
        parts.append(f"- Neerslagtekort sinds 1 april (KNMI-stijl, referentiegewas): {deficit:.0f} mm.")
    o = outlook(state.forecast)
    if o:
        parts.append(f"- Verwachting komende {o['days']} dagen: neerslag {o['precipitation_mm']:.0f} mm, gewasverdamping {o['etc_mm']:.0f} mm, "
                     f"delta {o['delta_mm']:+.0f} mm; bodemvocht aan het eind {o['moisture_end_pct']:.0f}% ({o['status_end']}).")
        if o["first_stress_date"]:
            parts.append(f"  Droogtestress verwacht vanaf {o['first_stress_date']}.")
        elif o["first_warn_date"]:
            parts.append(f"  Het wordt droog (let op) vanaf {o['first_warn_date']}.")
        if o["first_wet_date"]:
            parts.append(f"  Afvoer door veel regen (nat) verwacht vanaf {o['first_wet_date']}.")
    elif state.forecast_error:
        parts.append("- Verwachting niet beschikbaar (forecast tijdelijk niet op te halen).")
    parts.append(f"Aannames: grond '{cfg.soil}', wortelzone {cfg.root_depth_m:.1f} m (TAW {cfg.taw_mm:.0f} mm), ondergroei '{cfg.ground_cover}'. "
                 "Zonder grondwater-opstijging en zonder beregening is dit een pessimistische schatting; grond en wortelzone zijn nog niet voor dit perceel gemeten.")
    return "\n".join(parts)


SOURCE_LABEL = "Waterbalans (FAO-56, Open-Meteo; indicatief)"
__all__ = ["WaterState", "compute_water_state", "outlook", "advisor_summary", "SOURCE_LABEL", "CITATION"]
