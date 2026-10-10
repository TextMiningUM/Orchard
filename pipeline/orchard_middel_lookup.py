"""Middel opzoeken: het officiele Ctgb-voorschrift voor kers + wat de teler zelf met dit middel deed (eigen logboek) + een controle van de eigen praktijk
tegen de Ctgb-limieten (ontwerp G.31). Eén functie, ``middel_opzoeken``, voor de pagina "Gebruik van Middelen" en de adviseur-tool ``middel_opzoeken``.

Twee uitvoerkanalen, bewust gescheiden (deterministische kern eerst, ontwerp B.1/B.11):
  * ``card``  -- voor de mens: de volledige Ctgb-kaart (letterlijke getallen) + het eigen gebruik. Wordt door de app getoond, niet door het model geschreven.
  * ``facts`` -- voor het taalmodel: status, eigen gebruik in tellingen en de praktijkwaarschuwingen, maar GEEN doseringen of limieten.

De praktijkcontrole vergelijkt alleen met de meest RUIMHARTIGE limiet van de geldige kers-voorschriften (anders beschuldigen we ten onrechte) en formuleert
voorzichtig: één logboekregel kan een deelbehandeling zijn en de voorschriften waren in eerdere jaren mogelijk anders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pipeline.orchard_ctgb import (CtgbClient, CtgbLookup, CtgbUnavailable, CtgbUse, MONTHS_NL, format_card, format_model_facts, lookup, nl_date)
from pipeline.orchard_logbook_calendar import ProductHistory, product_history
from pipeline.orchard_middelen import CATEGORY_LABELS
from pipeline.orchard_patterns import LogEntry

PRACTICE_CAVEAT = ("Eén logboekregel kan een deelbehandeling of een ander perceel zijn en de voorschriften kunnen in eerdere jaren anders zijn geweest; "
                   "controleer het zelf voordat je hier conclusies aan verbindt.")


@dataclass(frozen=True)
class PracticeFlag:
    kind: str     # "aantal" | "interval" | "periode"
    text: str     # met de Ctgb-getallen: alleen voor de kaart die de gebruiker ziet
    model: str    # zonder limieten: dit mag het taalmodel zien


@dataclass
class MiddelAdvies:
    query: str
    ref: date
    lookup: CtgbLookup | None = None
    ctgb_error: str | None = None
    history: ProductHistory | None = None
    flags: list[PracticeFlag] = field(default_factory=list)

    @property
    def compare_note(self) -> str:
        """Waarom er (nog) niet vergeleken is met het voorschrift, als er wel eigen gebruik is."""
        if not self.history or self.flags:
            return ""
        if self.lookup is None:
            return "De eigen praktijk is niet vergeleken met het voorschrift: de Ctgb-databank was niet bereikbaar."
        if not self.lookup.valid_cherry_uses:
            return ("De eigen praktijk is niet vergeleken met het voorschrift: er is nu geen geldig kers-voorschrift voor dit middel (de toelating is verlopen "
                    "of het middel is niet voor kers toegelaten).")
        return "Eigen praktijk tegenover het Ctgb-voorschrift (aantal, interval, periode): geen afwijking gevonden in het logboek."


def _month_window(u: CtgbUse) -> set[int] | None:
    if not u.month_from or not u.month_to:
        return None
    a, b = u.month_from, u.month_to
    return set(range(a, b + 1)) if a <= b else set(range(a, 13)) | set(range(1, b + 1))


def practice_flags(h: ProductHistory, uses: list[CtgbUse]) -> list[PracticeFlag]:
    """Waar wijkt het eigen gebruik af van de ruimhartigste limiet van de geldige kers-voorschriften? Leeg = niets gevonden (of niets te vergelijken)."""
    if not uses:
        return []
    flags: list[PracticeFlag] = []
    seasons = [u.per_season for u in uses]
    if all(s is not None for s in seasons):
        cap = max(seasons)
        over = [(y, c) for y, c in h.per_year if c > cap]
        if over:
            flags.append(PracticeFlag(
                "aantal", f"In {len(over)} van {len(h.per_year)} jaren staan meer toepassingen in je logboek dan het voorschrift toestaat (maximaal {cap:g} "
                          f"per teeltseizoen): " + ", ".join(f"{y}: {c}×" for y, c in over) + ".",
                f"In {len(over)} van {len(h.per_year)} jaren staan meer toepassingen in het logboek dan het Ctgb-voorschrift per teeltseizoen toestaat."))
    intervals = [u.min_interval_days for u in uses]
    if all(i for i in intervals):
        floor = min(intervals)
        short = [h.dates[i + 1] for i in range(len(h.dates) - 1)
                 if 0 < (h.dates[i + 1] - h.dates[i]).days < floor and h.dates[i + 1].year == h.dates[i].year]
        if short:
            flags.append(PracticeFlag(
                "interval", f"{len(short)}× lag er minder dan {floor} dagen tussen twee toepassingen in hetzelfde jaar (bijv. op {nl_date(short[0])}).",
                f"{len(short)}× lag er minder tijd tussen twee toepassingen dan het voorschrift toestaat."))
    windows = [_month_window(u) for u in uses]
    if all(w is not None for w in windows):
        allowed = set().union(*windows)
        outside = [d for d in h.dates if d.month not in allowed]
        if outside:
            names = ", ".join(sorted({MONTHS_NL[d.month - 1] for d in outside}))
            flags.append(PracticeFlag(
                "periode", f"{len(outside)} toepassing(en) buiten de toegestane maanden (bijv. {nl_date(outside[0])}; toegestaan zijn "
                           f"{MONTHS_NL[min(allowed) - 1]} t/m {MONTHS_NL[max(allowed) - 1]}; je logboek noemt {names}).",
                f"{len(outside)} toepassing(en) lagen buiten de periode die het voorschrift toestaat."))
    return flags


def build_advies(entries: list[LogEntry] | None, query: str, today: date, lk: CtgbLookup | None, error: str | None) -> MiddelAdvies:
    """Combineert een (eventueel gecachete) Ctgb-lookup met het eigen gebruik uit het logboek en de praktijkcontrole."""
    advies = MiddelAdvies(query=query.strip(), ref=today, lookup=lk, ctgb_error=error)
    if entries:
        advies.history = product_history(entries, advies.query, today)
    if advies.history and lk and lk.valid_cherry_uses:
        advies.flags = practice_flags(advies.history, lk.valid_cherry_uses)
    return advies


def middel_opzoeken(entries: list[LogEntry] | None, query: str, *, client: CtgbClient | None = None, today: date | None = None) -> MiddelAdvies:
    today = today or date.today()
    try:
        return build_advies(entries, query, today, lookup(query.strip(), client, today), None)
    except CtgbUnavailable as exc:
        return build_advies(entries, query, today, None, str(exc))


def _history_lines(h: ProductHistory, ref: date) -> list[str]:
    years = ", ".join(f"{y}: {c}×" for y, c in h.per_year)
    months = ", ".join(f"{MONTHS_NL[m - 1]} ({c}×)" for m, c in sorted(h.months, key=lambda t: -t[1])[:4])
    lines = [f"{h.applications} toepassingen in je logboek ({', '.join(h.names[:4])}; {CATEGORY_LABELS.get(h.category, h.category)}), voor het eerst "
             f"{nl_date(h.first)}, laatst {nl_date(h.last)}.",
             f"Per jaar: {years}.", f"Vooral in: {months}."]
    if h.gaps_days:
        gaps = sorted(h.gaps_days)
        lines.append(f"Binnen een jaar meestal om de ~{gaps[len(gaps) // 2]} dagen.")
    if h.purposes:
        lines.append("Doel volgens je opmerkingen: " + ", ".join(f"{p} ({n} jaar)" for p, n in h.purposes) + ".")
    if h.covered_years:
        lines.append(f"Rond deze tijd van het jaar ({ref.day}-{ref.month}, ±15 dagen) paste je het toe in {h.near_ref_years} van de {h.covered_years} jaren met logboek.")
    return lines


def format_facts(a: MiddelAdvies) -> str:
    """Voor het taalmodel: status + eigen gebruik in tellingen; geen doseringen/limieten."""
    parts = [format_model_facts(a.lookup)] if a.lookup else [
        f"COMPLIANCE-GUARDRAIL: de Ctgb-databank is nu niet te bereiken ({a.ctgb_error}); doe geen uitspraak over toelating of dosering voor '{a.query}'."]
    if a.history:
        parts.append("Eigen logboek: " + " ".join(_history_lines(a.history, a.ref)))
        if a.flags:
            parts.append("Let op, eigen praktijk tegenover het Ctgb-voorschrift: " + " ".join(f.model for f in a.flags) + " Details staan op de kaart. " + PRACTICE_CAVEAT)
        elif a.compare_note:
            parts.append(a.compare_note)
    else:
        parts.append(f"Eigen logboek: geen toepassingen van '{a.query}' gevonden (of het logboek is niet beschikbaar).")
    parts.append("Zeg wat de teler volgens het logboek meestal deed; noem geen doseringen; verwijs voor dosering en regels naar de kaart en het etiket.")
    return "\n".join(parts)


def format_full_card(a: MiddelAdvies) -> str:
    """Voor de mens: Ctgb-kaart (letterlijk) + eigen gebruik + praktijkcontrole."""
    out = [format_card(a.lookup)] if a.lookup else [f"**De Ctgb-databank is nu niet te bereiken** ({a.ctgb_error}). Probeer het later opnieuw of kijk op ctgb.nl."]
    if a.history:
        out += ["", f"### Je eigen gebruik van '{a.query}' (uit je logboek)", *[f"- {line}" for line in _history_lines(a.history, a.ref)]]
        if a.flags:
            out += ["", "**Let op: eigen praktijk tegenover het Ctgb-voorschrift**", *[f"- {f.text}" for f in a.flags], f"*{PRACTICE_CAVEAT}*"]
        elif a.compare_note:
            out += ["", f"*{a.compare_note}*"]
    return "\n".join(out)
