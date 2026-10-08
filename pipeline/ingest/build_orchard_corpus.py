"""Raw acquisition of the Cherry Orchard Advisor's Track 1 corpus (design doc Sec C.1-C.7).

Direct mirror of Auto Pilot's `pipeline/ingest/build_chief_engineer_corpus.py` posture:
this script ONLY downloads/saves real, provenance-tracked source documents into
``Data/Orchard/OrchardKnowledge/<category>/`` -- no parsing, chunking, translation, or RAG
indexing happens here (that is Phase 3, a separate script, so a later re-run of THIS
script never silently changes chunk IDs downstream). Every entry in ``SOURCES`` is a real,
individually-verified URL (fetched once by hand during this session to confirm it
actually resolves) -- never a guessed/plausible-looking link. Entries with
``status="blocked"`` are honestly documented dead ends (same discipline as Chief
Engineer's §7 table noting DNV/ABS as "CONFIRMED GATED, not pursued further") rather than
silently omitted.

Output: one file per acquired source under ``Data/Orchard/OrchardKnowledge/<category>/``,
plus ``Data/Orchard/OrchardKnowledge/manifest.json`` (one row per SOURCES entry, acquired
or not) for full provenance tracking -- required before anything in this corpus can ever
be cited in an answer (design doc Sec B.11: every advice must show a real citation).

Safe to run LOCALLY (pure stdlib: urllib, json, hashlib -- no GPU/API key needed).
Idempotent: skips re-downloading a file that already exists on disk.

Usage::

    .venv\\Scripts\\python.exe -m pipeline.ingest.build_orchard_corpus
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from core.paths import AgentPaths  # noqa: E402

# A real browser User-Agent is required for WUR's edepot.wur.nl (confirmed 2026-10-08:
# bare urllib/PowerShell HEAD requests get a 403, but a normal browser UA + GET succeeds) --
# mirrors Chief Engineer's own "maritime.org needs a Referer header" finding (design
# doc §7): different site, same lesson -- try a realistic header set before giving up.
_BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
_TIMEOUT_S = 60


@dataclass(frozen=True)
class SourceSpec:
    id: str
    title: str
    category: str  # subfolder under OrchardKnowledge/
    url: str | None  # None for status="blocked" entries (no working URL found)
    filename: str | None  # None for status="blocked" entries
    language: str  # "nl" | "en"
    status: str  # "to_fetch" | "blocked"
    note: str = ""


# ── Bronnenregister -- elke URL hieronder is deze sessie (2026-10-08) handmatig geverifieerd ──
SOURCES: list[SourceSpec] = [
    SourceSpec(
        id="wur_teelthandleidingen_139993",
        title="Teelthandleidingen (WUR edepot)",
        category="wur_groenkennisnet",
        url="https://edepot.wur.nl/139993",
        filename="wur_teelthandleidingen_139993.pdf",
        language="nl", status="to_fetch",
        note="Algemene WUR-teelthandleiding; gevonden via Groen Kennisnet-verwijzing. "
             "Vereist browser User-Agent (bare request -> 403).",
    ),
    SourceSpec(
        id="wur_onderstammenproef_kers_297528",
        title="2005-14 onderstammenproef zoete kers 610044.30 (WUR edepot)",
        category="wur_groenkennisnet",
        url="https://edepot.wur.nl/297528",
        filename="wur_onderstammenproef_zoete_kers_297528.pdf",
        language="nl", status="to_fetch",
        note="Direct kersenteelt-specifiek: internationale onderstammenproef zoete kers "
             "(groei, productie, vruchtgrootte, barstgevoeligheid). Vereist browser User-Agent.",
    ),
    SourceSpec(
        id="usda_handbook_442_sweet_cherries",
        title="Sweet Cherries: Production, Marketing, and Processing (USDA Agriculture Handbook No. 442, 1973)",
        category="usda_historisch",
        url="https://www.govinfo.gov/content/pkg/GOVPUB-A-PURL-gpo25996/pdf/GOVPUB-A-PURL-gpo25996.pdf",
        filename="usda_agriculture_handbook_442_sweet_cherries_1973.pdf",
        language="en", status="to_fetch",
        note="Real USDA-publicatie (GovInfo, public domain). Vervangt o.a. de oudere "
             "Farmers' Bulletin 776 'Growing Cherries East of the Rocky Mountains' -- "
             "een werkende digitale kopie van FB 776 zelf (pre-1930) is deze sessie niet "
             "gevonden, zie het 'blocked'-record hieronder.",
    ),
    SourceSpec(
        id="usda_farmers_bulletin_776_cherries",
        title="Farmers' Bulletin 776 -- Growing Cherries East of the Rocky Mountains (pre-1930, historisch)",
        category="usda_historisch", url=None, filename=None,
        language="en", status="blocked",
        note="GECONTROLEERD 2026-10-08: geen werkende directe downloadlink gevonden op "
             "archive.org/HathiTrust/UNT Digital Library in deze sessie (FB-nummer-zoekacties "
             "leverden alleen andere bulletins op, bv. FB1399=Blackberry Growing). "
             "Niet verder geforceerd ('don't brute-force a blocked approach'); USDA Agriculture "
             "Handbook 442 hierboven dekt dezelfde stof met recentere, wel bereikbare bron.",
    ),
    SourceSpec(
        id="eu_reg_2018_848_organic_nl",
        title="Verordening (EU) 2018/848 inzake de biologische productie (NL, EUR-Lex)",
        category="eu_wetgeving",
        url="https://eur-lex.europa.eu/legal-content/NL/TXT/?uri=CELEX:32018R0848",
        filename="eu_verordening_2018_848_biologische_productie_nl.html",
        language="nl", status="to_fetch",
        note="GECORRIGEERD 2026-10-08 (Fase 3): bij parsen bleek dit bestand ondanks de /NL/-URL "
             "toch Engelstalig te zijn (<title> zegt 'EN'). Hernieuwde pogingen (met /HTML/, /PDF/ "
             "en Accept-Language: nl) kregen herhaaldelijk 202 Accepted/lege body van EUR-Lex terug "
             "(waarschijnlijk tijdelijke rate-limiting) -- niet verder geforceerd. Dit bestand blijft "
             "op schijf staan maar is expliciet uitgesloten van de RAG-index "
             "(pipeline/ingest/parse_orchard_documents.py SKIP_FROM_RAG) totdat een echte NL-versie "
             "bevestigd is; zie ontwerp Deel F punt 8.",
    ),
    SourceSpec(
        id="ctgb_bulk_export",
        title="Ctgb bulk-export bestrijdingsmiddelendatabank (Excel)",
        category="ctgb", url=None, filename=None,
        language="nl", status="blocked",
        note="GECONTROLEERD 2026-10-08: de veelgeciteerde URL "
             "ctgb.blob.core.windows.net/documents/public-authorisations-report.xls "
             "resolvet niet meer (DNS-fout, bevestigd vanaf zowel lokale machine als los "
             "fetch-mechanisme) -- kennelijk verouderd/verplaatst. toelatingen.ctgb.nl zelf "
             "weigert scripted toegang (403, waarschijnlijk JS-vereiste SPA). Blijft een "
             "open gat; pipeline.orchard_tools.check_ctgb_toelating() blijft daarom een "
             "expliciete NotImplementedError-stub (nooit een verzonnen toelatingsstatus).",
    ),
    SourceSpec(
        id="actua_steenfruit_archief",
        title="Actua Steenfruit-archief (StonefruitConsult, oudere nummers)",
        category="actua_steenfruit", url=None, filename=None,
        language="nl", status="blocked",
        note="GECONTROLEERD 2026-10-08: het volledige archief is alleen toegankelijk voor "
             "CAF/StonefruitConsult-abonnees (inlogmuur) -- niet publiek scrapebaar. De 2 "
             "nummers die de teler al zelf heeft (#6, #7 2026) blijven de enige bron; "
             "zie Data/Data Log Books/Actua steenfruit #6 en #7 2026.pdf (niet gedupliceerd "
             "hierheen, blijft op de originele plek).",
    ),
    # -- Fase 2 vervolgronde (2026-10-08, tweede sessie) --------------------------------
    SourceSpec(
        id="netafim_kersen_buiten_adviesrapport_2021",
        title="Kersen (Buiten) Adviesrapport 2021 (Netafim)",
        category="teelt_advies",
        url="https://www.netafim.nl/contentassets/fd77f39c3a734ab8abf584a59a31390b/kersen-buiten-adviesrapport-2021.pdf",
        filename="netafim_kersen_buiten_adviesrapport_2021.pdf",
        language="nl", status="to_fetch",
        note="Commercieel irrigatie/fertigatie-adviesrapport specifiek voor buitenteelt "
             "zoete kers (NL) -- onderdoorberegening tegen nachtvorst, bemestingsschema's. "
             "Bron is een leverancier (Netafim), geen onafhankelijk onderzoeksinstituut -- "
             "bij gebruik in antwoorden expliciet als zodanig citeren, niet als WUR/Ctgb-"
             "niveau autoriteit behandelen.",
    ),
    SourceSpec(
        id="biofruitnet_zoete_kers_onderstammen",
        title="Zoete kers: eigenschappen van onderstammen (BIOFRUITNET, Horizon 2020)",
        category="wur_groenkennisnet",
        url="https://biofruitnet.eu/wp-content/uploads/2023/04/80.PA_Zoete_kers_Eigenschappen_van_onderstammen_NL.pdf",
        filename="biofruitnet_zoete_kers_onderstammen_nl.pdf",
        language="nl", status="to_fetch",
        note="EU Horizon 2020-project BIOFRUITNET (biologische fruitteelt kennisuitwisseling) -- "
             "Nederlandstalige factsheet over onderstam-eigenschappen voor zoete kers, "
             "aanvullend op de WUR-onderstammenproef hierboven.",
    ),
    SourceSpec(
        id="osu_em9267_spotted_wing_drosophila",
        title="Spotted Wing Drosophila Pest Alert (EM 9267, Oregon State University Extension)",
        category="suzukii_swd",
        url="https://extension.oregonstate.edu/sites/default/files/documents/em9267.pdf",
        filename="osu_em9267_spotted_wing_drosophila.pdf",
        language="en", status="to_fetch",
        note="Amerikaanse university-extension-publicatie specifiek over Drosophila suzukii "
             "(herkenning, monitoring, beheersing) -- gebruikt om "
             "pipeline/orchard_phenology_spec.py's suzukii-risicofunctie van een echte, "
             "citeerbare bron te voorzien i.p.v. 'illustrative placeholder'. Een directe "
             "Nederlandstalige WUR-factsheet over hetzelfde onderwerp (Helsen & Heijerman, "
             "PPO Factsheet 31) kon deze sessie NIET geverifieerd worden -- een door "
             "websearch gesuggereerd edepot.wur.nl/281922 bleek bij download een compleet "
             "ander (tuinbouw-statistiek) document te zijn, dus niet gebruikt (zelfde les "
             "als de eerdere FB1399-misser: nooit een gesuggereerde ID vertrouwen zonder "
             "de gedownloade inhoud te verifiëren).",
    ),
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def build_corpus(knowledge_dir: Path) -> list[dict]:
    """Downloads every ``status="to_fetch"`` source not already on disk, and returns the
    full manifest (acquired + blocked entries) ready to be written to ``manifest.json``."""
    manifest: list[dict] = []
    for src in SOURCES:
        row = {
            "id": src.id, "title": src.title, "category": src.category, "url": src.url,
            "language": src.language, "note": src.note,
        }
        if src.status == "blocked":
            row["status"] = "blocked"
            manifest.append(row)
            print(f"[blocked] {src.id}: {src.note}")
            continue

        dest = knowledge_dir / src.category / src.filename
        if dest.exists():
            row.update({"status": "already_acquired", "file_path": str(dest), "sha256": _sha256(dest)})
            manifest.append(row)
            print(f"[skip, already on disk] {src.id} -> {dest}")
            continue

        try:
            _fetch(src.url, dest)
            row.update({
                "status": "acquired", "file_path": str(dest), "sha256": _sha256(dest),
                "size_bytes": dest.stat().st_size,
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            })
            print(f"[acquired] {src.id} -> {dest} ({dest.stat().st_size} bytes)")
        except Exception as exc:
            row.update({"status": "failed", "error": str(exc)})
            print(f"[FAILED] {src.id}: {exc}")
        manifest.append(row)
    return manifest


def main() -> None:
    paths = AgentPaths.orchard()
    knowledge_dir = paths.source_dir  # Data/Orchard/OrchardKnowledge/
    manifest = build_corpus(knowledge_dir)
    manifest_path = knowledge_dir / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    n_acquired = sum(1 for m in manifest if m["status"] in ("acquired", "already_acquired"))
    n_blocked = sum(1 for m in manifest if m["status"] == "blocked")
    n_failed = sum(1 for m in manifest if m["status"] == "failed")
    print(f"\nManifest geschreven: {manifest_path}")
    print(f"  acquired/already_acquired: {n_acquired}  blocked: {n_blocked}  failed: {n_failed}")


if __name__ == "__main__":
    main()
