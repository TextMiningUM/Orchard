"""Daily soil-water balance for the cherry orchard: "is it too dry or too wet?" as a day-by-day delta.

Deterministic and dependency-free, like ``orchard_phenology_spec`` (the LLM never computes these numbers; it may only call this
and explain). Method: the FAO-56 single-crop-coefficient soil-water "bucket" (Allen et al. 1998, FAO Irrigation and Drainage Paper
56, chapters 6 and 8; https://www.fao.org/4/x0490e/x0490e00.htm):

    ETc      = Kc x ET0                                              (eq. 58)   crop water demand of the day
    delta    = P + I - ETc                                                       THE daily delta: water in minus water demand
    Ks       = 1                          if Dr <= RAW                          (eq. 84)
             = (TAW - Dr) / ((1-p) TAW)   otherwise                                 reduced uptake when the soil is dry
    Dr_i     = Dr_(i-1) - (P + I) + Ks x ETc + DP                    (eq. 85)   root-zone depletion (0 = field capacity)
    DP       = max(0, (P + I) - Ks x ETc - Dr_(i-1))                 (eq. 88)   deep percolation: what the bucket cannot hold
    TAW      = 1000 (theta_FC - theta_WP) Zr                         (eq. 82)   total available water [mm]
    RAW      = p x TAW                                                          readily available water [mm]

Water IN: rain (Open-Meteo) and irrigation (entered by the grower; the logbook records none). Water OUT: crop evapotranspiration
and drainage below the root zone. Runoff and capillary rise are neglected (documented simplifications, see CITATION).

Labels, as everywhere in this project -- "real, cited" vs "illustrative":
  * REAL, cited (FAO-56): the equations, Kc for stone fruit (table 12), soil water per soil type (table 19), p = 0.50 and the
    root-zone range 1.0-2.0 m for cherries (table 22), and the KNMI definition of the precipitation deficit.
  * ILLUSTRATIVE: the calendar of the Kc curve (own approximation of FAO's growth-stage lengths for a Dutch cherry orchard), the
    default root depth (1.0 m, lower end -- dwarfing rootstocks root shallower), the default soil, the assumption that the soil is
    at field capacity at the start of the spin-up (1 March), and the thresholds of the status labels. Real calibration needs this
    orchard's soil (bodemanalyse) and soil-moisture sensors (design doc C.4/C.7).

Safe to run locally (pure stdlib).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

CITATION = (
    "FAO-56 bodemwaterbalans (Allen et al. 1998, FAO Irrigation and Drainage Paper 56, hoofdstuk 6 en 8): Kc 'stone fruit' (tabel 12), "
    "bodemwater per grondsoort (tabel 19), kers p = 0,50 en wortelzone 1,0-2,0 m (tabel 22). Afvoer over het oppervlak en capillaire opstijging "
    "zijn verwaarloosd. Indicatief: Kc-kalender, wortelzone, grondsoort en de beginvoorraad (veldcapaciteit op 1 maart) zijn aannames, "
    "nog niet gekalibreerd op dit perceel (ontwerp C.4/C.7)."
)
KNMI_CITATION = (
    "KNMI neerslagtekort: cumulatief (verdamping - neerslag) vanaf 1 april, nooit onder 0 "
    "(https://www.knmi.nl/kennis-en-datacentrum/achtergrond/achtergrondinformatie-neerslagtekort). Hier met FAO-56 ET0 "
    "(Open-Meteo, Penman-Monteith) in plaats van Makkink: kleine afwijking, zelfde betekenis."
)

# FAO-56 table 19: (theta_FC - theta_WP) [m3/m3]; value = middle of the FAO range, range kept for display.
SOIL_PRESETS: dict[str, tuple[float, tuple[float, float], str]] = {
    "zand": (0.08, (0.05, 0.11), "Sand"),
    "lemig zand": (0.09, (0.06, 0.12), "Loamy sand"),
    "zandleem": (0.13, (0.11, 0.15), "Sandy loam"),
    "leem": (0.155, (0.13, 0.18), "Loam"),
    "siltleem": (0.16, (0.13, 0.19), "Silt loam"),
    "klei": (0.16, (0.12, 0.20), "Clay"),
}

# FAO-56 table 12, "Stone fruit" in a climate with killing frost: (Kc ini, Kc mid, Kc end). FAO lists apricots, peaches, pears,
# plums and pecans in this category; cherries are not named separately, so these are an approximation for cherry.
KC_BY_COVER: dict[str, tuple[float, float, float]] = {
    "kaal": (0.45, 0.90, 0.65),   # no ground cover
    "gras": (0.50, 1.15, 0.90),   # active ground cover (grass alleys)
}

DEPLETION_FRACTION = 0.50          # FAO-56 table 22: apples, cherries, pears
ROOT_DEPTH_RANGE_M = (1.0, 2.0)    # FAO-56 table 22
DEFAULT_ROOT_DEPTH_M = 1.0

# Illustrative status thresholds
DRY_WARN_FRACTION_OF_RAW = 0.75    # depletion above 75% of RAW: "droog (let op)"
WET_DRAINAGE_MM_3D = 5.0           # >= 5 mm drained below the root zone in 3 days: "nat"

STATUS_OK, STATUS_DRY_WARN, STATUS_DRY, STATUS_WET = "ok", "droog (let op)", "te droog", "nat"


def crop_coefficient(day: date, ground_cover: str = "gras") -> float:
    """Kc for a calendar day (illustrative calendar, FAO values): Kc_ini until 1 April and from 15 November; linear to Kc_mid on 1 June;
    Kc_mid until 15 September; linear to Kc_end on 1 November; back to Kc_ini on 15 November (winter: dormant tree + soil evaporation)."""
    ini, mid, end = KC_BY_COVER[ground_cover]
    y = day.year
    a1, a2, a3, a4, a5 = date(y, 4, 1), date(y, 6, 1), date(y, 9, 15), date(y, 11, 1), date(y, 11, 15)

    def lerp(d0: date, d1: date, v0: float, v1: float) -> float:
        return v0 + (v1 - v0) * (day - d0).days / (d1 - d0).days

    if day < a1 or day >= a5:
        return ini
    if day < a2:
        return lerp(a1, a2, ini, mid)
    if day < a3:
        return mid
    if day < a4:
        return lerp(a3, a4, mid, end)
    return lerp(a4, a5, end, ini)


@dataclass(frozen=True)
class WaterBalanceConfig:
    soil: str = "leem"
    root_depth_m: float = DEFAULT_ROOT_DEPTH_M
    ground_cover: str = "gras"
    depletion_fraction: float = DEPLETION_FRACTION
    start_depletion_mm: float = 0.0   # 0 = field capacity at the start of the series

    @property
    def taw_mm(self) -> float:
        return 1000.0 * SOIL_PRESETS[self.soil][0] * self.root_depth_m

    @property
    def raw_mm(self) -> float:
        return self.depletion_fraction * self.taw_mm


@dataclass(frozen=True)
class DayInput:
    date: str                      # ISO
    precipitation_mm: float
    et0_mm: float | None           # None = missing in the weather source
    irrigation_mm: float = 0.0


@dataclass(frozen=True)
class DayResult:
    date: str
    precipitation_mm: float
    irrigation_mm: float
    et0_mm: float
    et0_missing: bool
    kc: float
    etc_mm: float                  # crop water demand (Kc x ET0)
    etc_actual_mm: float           # Ks x ETc: what the tree could actually take up
    ks: float
    delta_mm: float                # P + I - ETc  (the daily delta)
    drainage_mm: float             # DP: lost below the root zone
    depletion_mm: float            # Dr at the end of the day (0 = field capacity, TAW = wilting point)
    soil_moisture_pct: float       # share of the available water that is still in the root zone
    status: str


def water_balance(days: list[DayInput], cfg: WaterBalanceConfig = WaterBalanceConfig()) -> list[DayResult]:
    """Runs the bucket over the days (sorted by date). Mass balance holds exactly: sum(P + I) - sum(Ks x ETc) - sum(DP) = Dr_start - Dr_end."""
    taw, raw, p = cfg.taw_mm, cfg.raw_mm, cfg.depletion_fraction
    dr = min(max(cfg.start_depletion_mm, 0.0), taw)
    out: list[DayResult] = []
    drain_hist: list[float] = []
    for d in sorted(days, key=lambda x: x.date):
        day = date.fromisoformat(d.date)
        missing = d.et0_mm is None
        et0 = 0.0 if missing else max(0.0, d.et0_mm)
        kc = crop_coefficient(day, cfg.ground_cover)
        etc = kc * et0
        ks = 1.0 if dr <= raw else max(0.0, (taw - dr) / ((1.0 - p) * taw))
        etc_act = ks * etc
        inflow = max(0.0, d.precipitation_mm) + max(0.0, d.irrigation_mm)
        new_dr = dr - inflow + etc_act
        dp = 0.0
        if new_dr < 0.0:
            dp, new_dr = -new_dr, 0.0
        if new_dr > taw:                       # cannot be drier than the wilting point
            etc_act -= new_dr - taw
            new_dr = taw
        dr = new_dr
        drain_hist.append(dp)
        recent_drain = sum(drain_hist[-3:])
        if ks < 1.0:
            status = STATUS_DRY
        elif dr > DRY_WARN_FRACTION_OF_RAW * raw:
            status = STATUS_DRY_WARN
        elif recent_drain >= WET_DRAINAGE_MM_3D:
            status = STATUS_WET
        else:
            status = STATUS_OK
        out.append(DayResult(
            date=d.date, precipitation_mm=d.precipitation_mm, irrigation_mm=d.irrigation_mm, et0_mm=et0, et0_missing=missing,
            kc=kc, etc_mm=etc, etc_actual_mm=etc_act, ks=ks, delta_mm=inflow - etc, drainage_mm=dp, depletion_mm=dr,
            soil_moisture_pct=100.0 * (1.0 - dr / taw) if taw else 0.0, status=status,
        ))
    return out


def window(results: list[DayResult], start: str, end: str) -> list[DayResult]:
    return [r for r in results if start <= r.date <= end]


def cumulative_delta(results: list[DayResult]) -> list[float]:
    """Running sum of the daily delta over the shown period (restarts at 0 on the first shown day)."""
    total, out = 0.0, []
    for r in results:
        total += r.delta_mm
        out.append(total)
    return out


def period_summary(results: list[DayResult]) -> dict:
    return {
        "days": len(results),
        "precipitation_mm": sum(r.precipitation_mm for r in results),
        "irrigation_mm": sum(r.irrigation_mm for r in results),
        "etc_mm": sum(r.etc_mm for r in results),
        "delta_mm": sum(r.delta_mm for r in results),
        "drainage_mm": sum(r.drainage_mm for r in results),
        "stress_days": sum(1 for r in results if r.status == STATUS_DRY),
        "wet_days": sum(1 for r in results if r.status == STATUS_WET),
        "et0_missing_days": sum(1 for r in results if r.et0_missing),
    }


def knmi_deficit(days: list[DayInput]) -> list[tuple[str, float | None]]:
    """KNMI-style cumulative precipitation deficit: sum of (ET0 - P) from 1 April, never below 0; ``None`` outside 1 April - 30 September.
    Reference-crop based (no Kc, no soil): a country-wide drought indicator that growers know, shown next to the orchard-specific balance."""
    out: list[tuple[str, float | None]] = []
    deficit, year = 0.0, None
    for d in sorted(days, key=lambda x: x.date):
        day = date.fromisoformat(d.date)
        if not (date(day.year, 4, 1) <= day <= date(day.year, 9, 30)):
            out.append((d.date, None))
            continue
        if year != day.year:
            deficit, year = 0.0, day.year
        deficit = max(0.0, deficit + (d.et0_mm or 0.0) - d.precipitation_mm)
        out.append((d.date, deficit))
    return out


def spinup_start(end: date, period_days: int) -> date:
    """First day to fetch so that the bucket has a warm-up before the shown period: 1 March of the year (so the KNMI deficit from 1 April
    is complete), or of the previous year when that leaves less than 30 days of warm-up."""
    start = date(end.year, 3, 1)
    if start > end - timedelta(days=period_days + 30):
        start = date(end.year - 1, 3, 1)
    return start
