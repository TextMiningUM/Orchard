"""Agentic tools: real, verified external data sources the advisor can call.

Mirrors the ``ToolSpec``/tool-registry convention of Auto Pilot's ``captain_tools.py`` /
``chief_engineer_tools.py`` -- see ``design_cherry_orchard_advisor.md`` Sec B.5/C.4. Every
function here either (a) calls a real, documented, free/open API (weather, rain-nowcast),
or (b) is an explicit, clearly-labelled STUB that raises ``NotImplementedError`` rather
than fabricating data -- never silently return a fake toelating/soil value (design doc Sec
B.1/B.11 hard rule: a dosage/registration claim must come from a real, verified source or
not be made at all).

Network calls use only the stdlib (``urllib``) so this module has zero third-party
dependency for its core weather tools -- ``requests`` is NOT required to run these.
"""
from __future__ import annotations

from datetime import date as _date_cls, timedelta as _timedelta_cls

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pipeline.orchard_phenology_spec import DailyReading, TemperatureReading

_USER_AGENT = "OrchardAdvisor/0.1 (design walking-skeleton; see design_cherry_orchard_advisor.md)"
_TIMEOUT_S = 15


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── § 1  Open-Meteo: forecast (future, up to 16 days) ───────────────────────────────────
# design_cherry_orchard_advisor.md Sec C.4 -- free, no API key, non-commercial use.
_OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


@dataclass(frozen=True)
class WeatherSeries:
    """Container for a fetched weather series -- both hourly and daily aggregates,
    ready to feed straight into ``pipeline.orchard_phenology_spec``'s functions."""
    hourly: list[TemperatureReading]
    daily: list[DailyReading]
    source_citation: str


def get_weather_forecast(lat: float, lon: float, days: int = 7) -> WeatherSeries:
    """Fetch an hourly + daily forecast (temperature, precipitation) via Open-Meteo.

    ``days`` is capped at 16 (Open-Meteo's own forecast horizon).
    """
    days = max(1, min(days, 16))
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,precipitation",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "forecast_days": days,
        "timezone": "Europe/Amsterdam",
    }
    url = f"{_OPEN_METEO_FORECAST_URL}?{urllib.parse.urlencode(params)}"
    data = _http_get_json(url)
    hourly = [
        TemperatureReading(timestamp=datetime.fromisoformat(t), temp_c=temp)
        for t, temp in zip(data["hourly"]["time"], data["hourly"]["temperature_2m"])
    ]
    daily = [
        DailyReading(date=d, temp_min_c=tmin, temp_max_c=tmax, precipitation_mm=precip)
        for d, tmin, tmax, precip in zip(
            data["daily"]["time"], data["daily"]["temperature_2m_min"],
            data["daily"]["temperature_2m_max"], data["daily"]["precipitation_sum"],
        )
    ]
    return WeatherSeries(
        hourly=hourly, daily=daily,
        source_citation=f"Open-Meteo Forecast API ({_OPEN_METEO_FORECAST_URL}), opgehaald {datetime.now(timezone.utc).isoformat()}",
    )


def get_forecast_water_inputs(lat: float, lon: float, days: int = 7) -> list[tuple[str, float, float | None]]:
    """(datum, neerslag mm, ET0 mm) per dag voor de komende ``days`` dagen (vanaf vandaag) uit de Open-Meteo-forecast; voedt de waterbalans-vooruitblik.
    ET0 is de FAO-56 Penman-Monteith-referentieverdamping die Open-Meteo zelf berekent."""
    days = max(1, min(days, 16))
    params = {"latitude": lat, "longitude": lon, "forecast_days": days, "timezone": "Europe/Amsterdam",
              "daily": "precipitation_sum,et0_fao_evapotranspiration"}
    data = _http_get_json(f"{_OPEN_METEO_FORECAST_URL}?{urllib.parse.urlencode(params)}")
    d = data.get("daily", {})
    times = d.get("time", [])
    precip = d.get("precipitation_sum") or [0.0] * len(times)
    et0 = d.get("et0_fao_evapotranspiration") or [None] * len(times)
    return [(t, precip[i] or 0.0, et0[i]) for i, t in enumerate(times)]


def get_weather_history(lat: float, lon: float, start_date: str, end_date: str) -> WeatherSeries:
    """Fetch an hourly + daily historical series via Open-Meteo's Historical Weather API.

    ``start_date``/``end_date`` are ISO dates ("YYYY-MM-DD"); data is available back to 1940.
    """
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start_date, "end_date": end_date,
        "hourly": "temperature_2m,precipitation",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "Europe/Amsterdam",
    }
    url = f"{_OPEN_METEO_ARCHIVE_URL}?{urllib.parse.urlencode(params)}"
    data = _http_get_json(url)
    hourly = [
        TemperatureReading(timestamp=datetime.fromisoformat(t), temp_c=temp)
        for t, temp in zip(data["hourly"]["time"], data["hourly"]["temperature_2m"])
        if temp is not None
    ]
    daily = [
        DailyReading(date=d, temp_min_c=tmin, temp_max_c=tmax, precipitation_mm=precip or 0.0)
        for d, tmin, tmax, precip in zip(
            data["daily"]["time"], data["daily"]["temperature_2m_min"],
            data["daily"]["temperature_2m_max"], data["daily"]["precipitation_sum"],
        )
        if tmin is not None and tmax is not None
    ]
    return WeatherSeries(
        hourly=hourly, daily=daily,
        source_citation=f"Open-Meteo Historical Weather API ({_OPEN_METEO_ARCHIVE_URL}), "
                         f"periode {start_date}..{end_date}, opgehaald {datetime.now(timezone.utc).isoformat()}",
    )


# ── § 1b  Open-Meteo: gedetailleerd weer-venster rond een datum (voor logboek-popup) ────
@dataclass(frozen=True)
class DetailedDailyReading:
    """Eén dag se weer, met de extra velden die voor een kersenteler relevant zijn naast
    de kale temperatuur/neerslag uit DailyReading: wind (snelheid + richting, relevant
    voor bestuiving/spuitdrift), zonuren (relevant voor rijping/suikergehalte) en
    referentie-verdamping ET0 (relevant voor irrigatiebehoefte)."""
    date: str
    temp_min_c: float
    temp_max_c: float
    precipitation_mm: float
    wind_speed_max_kmh: float | None
    wind_direction_deg: float | None
    wind_direction_compass: str | None
    sunshine_duration_h: float | None
    et0_evapotranspiration_mm: float | None


_COMPASS_POINTS = ("N", "NNO", "NO", "ONO", "O", "OZO", "ZO", "ZZO",
                   "Z", "ZZW", "ZW", "WZW", "W", "WNW", "NW", "NNW")


def _degrees_to_compass(deg: float | None) -> str | None:
    if deg is None:
        return None
    idx = int((deg / 22.5) + 0.5) % 16
    return _COMPASS_POINTS[idx]


def latest_available_archive_date() -> _date_cls:
    """Open-Meteo's Historical/Archive API has NO data yet for "today" itself (confirmed
    2026-10-09: requesting end_date=today returns HTTP 400, yesterday already works fine) --
    callers that build an end-date from ``date.today()`` for the archive endpoint must clamp
    to this instead, or risk a crash the one day a year someone runs it at the season's very
    start. Centralised here so every "current season so far" caller (``orchard_season_watch``,
    ``orchard_disease_weather_links``) applies the exact same clamp."""
    return _date_cls.today() - _timedelta_cls(days=1)


def get_weather_history_detailed(lat: float, lon: float, start_date: str, end_date: str) -> tuple[list[DetailedDailyReading], str]:
    """Haalt een gedetailleerd dagelijks weerbeeld op voor een expliciete periode (ISO
    "YYYY-MM-DD".."YYYY-MM-DD") -- wind (snelheid + dominante richting), zonuren, en
    ET0-referentieverdamping, bovenop de kale temperatuur/neerslag uit
    ``get_weather_history()``. Gedeelde basis voor ``get_weather_window()`` (venster rond
    één datum) en ``pipeline.orchard_season_watch`` (lang seizoensbereik)."""
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start_date, "end_date": end_date,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                 "windspeed_10m_max,winddirection_10m_dominant,sunshine_duration,"
                 "et0_fao_evapotranspiration",
        "timezone": "Europe/Amsterdam",
    }
    url = f"{_OPEN_METEO_ARCHIVE_URL}?{urllib.parse.urlencode(params)}"
    data = _http_get_json(url)
    d = data.get("daily", {})
    times = d.get("time", [])
    rows = []
    for i, dt in enumerate(times):
        wind_dir = (d.get("winddirection_10m_dominant") or [None] * len(times))[i]
        sunshine_s = (d.get("sunshine_duration") or [None] * len(times))[i]
        rows.append(DetailedDailyReading(
            date=dt,
            temp_min_c=(d.get("temperature_2m_min") or [None] * len(times))[i],
            temp_max_c=(d.get("temperature_2m_max") or [None] * len(times))[i],
            precipitation_mm=(d.get("precipitation_sum") or [0.0] * len(times))[i] or 0.0,
            wind_speed_max_kmh=(d.get("windspeed_10m_max") or [None] * len(times))[i],
            wind_direction_deg=wind_dir,
            wind_direction_compass=_degrees_to_compass(wind_dir),
            sunshine_duration_h=(sunshine_s / 3600.0) if sunshine_s is not None else None,
            et0_evapotranspiration_mm=(d.get("et0_fao_evapotranspiration") or [None] * len(times))[i],
        ))
    citation = (
        f"Open-Meteo Historical Weather API ({_OPEN_METEO_ARCHIVE_URL}), periode {start_date}..{end_date}"
    )
    return rows, citation


def get_weather_window(
    lat: float, lon: float, center_date: str, days_before: int = 7, days_after: int = 7,
) -> tuple[list[DetailedDailyReading], str]:
    """Haalt een gedetailleerd dagelijks weerbeeld op rond ``center_date`` (ISO
    "YYYY-MM-DD"), standaard een week ervoor en een week erna -- bedoeld voor de
    Logboek-Verifieren-popup, zodat een logboek-ingreep in zijn volledige weerscontext
    bekeken kan worden (niet alleen de ene dag zelf). Gebruikt dezelfde Open-Meteo
    Historical Weather API als ``get_weather_history()``, met extra dagwaarden: wind
    (snelheid + dominante richting), zonuren, en ET0-referentieverdamping."""
    from datetime import date as _date, timedelta as _timedelta
    center = _date.fromisoformat(center_date)
    start = center - _timedelta(days=days_before)
    end = center + _timedelta(days=days_after)
    rows, _citation = get_weather_history_detailed(lat, lon, start.isoformat(), end.isoformat())
    citation = (
        f"Open-Meteo Historical Weather API ({_OPEN_METEO_ARCHIVE_URL}), "
        f"venster {start.isoformat()}..{end.isoformat()} rond {center_date}"
    )
    return rows, citation


# ── § 1c  Geocoding: adres -> coördinaten ────────────────────────────────────────────────
# Nominatim (OpenStreetMap) is primair: dit is een echte straatadres-geocoder (huisnummer +
# postcode + plaats), in tegenstelling tot Open-Meteo's eigen Geocoding API die alleen
# plaatsnamen/steden herkent (bleek in de praktijk geen volledig straatadres te kunnen
# vinden, zie design_cherry_orchard_advisor.md se praktijktest). Open-Meteo blijft als
# fallback voor het geval Nominatim niets vindt (bijv. bij een zeer korte/vage zoekterm).
# Gratis, geen API-key, wel Nominatim's eigen gebruiksbeleid: duidelijke User-Agent
# verplicht, max. ~1 request/seconde (hier ruim binnen, 1 klik = 1 request).
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


def _geocode_nominatim(query: str) -> dict | None:
    params = {"q": query, "format": "json", "limit": 1, "countrycodes": "nl", "addressdetails": 1}
    url = f"{_NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
    data = _http_get_json(url)
    if not data:
        return None
    r = data[0]
    return {"lat": float(r["lat"]), "lon": float(r["lon"]), "display_name": r.get("display_name", query)}


def _geocode_open_meteo(query: str) -> dict | None:
    params = {"name": query, "count": 1, "language": "nl", "format": "json"}
    url = f"{_OPEN_METEO_GEOCODING_URL}?{urllib.parse.urlencode(params)}"
    data = _http_get_json(url)
    results = data.get("results")
    if not results:
        return None
    r = results[0]
    display = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x)
    return {"lat": r["latitude"], "lon": r["longitude"], "display_name": display}


def geocode_address(query: str) -> dict | None:
    """Zoekt een (straat-)adres of plaatsnaam op en geeft het beste resultaat terug als
    ``{"lat", "lon", "display_name"}``, of ``None`` als er écht niets gevonden is bij geen
    van beide bronnen. Gebruikt voor de "Boomgaard-instellingen"-sidebar (ontwerp Sec B.9)
    zodat de teler een adres kan intypen i.p.v. zelf lat/lon te moeten opzoeken. Probeert
    Nominatim eerst (volledige adressen), valt terug op Open-Meteo (plaatsnamen) als
    Nominatim niets vindt of tijdelijk niet bereikbaar is."""
    try:
        result = _geocode_nominatim(query)
        if result is not None:
            return result
    except Exception:
        pass
    return _geocode_open_meteo(query)


# ── § 2  Buienradar: short-term rain nowcast (NL only) ──────────────────────────────────
_BUIENRADAR_RAINTEXT_URL = "https://gpsgadget.buienradar.nl/data/raintext"


@dataclass(frozen=True)
class RainNowcast:
    """5-minute-resolution precipitation nowcast, up to 2 hours ahead (NL coverage only)."""
    values_mm_per_h: list[tuple[datetime, float]]
    source_citation: str


def get_rain_nowcast(lat: float, lon: float) -> RainNowcast:
    """Fetch a 2-hour, 5-minute-resolution rain nowcast from Buienradar (NL only, free for
    non-commercial use with attribution -- design doc Sec C.4). Each line in the response
    is ``"<value 000-255>|<HH:MM>"``, where value maps to mm/h via Buienradar's own log
    scale; this function returns the raw decoded mm/h estimate per the publicly documented
    conversion (``10 ** ((value - 109) / 32)``)."""
    url = f"{_BUIENRADAR_RAINTEXT_URL}?lat={lat}&lon={lon}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        text = resp.read().decode("utf-8")
    now = datetime.now()
    values: list[tuple[datetime, float]] = []
    for line in text.strip().splitlines():
        if "|" not in line:
            continue
        raw, hhmm = line.split("|")
        mm_per_h = 10 ** ((int(raw) - 109) / 32)
        hh, mm = (int(x) for x in hhmm.split(":"))
        ts = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        values.append((ts, round(mm_per_h, 3)))
    return RainNowcast(
        values_mm_per_h=values,
        source_citation=f"Buienradar raintext endpoint ({_BUIENRADAR_RAINTEXT_URL}), "
                         f"niet-commercieel gebruik, bron vermelden verplicht.",
    )


# ── § 3  Ctgb toelating (gewasbeschermingsmiddelen) — via de OPEN Ctgb MST public API ──────────
# Hard rule (design doc Sec B.1/B.11): a medicine/dosage claim must come from a real, verified
# source. Sinds 2026-10-10 is dat de officiele Ctgb-API (geen abonnement nodig, zie G.31); de
# oude bulk-export-URL blijft dood. Bij een storing en zonder cache gooit dit een
# CtgbUnavailable (nooit een verzonnen status).
def check_ctgb_toelating(middel: str, gewas: str = "kers") -> dict:
    """Zoekt ``middel`` (merknaam of deel ervan) in de Ctgb-databank en geeft status + gebruiksvoorschriften voor kers terug.
    Alleen kers wordt ondersteund. Raises ``pipeline.orchard_ctgb.CtgbUnavailable`` als de API en de cache beide ontbreken."""
    from pipeline.orchard_ctgb import SOURCE, format_card, format_model_facts, lookup
    if gewas.strip().lower() not in ("kers", "kersen", "zoete kers"):
        raise ValueError(f"check_ctgb_toelating() ondersteunt alleen kers, niet {gewas!r}.")
    lk = lookup(middel)
    return {
        "middel": middel, "as_of": lk.as_of.isoformat(), "source": SOURCE, "card": format_card(lk), "facts": format_model_facts(lk),
        "products": [{"name": p.name, "registration_number": p.registration_number, "expired": p.expired,
                      "expiration": p.expiration.isoformat() if p.expiration else None, "cherry_uses": [u.name for u in p.cherry_uses],
                      "manual_url": p.manual_url} for p in lk.products],
    }


# ── § 4  Bodeminformatie (BOFEK/Bodemdata.nl) — STUB, NOT yet wired ─────────────────────
def get_soil_info(lat: float, lon: float) -> dict:
    """STUB. Real implementation must call the Bodemdata.nl/BOFEK API (design doc Sec
    C.4) -- not yet wired. Raises deliberately rather than inventing a bodemtype."""
    raise NotImplementedError(
        "get_soil_info() is nog niet aangesloten op de echte Bodemdata.nl/BOFEK-API "
        f"(zie design_cherry_orchard_advisor.md Sec C.4) voor lat={lat}, lon={lon}."
    )
