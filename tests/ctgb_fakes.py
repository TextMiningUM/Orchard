"""Fake Ctgb MST public API for tests: same JSON shapes as the real answers (checked against Syllit/Movento/Signum on 2026-10-10), no network."""
from __future__ import annotations

import urllib.parse

CHERRY_TREE = [{"group": "Fruitgewassen", "complete": False, "eppo": [], "items": [
    {"group": "Kers", "complete": True, "eppo": [], "items": [
        {"crop": "Zoete kers", "selected": True, "eppo": ["PRNAV"]}, {"crop": "Zure kers", "selected": True, "eppo": ["PRNCE"]}]}]}]
FRUIT_TREE = [{"group": "Vruchtbomen en -struiken", "complete": True, "eppo": [], "items": [
    {"crop": "Appel", "selected": True, "eppo": ["MABSD"]}, {"crop": "Kers", "selected": True, "eppo": ["PRNAV"]}]}]
NURSERY_TREE = [{"group": "Boomkwekerijgewassen", "complete": True, "eppo": [], "items": [
    {"crop": "Appel", "selected": True, "eppo": ["MABSD"]}, {"crop": "Kers", "selected": True, "eppo": ["PRNAV"]}]}]
CRESS_TREE = [{"crop": "Tuinkers", "selected": True, "eppo": ["LEPSA"]}]
ORGANISMS = [{"group": "Schimmels", "selected": False, "items": [{"organismScientific": "Blumeriella jaapii", "diseases": ["Kersenbladvlekkenziekte"],
                                                                     "eppo": "BLUMJA", "selected": True}]}]


def use(name="WG 3", summary="Kers", crops=None, dose=1.25, unit="L/ha", per_season=2.0, per_use=None, interval=60, phi=14, months=(3, 9),
        bbch=("71", "97"), remarks="Na de bloei toepassen.", restrictions=None) -> dict:
    amount = {}
    if per_season is not None:
        amount["perCropSeason"] = per_season
    if per_use is not None:
        amount["perUse"] = per_use
    out = {"nameOfUse": {"name": name, "usesSummary": summary}, "targetCrops": crops if crops is not None else CHERRY_TREE, "targetOrganisms": ORGANISMS,
           "targetLocations": [{"id": 2, "description": "Onbedekt"}], "applicationMethods": [{"id": 1, "description": "Gewasbehandeling"}],
           "amountOfApplications": amount, "maximumProductDose": {"ratio": dose, "measure": {"id": 2, "unit": unit}},
           "minorUse": {"description": "Nee", "type": "Nee"}, "remarks": remarks, "restrictions": restrictions or []}
    if interval is not None:
        out["minimumIntervalBetweenApplications"] = interval
    if phi is not None:
        out["phiDays"] = phi
    if months:
        out["applicationTiming"] = {"fromMonth": months[0], "toMonth": months[1]}
    if bbch:
        out["growthStage"] = {"from": bbch[0], "to": bbch[1]}
    return out


def detail(pid: str, name: str, uses: list[dict], reg: int = 16287, manual: bool = True) -> dict:
    wcode = {"authorisationStartDate": "2025-04-01T22:00:00Z", "expirationDate": "2029-06-29T22:00:00Z"}
    if manual:
        wcode["instructionOfUse"] = {"document": {"link": f"https://docs.example/{pid}_PW1.pdf", "documentName": "PW1.pdf"}}
    return {"data": {
        "id": pid, "name": name, "uses": uses, "categoryType": {"description": "Gewas", "type": "PPP"},
        "authorisationHolder": {"companyName": "Voorbeeld BV"}, "formulationType": None,
        "compositions": {"substances": [{"substance": {"name": "dodine"}, "function": {"isActiveSubstance": True}, "concentration": 544,
                                         "concentrationUnit": {"unit": "G/L", "description": "gram per liter"}}],
                         "formulationType": {"description": "Suspensie concentraat"}},
        "components": [{"labelling": [{"signalWord": {"description": "Gevaar"}}]}],
        "authorisation": {"actual": [{"wCodings": [wcode]}], "registrationNumber": {"nl": reg}},
        "decisions": [{"document": {"link": f"https://docs.example/{pid}_BESL.pdf"}}]}}


def standard_api() -> "FakeApi":
    """Syllit 544 SC (valid, cherry use: max 2 per season, interval 60, May-September) + an expired old product."""
    syllit = detail("1", "Syllit 544 SC", [use(months=(5, 9))])
    old = detail("2", "SYLLIT OUD", [use("WG 1", "Kers", dose=1.5, per_season=3.0, interval=21, phi=7)], reg=99)
    return FakeApi([("1", "Syllit 544 SC", "2029-06-29T22:00:00.000Z", syllit), ("2", "SYLLIT OUD", "2024-04-29T22:00:00.000Z", old)])


def log_entries(extra_filler: bool = True) -> list:
    """Logbook 2016-2019: Syllit on 2 April, 5 and 12 May and 20 August (4 per year), plus filler lines so each year counts as a logbook year."""
    from pipeline.orchard_patterns import LogEntry
    out, n = [], 0
    for y in range(2016, 2020):
        rows = [(f"{y}-05-05", [("Syllit", "1 ltr")], "Tegen bladvlekkenziekte."), (f"{y}-05-12", [("Syllit", "1 ltr")], "Tegen bladvlekkenziekte."),
                (f"{y}-08-20", [("Syllit", "1 ltr")], "Tegen bladvalziekte."), (f"{y}-04-02", [("Syllit", "1 ltr")], "")]
        if extra_filler:
            rows += [(f"{y}-06-{d:02d}", [("Ureum", "1 kg")], "") for d in range(1, 8)]
        for iso, apps, rem in rows:
            n += 1
            out.append(LogEntry(id=n, jaar=str(y), datum_iso=iso, opmerkingen=rem, toepassingen=apps))
    return out


class FakeApi:
    """``items``: list of (id, name, expirationDate ISO, detail payload). Counts the HTTP calls it receives in ``calls``."""

    def __init__(self, items: list[tuple[str, str, str, dict]]) -> None:
        self.items = items
        self.calls: list[str] = []

    def fetch(self, url: str) -> dict:
        self.calls.append(url)
        parsed = urllib.parse.urlparse(url)
        if parsed.path.endswith("/authorisations"):
            needle = urllib.parse.parse_qs(parsed.query).get("filter[productName]", [""])[0].lower()
            data = [{"id": i, "name": n, "registrationNumber": "1", "expirationDate": exp, "categoryType": {"type": "PPP"}}
                    for i, n, exp, _ in self.items if needle in n.lower()]
            return {"meta": {"total": len(data)}, "data": data}
        pid = parsed.path.rsplit("/", 1)[1]
        for i, _n, _e, payload in self.items:
            if i == pid:
                return payload
        raise KeyError(pid)
