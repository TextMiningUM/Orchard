"""Tool catalogue for the ReACT-style Qwen chat agent (``pipeline/orchard_agent.py``).

Binds the project's existing deterministic data sources (live weather, phenology risk
calculations, the Track 1 RAG knowledge base, and the explicit guardrail stubs) as
individually callable "tools" the LLM may request mid-conversation -- same shape as Auto
Pilot's ``app/chief_engineer_tool_catalog.py``/``app/captain_tool_catalog.py``, simplified
since Orchard's tools take at most one simple argument (no nested JSON schemas needed yet).

None of these tools let the LLM compute a number itself -- every one calls straight into
already-reviewed code (``pipeline/orchard_phenology_spec.py``, ``pipeline/orchard_tools.py``,
``pipeline/orchard_rag.py``) and returns plain, cited Dutch text. This is the same
"deterministic-core-first" rule as the rest of the project, just exposed as tool calls instead
of (or in addition to) the keyword router in ``app/pages/2_Vraag_de_Adviseur.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pipeline.orchard_rag import RagIndex, format_context, format_sources, retrieve


@dataclass
class ToolResult:
    facts: str
    sources: list[str] = field(default_factory=list)
    card: str = ""   # markdown shown to the user VERBATIM by the app (e.g. the Ctgb dose card); never passed through the model


@dataclass
class BoundTool:
    name: str
    description: str  # shown verbatim to the LLM in the tool list
    arg_hint: str | None  # e.g. "aantal dagen (geheel getal)" -- None means no argument
    fn: Callable[[str | None], ToolResult]


def _weer_vooruitzicht(_arg: str | None, snapshot: dict) -> ToolResult:
    forecast = snapshot["forecast"]
    lines = [
        f"{d.date}: {d.temp_min_c:.1f}-{d.temp_max_c:.1f}°C, {d.precipitation_mm:.1f} mm neerslag"
        for d in forecast.daily
    ]
    return ToolResult(facts="Weersvooruitzicht (7 dagen):\n" + "\n".join(lines),
                       sources=[forecast.source_citation])


def _weer_geschiedenis(arg: str | None, ctx, snapshot: dict) -> ToolResult:
    from datetime import date
    from pipeline.orchard_tools import get_weather_window
    try:
        n_days = max(1, min(90, int(arg))) if arg else 30
    except ValueError:
        n_days = 30
    rows, citation = get_weather_window(ctx.lat, ctx.lon, date.today().isoformat(),
                                        days_before=n_days, days_after=0)
    total_precip = sum(r.precipitation_mm for r in rows)
    avg_tmax = sum(r.temp_max_c for r in rows if r.temp_max_c is not None) / max(1, len(rows))
    return ToolResult(
        facts=(f"Afgelopen {n_days} dagen: totale neerslag {total_precip:.1f} mm, "
               f"gemiddelde dagmax {avg_tmax:.1f}°C."),
        sources=[citation],
    )


def _koude_uren(_arg: str | None, ctx, snapshot: dict) -> ToolResult:
    c = snapshot["chill"]
    if c.required_hours:
        facts = (f"{ctx.variety} heeft nu {c.accumulated_hours:.0f} van de {c.required_hours:.0f} "
                 f"benodigde koude-uren ({c.fraction_complete * 100:.0f}%).")
    else:
        facts = f"{c.accumulated_hours:.0f} koude-uren opgebouwd; drempel voor '{ctx.variety}' nog niet gesourced."
    return ToolResult(facts=facts, sources=[c.source_citation])


def _vorst_risico(_arg: str | None, ctx, snapshot: dict) -> ToolResult:
    risky = [f for _d, f in snapshot["frost_by_day"] if f.risk in ("hoog", "kritiek")]
    if not risky:
        return ToolResult(
            facts=f"Geen verhoogd vorstrisico voor fase '{ctx.stage}' in de komende 7 dagen.",
            sources=[snapshot["forecast"].source_citation],
        )
    return ToolResult(facts="Vorstrisico gevonden:\n" + "\n".join(f.note for f in risky),
                       sources=[risky[0].source_citation])


def _suzuki_risico(_arg: str | None, snapshot: dict) -> ToolResult:
    s = snapshot["suzukii"]
    return ToolResult(facts=f"Suzuki-fruitvlieg-risico: {s.risk.upper()}.", sources=[s.source_citation])


def _vruchtbarsten_risico(_arg: str | None, ctx, snapshot: dict) -> ToolResult:
    r = snapshot["rain_crack"]
    return ToolResult(
        facts=(f"Vruchtbarsten-risico voor fase '{ctx.stage}': {r.risk.upper()} "
               f"({r.forecast_precip_mm_48h:.1f} mm verwacht komende 48u)."),
        sources=[r.source_citation],
    )


def _ctgb_toelating(arg: str | None) -> ToolResult:
    """Echte Ctgb-lookup (ontwerp G.31). Het model krijgt status + verwijzing zonder doseringen; de voorschriftkaart met de letterlijke getallen gaat
    via ``card`` rechtstreeks naar de gebruiker."""
    from pipeline.orchard_ctgb import SOURCE, CtgbUnavailable, format_card, format_model_facts, lookup
    name = (arg or "").strip()
    if not name:
        return ToolResult(facts="COMPLIANCE-GUARDRAIL: geen middelnaam meegegeven aan ctgb_toelating; vraag de teler om de merknaam van het middel.")
    try:
        lk = lookup(name)
    except CtgbUnavailable as exc:
        return ToolResult(facts=f"COMPLIANCE-GUARDRAIL: de Ctgb-databank is nu niet te bereiken ({exc}). Doe geen uitspraak over toelating of dosering "
                                f"van {name!r}; verwijs naar ctgb.nl en het etiket.")
    return ToolResult(facts=format_model_facts(lk), sources=[SOURCE], card=format_card(lk))


def _middel_opzoeken(arg: str | None) -> ToolResult:
    from pipeline.orchard_ctgb import SOURCE
    from pipeline.orchard_logbook_calendar import load_calendar_data
    from pipeline.orchard_middel_lookup import format_facts, format_full_card, middel_opzoeken
    name = (arg or "").strip()
    if not name:
        return ToolResult(facts="Geen merknaam meegegeven aan middel_opzoeken.")
    advies = middel_opzoeken(load_calendar_data().entries, name)
    return ToolResult(facts=format_facts(advies), sources=[SOURCE, "Eigen logboek 2013-heden (niet geverifieerd)"], card=format_full_card(advies))


def _kennisbank_zoeken(arg: str | None, rag_index: RagIndex | None) -> ToolResult:
    if rag_index is None:
        return ToolResult(facts="Kennisbank-index is nog niet gebouwd (draai build_orchard_rag.py).")
    query = arg or ""
    if not query.strip():
        return ToolResult(facts="Geen zoekterm meegegeven aan kennisbank_zoeken.")
    hits = retrieve(query, rag_index, k=4)
    return ToolResult(facts=format_context(hits), sources=format_sources(hits))


def _logboek_zoeken(arg: str | None, logbook_index) -> ToolResult:
    query = (arg or "").strip()
    if not query:
        return ToolResult(facts="Geen zoekterm meegegeven aan logboek_zoeken.")
    from pipeline.orchard_logbook_rag import format_logbook, format_sources as logbook_sources
    hits, trace = logbook_index.search(query, k=6)
    note = ""
    if trace["hints"]["years"] or trace["hints"]["months"] or trace["hints"]["dates"]:
        if not trace["time_filtered"]:
            note = "LET OP: voor die periode staat niets in het logboek; dit zijn de dichtstbijzijnde regels.\n"
    return ToolResult(facts=note + format_logbook(hits), sources=logbook_sources(hits))


def _waterbalans(_arg: str | None, ctx) -> ToolResult:
    from pipeline import orchard_tools
    from pipeline.orchard_water_service import SOURCE_LABEL, advisor_summary, compute_water_state

    def history(lat, lon, start, end):
        rows, _citation = orchard_tools.get_weather_history_detailed(lat, lon, start, end)
        return [(r.date, r.precipitation_mm or 0.0, r.et0_evapotranspiration_mm) for r in rows]

    try:
        state = compute_water_state(ctx.lat, ctx.lon, history_fetch=history, forecast_fetch=orchard_tools.get_forecast_water_inputs,
                                    latest_archive=orchard_tools.latest_available_archive_date())
    except Exception as exc:  # noqa: BLE001 -- say so instead of inventing numbers
        return ToolResult(facts=f"Waterbalans niet te berekenen (weerdata niet bereikbaar: {exc}). Geef geen getallen.")
    return ToolResult(facts=advisor_summary(state), sources=[SOURCE_LABEL])


def build_tool_catalog(ctx, snapshot: dict | None, rag_index: RagIndex | None) -> dict[str, BoundTool]:
    """Returns the full tool catalogue, each tool already bound to the current `ctx`
    (location/variety/stage), `snapshot` (this session's compute_season_snapshot() result --
    None skips the snapshot-dependent tools), and `rag_index` (None skips the knowledge-base
    search tool, with a clear "not built yet" fact instead of crashing)."""
    catalog: dict[str, BoundTool] = {
        "kennisbank_zoeken": BoundTool(
            name="kennisbank_zoeken",
            description="Doorzoek de Track 1-kennisbank (WUR/USDA/EU/Netafim/OSU-documenten) op een "
                         "onderwerp. Gebruik dit voor elke vraag over vaktechnische kennis.",
            arg_hint="een korte Nederlandse of Engelse zoekvraag",
            fn=lambda arg: _kennisbank_zoeken(arg, rag_index),
        ),
        "ctgb_toelating": BoundTool(
            name="ctgb_toelating",
            description="Controleer of een gewasbeschermingsmiddel is toegelaten (geeft altijd een "
                         "compliance-waarschuwing terug -- deze tool verzint nooit een toelatingsstatus).",
            arg_hint="de naam van het middel",
            fn=_ctgb_toelating,
        ),
    }
    # The teler's own logbook: LOCAL-ONLY, opt-in via ORCHARD_LOGBOOK_RAG=1 (never set on the public pod).
    from pipeline.orchard_logbook_rag import load_logbook_index, logbook_enabled
    if logbook_enabled():
        from pipeline.orchard_logbook_calendar import calendar_facts
        logbook_index = load_logbook_index(getattr(rag_index, "embedder", None), getattr(rag_index, "query_prefix", ""))
        if logbook_index is not None:
            catalog["logboek_zoeken"] = BoundTool(
                name="logboek_zoeken",
                description="Doorzoek het EIGEN logboek van de teler (wat is wanneer gespoten of gestrooid, met weer "
                             "erbij; 2013-heden). Gebruik dit voor elke vraag over wat de teler zelf eerder deed. "
                             "Citeer alleen wat er staat; de transcripties zijn nog niet allemaal geverifieerd.",
                arg_hint="een korte zoekvraag met jaar/maand/datum en/of middel, bijv. 'Syllit 2019' of 'mei 2014'",
                fn=lambda arg: _logboek_zoeken(arg, logbook_index),
            )
            catalog["middel_opzoeken"] = BoundTool(
                name="middel_opzoeken",
                description="Zoek een middel op merknaam op: toelatingsstatus en gebruiksvoorschrift voor kers uit de Ctgb-databank (de dosering "
                             "verschijnt als kaart onder je antwoord, noem hem zelf niet) PLUS wat de teler er zelf mee deed volgens het eigen "
                             "logboek (hoe vaak, wanneer, doel) en waar dat afwijkt van het voorschrift. Gebruik dit voor 'welk middel heb ik/wat "
                             "moet ik met X', ook als vervolg op logboek_kalender.",
                arg_hint="de merknaam, bijv. 'Syllit'",
                fn=_middel_opzoeken,
            )
            catalog["logboek_kalender"] = BoundTool(
                name="logboek_kalender",
                description="Wat deed de teler zelf rond deze tijd van het jaar? Telt uit het eigen logboek (2013-heden) per middel in "
                             "hoeveel jaren het in dit venster voorkwam, het gebruikelijke interval en het doel, en wat dit jaar nog "
                             "ontbreekt. Gebruik dit voor 'wat moet ik nu/deze maand doen volgens mijn eigen historie'. Geeft nooit "
                             "hoeveelheden of toelatingsstatus.",
                arg_hint="optioneel: een maandnaam ('november') of datum (JJJJ-MM-DD); leeg = vandaag",
                fn=lambda arg: ToolResult(facts=calendar_facts(arg), sources=["Eigen logboek 2013-heden (kalenderoverzicht, niet geverifieerd)"]),
            )
    if snapshot is not None:
        catalog.update({
            "weer_vooruitzicht": BoundTool(
                name="weer_vooruitzicht",
                description="Haal de weersvooruitzicht voor de komende 7 dagen op (temperatuur, neerslag).",
                arg_hint=None, fn=lambda _a: _weer_vooruitzicht(_a, snapshot),
            ),
            "weer_geschiedenis": BoundTool(
                name="weer_geschiedenis",
                description="Haal het weer van de afgelopen N dagen op (totale neerslag, gem. temperatuur).",
                arg_hint="aantal dagen terug (geheel getal, standaard 30)",
                fn=lambda a: _weer_geschiedenis(a, ctx, snapshot),
            ),
            "koude_uren": BoundTool(
                name="koude_uren",
                description="Hoeveel koude-uren (chill hours) zijn er dit seizoen opgebouwd voor het huidige ras?",
                arg_hint=None, fn=lambda _a: _koude_uren(_a, ctx, snapshot),
            ),
            "vorst_risico": BoundTool(
                name="vorst_risico",
                description="Is er nachtvorstrisico voor de huidige fenologische fase in de komende 7 dagen?",
                arg_hint=None, fn=lambda _a: _vorst_risico(_a, ctx, snapshot),
            ),
            "suzuki_risico": BoundTool(
                name="suzuki_risico",
                description="Wat is het huidige risico op suzuki-fruitvlieg (Drosophila suzukii)?",
                arg_hint=None, fn=lambda _a: _suzuki_risico(_a, snapshot),
            ),
            "vruchtbarsten_risico": BoundTool(
                name="vruchtbarsten_risico",
                description="Wat is het risico op vruchtbarsten door regen rond de oogst?",
                arg_hint=None, fn=lambda _a: _vruchtbarsten_risico(_a, ctx, snapshot),
            ),
            "waterbalans": BoundTool(
                name="waterbalans",
                description="Is het te droog of te nat? Geeft de waterbalans (neerslag min gewasverdamping, bodemvocht, "
                             "neerslagtekort) van de afgelopen dagen en de verwachting voor de komende 7 dagen. "
                             "Gebruik dit voor vragen over droogte, beregenen of te veel regen.",
                arg_hint=None, fn=lambda _a: _waterbalans(_a, ctx),
            ),
        })
    return catalog
