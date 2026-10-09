"""Concept lexicon for the Orchard knowledge graph (``build_orchard_kg.py``) and hybrid retrieval.

Same idea as Auto Pilot's ``_VHF_ALIASES``: a query phrase -- in the grower's own words, Dutch or English or the
Latin name -- is normalised to a CANONICAL concept; chunks are tagged with the same concepts, so a question about
"hagelschot" also reaches text that only says "Stigmina carpophila" or "shot hole", and "bronskleurig blad met webjes"
reaches the spider-mite text although the words "spintmijt" never occur in the question. Dense retrieval alone
misses those vocabulary gaps.

Deterministic and auditable: every concept is listed here with its aliases and category -- no model decides what a
concept is. The lexicon is built from domain knowledge (Dutch cherry cultivation vocabulary), not tuned on the gold
evaluation set; coverage statistics are printed by ``build_orchard_kg.py`` so gaps are visible, and a new alias is a
one-line change.

Matching: accent-folded lowercase. An alias of >= 5 letters matches at a WORD START (so ``vorstschade``,
``bladluizen`` and ``beregeningsinstallatie`` are found by ``vorst*`` / ``bladluis*`` / ``beregening*``); shorter
aliases must be a whole word (optionally with an ``s`` / ``en`` plural) so ``kers`` does not match ``kersenvlieg``.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache


def fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", folded.lower()).strip()


# canonical concept -> (category, aliases). Canonical ids are lowercase, accent-free, Dutch-first.
CONCEPTS: dict[str, tuple[str, list[str]]] = {
    # ── ziekten ────────────────────────────────────────────────────────────────────────
    "hagelschot": ("ziekte", ["hagelschot", "hagelschotziekte", "shot hole", "shothole", "stigmina", "wilsonomyces",
                              "coryneum", "schotgaten"]),
    "bacteriekanker": ("ziekte", ["bacteriekanker", "bacterial canker", "pseudomonas", "gomvloei", "gummosis",
                                  "bacterieziekte", "kankerplekken"]),
    "monilia": ("ziekte", ["monilia", "monilinia", "vruchtrot", "bruinrot", "brown rot", "bloesemsterfte",
                           "takjesziekte", "tak- en bloesemsterfte", "blossom blight", "vruchtmummies", "mummies",
                           "gemummificeerde"]),
    "bladvlekkenziekte": ("ziekte", ["bladvlekkenziekte", "bladvlekken", "blumeriella", "jaapii", "leaf spot",
                                     "coccomyces", "vroegtijdige bladval"]),
    "meeldauw": ("ziekte", ["meeldauw", "powdery mildew", "podosphaera", "witte aanslag"]),
    "loodglans": ("ziekte", ["loodglans", "silver leaf", "chondrostereum", "zilverglans"]),
    "wortelrot": ("ziekte", ["phytophthora", "wortelrot", "kraagrot", "root rot", "crown rot", "natte voeten",
                             "wortelverstikking"]),
    "verticillium": ("ziekte", ["verticillium", "verwelkingsziekte", "verwelken"]),
    "kroongal": ("ziekte", ["kroongal", "crown gall", "agrobacterium", "rhizobium"]),
    "virus": ("ziekte", ["virus", "virussen", "pnrsv", "little cherry", "kleine kers", "necrotic ringspot"]),
    "cytospora": ("ziekte", ["cytospora", "valsa", "tak sterft af"]),
    "botrytis": ("ziekte", ["botrytis", "grauwe schimmel", "grey mould", "gray mold"]),
    "rhizopus": ("ziekte", ["rhizopus", "zachtrot", "soft rot"]),
    # ── plagen ─────────────────────────────────────────────────────────────────────────
    "kersenvlieg": ("plaag", ["kersenvlieg", "rhagoletis", "cherry fruit fly", "kersenmade", "maden in de kers",
                              "madige kersen", "made in de kers"]),
    "suzukii": ("plaag", ["suzukii", "spotted wing", "swd", "kersenetsfruitvlieg", "kirschessigfliege",
                          "drosophila", "aziatische fruitvlieg", "fruitvlieg"]),
    "kersenluis": ("plaag", ["kersenluis", "zwarte kersenluis", "bladluis", "bladluizen", "myzus", "aphid",
                             "aphids", "luizen", "gekrulde bladeren", "honingdauw"]),
    "spint": ("plaag", ["spintmijt", "spint", "fruitspintmijt", "rode spin", "spider mite", "mijten", "tetranychus",
                        "panonychus", "bronskleurig", "bronzing", "webjes", "fijne webben", "spinsel"]),
    "slakkenwesp": ("plaag", ["slakkenwesp", "caliroa", "cherry slug", "pearslug", "slakachtige larven"]),
    "rupsen": ("plaag", ["wintervlinder", "bladroller", "bladrollers", "fruitmot", "rupsen", "rups", "caterpillar",
                         "cherry fruitworm", "bladvreters"]),
    "schorskever": ("plaag", ["schorskever", "scolytus", "shothole borer", "boorgaatjes", "boorders"]),
    "trips": ("plaag", ["trips", "thrips"]),
    "vogels": ("plaag", ["vogelschade", "vogels", "spreeuwen", "spreeuw", "merels", "merel", "vogelnet", "netten",
                         "vogelnetten", "birds", "bird damage", "vogelverschrikker", "pikken"]),
    "wild": ("plaag", ["konijnen", "konijn", "hazen", "reeen", "wildschade", "muizen", "woelmuizen", "veldmuizen",
                       "schade door wild"]),
    # ── klimaat / fysiologie ────────────────────────────────────────────────────────────
    "vorst": ("klimaat", ["vorst", "nachtvorst", "bloesemvorst", "vorstschade", "vorstberegening", "vorstgat",
                          "vorstnacht", "frost", "frostschade", "windmachine", "windmachines", "wind machine",
                          "bevriest", "bevroren", "koudeluchtmeer", "koude lucht"]),
    "scheuren": ("fysiologie", ["scheuren", "barsten", "gebarsten", "gescheurde", "scheurtjes", "rain cracking",
                                "cracking", "splitting", "fruit cracking", "regenkap", "regenkappen", "overkapping",
                                "afdekking", "rain cover", "regenschade", "uiteenspringen"]),
    "koude_uren": ("fenologie", ["koude-uren", "koude uren", "chill", "chilling", "winterrust", "dormancy", "rustperiode",
                                 "chill hours", "chill units"]),
    "bloei": ("fenologie", ["bloei", "bloesem", "bloeiperiode", "volle bloei", "blossom", "flowering", "bloeitijd",
                            "knopzwelling", "witte knop", "bud break", "bloeiknop", "bloemknop", "bloemknoppen"]),
    "bestuiving": ("teelt", ["bestuiving", "bestuiver", "bestuivers", "bestuivingslijst", "pollination", "pollinizer",
                             "pollinators", "bijen", "hommels", "bijenkast", "zelfvruchtbaar", "zelfsteriel",
                             "self-fertile", "self-incompatible", "incompatibiliteit", "befruchter", "befruchtingsras",
                             "pollenbron", "kruisbestuiving"]),
    "vruchtzetting": ("fysiologie", ["vruchtzetting", "fruit set", "vruchtval", "vruchtjes vallen af", "junival",
                                     "dubbele vruchten", "dubbele kersen", "doubles", "pitloos", "kleine vruchten",
                                     "vruchtgrootte", "fruit size", "fruitgrootte"]),
    "zonnebrand": ("fysiologie", ["zonnebrand", "sunscald", "sunburn", "hitteschade", "verbranding", "heat stress"]),
    "droogte": ("klimaat", ["droogte", "droog", "waterstress", "drought", "watertekort", "verdroging"]),
    "wind": ("klimaat", ["windbescherming", "windschade", "windscherm", "haag", "windhaag", "storm", "windbreak"]),
    "hagel": ("klimaat", ["hagelnet", "hagelschade", "hagelbui", "hail"]),
    "regen": ("klimaat", ["regen", "regenval", "neerslag", "nat weer", "natte periode", "bladnat", "bladnatperiode",
                          "rain", "rainfall", "wetness", "vochtig weer"]),
    "temperatuur": ("klimaat", ["temperatuur", "warm weer", "koud weer", "hitte", "temperature"]),
    # ── teelt / bodem / water ──────────────────────────────────────────────────────────
    "irrigatie": ("teelt", ["irrigatie", "beregening", "druppelirrigatie", "druppelslang", "druppelaar", "watergift",
                            "beregeningsinstallatie", "drip", "irrigation", "watergeven", "fertigatie", "gieten"]),
    "bodem": ("bodem", ["bodem", "grond", "grondsoort", "klei", "zand", "leem", "ploegzool", "verdichting",
                        "bodemverdichting", "drainage", "waterhuishouding", "soil", "grondwater", "grondwaterstand",
                        "bodemleven", "organische stof", "compost", "ph-waarde", "zuurgraad"]),
    "bemesting": ("bemesting", ["bemesting", "bemesten", "mest", "mestregels", "mestwetgeving", "meststoffen",
                                "stikstof", "nitrogen", "kalium", "potassium", "calcium", "magnesium", "boor", "boron",
                                "fosfaat", "bladvoeding", "ureum", "kalkgift", "kalk", "fertilizer", "fertilization",
                                "mineralen", "fosfor", "gebruiksnormen", "mestplaatsingsruimte", "voedingstoestand",
                                "bladanalyse", "grondanalyse", "bladbemesting"]),
    "snoei": ("teelt", ["snoei", "snoeien", "snoeihout", "pruning", "opbouwsnoei", "zomersnoei", "wintersnoei",
                        "onderhoudssnoei", "kappen", "inkorten", "uitdunnen", "training", "leiden", "boomvorm",
                        "spindel", "kandelaar", "y-systeem", "ufo", "steunconstructie", "palen", "dragers",
                        "leivorm", "leisysteem", "kroonopbouw", "snoeiwonden", "wondverzorging"]),
    "onkruid": ("teelt", ["onkruid", "onkruidbestrijding", "bodembedekking", "grasstrook", "boomstrook", "strook",
                          "mulch", "mulchen", "weed", "groenbemester", "gazon", "rijpad", "rijpaden", "maaien"]),
    "aanplant": ("teelt", ["aanplant", "plantafstand", "plantdichtheid", "plantmateriaal", "nursery",
                           "boomkwekerij", "plantgoed", "planting", "standplaats", "helling", "ligging",
                           "herplant", "nieuwe aanplant", "boomgaardlocatie"]),
    "dunning": ("teelt", ["dunnen", "dunning", "vruchtdunning", "thinning", "behang", "yield", "alternantie",
                          "overbehang"]),
    "oogst": ("oogst", ["oogst", "plukken", "pluk", "harvest", "rijpheid", "maturity", "brix", "stevigheid", "plukrijp",
                        "steellengte", "steeltjes", "sortering", "koeling", "koelen", "hydrocooling",
                        "houdbaarheid", "shelf life", "plukkers", "plukperiode", "vroeg plukken", "lang plukken",
                        "verpakking", "kisten"]),
    "verkoop": ("bedrijf", ["verkoop", "afzet", "klanten", "markt", "prijs", "prijzen", "directe verkoop",
                            "boerderijwinkel", "zelfpluk", "rendement", "kosten", "kostprijs", "marge", "arbeid",
                            "personeel", "veiling", "supermarkt", "export", "afnemers", "retail"]),
    "biologisch": ("bedrijf", ["biologisch", "biologische", "organic", "skal", "2018/848", "bio-teelt", "duurzaam",
                               "natuurlijke vijanden", "nuttigen", "geintegreerd", "ipm", "biodiversiteit",
                               "bloemrijke stroken", "randen"]),
    # ── regelgeving / gewasbescherming ─────────────────────────────────────────────────
    "spuitregistratie": ("regelgeving", ["spuitregistratie", "registratie", "noteren", "bijhouden", "spuitboek",
                                         "logboek", "administratie", "registreren", "bespuitingsregistratie",
                                         "spuitschrift", "vastleggen", "documenteren", "spuitdatum", "dosering",
                                         "etiket", "wachttijd", "gebruiksvoorschrift", "bijhouden van"]),
    "gewasbescherming": ("regelgeving", ["gewasbescherming", "gewasbeschermingsmiddel", "gewasbeschermingsmiddelen",
                                         "bespuiting", "bespuitingen", "spuiten", "spuitschema", "middel", "middelen",
                                         "ctgb", "toelating", "toegelaten", "fungicide", "insecticide", "pesticide",
                                         "pesticiden", "herbicide", "residu", "mrl", "bufferzone", "driftreductie",
                                         "spuitlicentie", "spuitcertificaat", "toepassing", "spray", "sprays",
                                         "bestrijding", "bestrijden", "resistentie", "werkzame stof", "koper",
                                         "zwavel", "sulfur", "copper", "bacillus", "spinosad", "kaolien",
                                         "plantversterker", "natuurlijke middelen", "curatief", "preventief"]),
    # ── onderstammen / rassen ──────────────────────────────────────────────────────────
    "onderstam": ("onderstam", ["onderstam", "onderstammen", "rootstock", "rootstocks", "tussenstam", "interstem",
                                "wortelstok", "stamvorm"]),
    "gisela": ("onderstam", ["gisela", "gisela 5", "gisela 6", "gisela 3", "gi 5", "gi 6"]),
    "colt": ("onderstam", ["colt"]),
    "weiroot": ("onderstam", ["weiroot", "weiroot 158", "weiroot 53", "weiroot 13"]),
    "mazzard": ("onderstam", ["mazzard", "f12/1", "f 12/1", "prunus avium"]),
    "mahaleb": ("onderstam", ["mahaleb", "prunus mahaleb", "sint luciakers", "st lucie"]),
    "edabriz": ("onderstam", ["edabriz", "damil", "piku", "krymsk", "tabel edabriz", "maxma", "colt wortelstok"]),
    "regina": ("ras", ["regina"]),
    "kordia": ("ras", ["kordia", "attika"]),
    "sweetheart": ("ras", ["sweetheart"]),
    "lapins": ("ras", ["lapins"]),
    "burlat": ("ras", ["burlat", "early burlat"]),
    "summit": ("ras", ["summit"]),
    "sunburst": ("ras", ["sunburst"]),
    "hedelfinger": ("ras", ["hedelfinger", "hedelfingen"]),
    "bing": ("ras", ["bing", "black tartarian", "tartarian"]),
    "napoleon": ("ras", ["napoleon", "royal ann"]),
    "lambert": ("ras", ["lambert", "rainier", "stella", "chinook", "windsor", "republican"]),
    "boskriek": ("ras", ["boskriek", "limburgse boskriek", "boskers"]),
    "morello": ("ras", ["morello", "zure kers", "morellen", "sour cherry", "prunus cerasus"]),
    "ras_algemeen": ("ras", ["ras", "rassen", "cultivar", "cultivars", "variety", "varieties", "rassenkeuze",
                             "rassenlijst", "karina", "samba", "sylvia", "vanda", "skeena", "merchant", "techlovan",
                             "lapins", "benton", "tamara", "satin", "sandra", "areko", "kasandra", "grace star"]),
    # ── fenologie ──────────────────────────────────────────────────────────────────────
    "graaddagen": ("fenologie", ["graaddagen", "gdd", "growing degree", "degree days", "temperatuursom",
                                 "warmtesom", "bbch", "fenologie", "fenologisch", "stadium", "groeistadium",
                                 "ontwikkelingsstadium"]),
    "bladval": ("fenologie", ["bladval", "leaf fall"]),
}


def _compile(alias: str) -> re.Pattern:
    a = re.escape(fold(alias))
    a = a.replace(r"\ ", r"\s+").replace(r"\-", r"[-\s]?")
    if len(fold(alias)) >= 5:
        return re.compile(rf"(?<![a-z0-9]){a}")
    return re.compile(rf"(?<![a-z0-9]){a}(?:s|en)?(?![a-z0-9])")


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[str, re.Pattern]]:
    out = []
    for concept, (_cat, aliases) in CONCEPTS.items():
        for alias in aliases:
            out.append((concept, _compile(alias)))
    return out


def concept_category(concept: str) -> str:
    return CONCEPTS[concept][0]


def tag_text(text: str) -> dict[str, int]:
    """``{concept: number of alias matches}`` for ``text`` (accent-folded, lowercase)."""
    folded = fold(text)
    counts: dict[str, int] = {}
    for concept, pattern in _patterns():
        n = len(pattern.findall(folded))
        if n:
            counts[concept] = counts.get(concept, 0) + n
    return counts


def aliases_for_kg() -> dict[str, list[str]]:
    """alias phrase (folded) -> [concept]: what the KG stores for query-time normalisation."""
    out: dict[str, list[str]] = {}
    for concept, (_cat, aliases) in CONCEPTS.items():
        for alias in aliases:
            out.setdefault(fold(alias), [])
            if concept not in out[fold(alias)]:
                out[fold(alias)].append(concept)
    return out
