"""Quality control for the structured Orchard JSON -- the gate between the document -> JSON stage and
the RAG / KG / PG builders.

It automates the project rule "read a sample of the parsed text and confirm it makes sense"
(copilot-instructions: PDF text extraction can silently interleave columns) with signals a model
cannot talk its way around. Every chunk gets ``chunk["qc"] = {"verdict", "reasons", "scores"}``:

- ``ok``     -- indexed.
- ``warn``   -- indexed, listed in the report for a human glance (mild OCR noise, open-ended edge).
- ``fail``   -- NOT indexed (quarantined, kept in the JSON): not running prose (table / figure /
  caption residue), interleaved columns / garbled text, or heavy OCR noise.
- ``references`` -- bibliography / literature lists: real text, but not knowledge to retrieve.

A human can overrule a verdict with ``Data/Orchard/orchard_qc_overrides.json``
(``{"chunk_id": "ok"|"fail"}``) -- keyed by chunk_id, which is a hash of the text, so an approval
silently expires when the text changes.

Signals (all deterministic except the optional language-model stage):

1. *Sentence structure*: share of words that sit in complete sentences (capital start, terminal
   punctuation, >= 4 words, mostly letters). Tables, figure labels and spec sidebars are not
   sentences -- exactly the "niet volledige zinnen" failure.
2. *Tabular / numeric density*, short-line fragments, duplicated lines.
3. *Lexical noise*: share of unprotected out-of-vocabulary words (spellchecker dictionary + domain
   terms + anything that repeats in the corpus + names/Latin binomials) and impossible characters
   (``n`` with tilde inside an English word) -- the OCR-noise signature.
4. *Bibliography score*: years, journal abbreviations ("Agr.", "Proc."), volume:page patterns.
5. *Language-model surprisal* (``--lm``): per-sentence next-token loss under a small Dutch / English
   GPT-2; a sentence whose loss is a robust outlier versus the rest of the corpus (median/MAD, never
   a fixed constant) is where two columns or a table fragment were glued together.

Usage::

    .venv\\Scripts\\python.exe -m pipeline.ingest.orchard_qc              # structural + lexical
    .venv\\Scripts\\python.exe -m pipeline.ingest.orchard_qc --lm         # + language-model stage
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.paths import AgentPaths  # noqa: E402
from core.text_segmentation import split_sentences  # noqa: E402
from pipeline.ingest.orchard_structure import chunk_flags, tabular_score, word_count  # noqa: E402

_WORD_RE = re.compile(r"[^\W\d_]{3,}")
_ALLOWED_ACCENTS = {"nl": set("\u00e9\u00e8\u00eb\u00ef\u00f3\u00f6\u00fc\u00ea\u00f4\u00e2\u00e7\u00e0\u00ed\u00e1"), "en": set()}
_STOPWORDS = {
    "nl": {"de", "het", "een", "en", "van", "in", "is", "dat", "op", "te", "met", "voor", "niet", "zijn", "als", "bij", "om", "ook"},
    "en": {"the", "of", "and", "to", "in", "is", "that", "for", "with", "as", "on", "are", "by", "this", "be", "from", "or"},
}
_REF_YEAR_RE = re.compile(r"\b(?:18|19|20)\d{2}\b")
_REF_ABBR_RE = re.compile(r"\b[A-Z][a-z]{1,5}\.")
_REF_VOLPAGE_RE = re.compile(r"\b\d{1,3}\s*[:(]\s*\d")
_REF_TITLE_RE = re.compile(r"literature cited|literatuur|references|referenties|bibliograph|bronnen en|verder lezen|"
                           r"further readings?|about the authors", re.I)
_LIST_MARKER_RE = re.compile(r"(?m)^\s*(?:[-\u2022*]|\d{1,2}[.)])\s+")

# Thresholds: calibrated on the real corpus (design doc G.20), kept few and explicit.
MIN_WORDS_FOR_SENTENCE_CHECK = 25
SENTENCE_RATIO_FAIL = 0.35
TABULAR_FAIL = 0.45
OOV_FAIL = 0.12
OOV_WARN = 0.06
REFERENCE_FAIL = 0.12
OUTLIER_Z = 4.0


# ── lexicon ─────────────────────────────────────────────────────────────────────────────

def build_protected_terms(docs: list[dict], min_count: int = 3) -> set[str]:
    """Words that look unknown to a general dictionary but are legitimate here: anything that
    repeats across the corpus (OCR errors are rare and varied, domain terms repeat) plus tokens
    that are capitalised mid-sentence (names, Latin binomials)."""
    counts: Counter[str] = Counter()
    capitalised: set[str] = set()
    for doc in docs:
        for chunk in doc["chunks"]:
            for sentence in split_sentences(chunk["text"]):
                tokens = _WORD_RE.findall(sentence)
                capitalised.update(t.lower() for t in tokens[1:] if t[0].isupper())
            counts.update(w.lower() for w in _WORD_RE.findall(chunk["text"]))
    return {w for w, c in counts.items() if c >= min_count} | capitalised


# ── structural + lexical signals ────────────────────────────────────────────────────────

_MD_HEADING_LINE_RE = re.compile(r"(?m)^\s*\*\*[^*\n]+\*\*\s*$")
_ABBREVIATIONS = {
    "spp", "vs", "al", "ca", "bv", "nr", "no", "fig", "figs", "tab", "table", "tables", "dr", "prof", "ir", "inc",
    "ltd", "st", "etc", "enz", "resp", "incl", "excl", "dept", "proc", "agr", "hort", "sci", "soc", "bul", "amer",
    "vol", "pp", "cf", "sp", "var", "subsp", "syn", "approx", "max", "min", "gem", "evt", "sec", "pl", "sq",
}
_TERMINALS = (".", "!", "?", ":", ";", "\u2026")
_REFERENCE_TAIL_RE = re.compile(r"\d+(?:[\s,;]+[A-Za-z0-9]{1,2})*\)+\.?")


def qc_sentences(text: str) -> list[str]:
    """Sentence splitter for the completeness check. Plain ``[.!?]\\s`` splitting cuts after
    abbreviations, initials, units and figure references ("Monilinia spp. kunnen", "M. laxa",
    "et al.", "5 lb. per tree", "(fig. 3).", "(table 1, A)."), which would report perfectly good
    sentences as fragments, so those boundaries are re-joined. A lowercase start after a normal
    full stop is NOT re-joined: that is exactly what a chunk, page or column boundary cutting
    through a sentence looks like and has to be reported."""
    pieces = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    out: list[str] = []
    for piece in pieces:
        if piece[:1] in ";,)" and out:  # a fragment that starts with punctuation continues the sentence
            out[-1] = out[-1] + " " + piece
            continue
        if out:
            prev = out[-1]
            tok = prev.split()[-1].lstrip("([{\"'\u2018\u201c")
            last = tok[:-1] if re.fullmatch(r"[A-Za-z]+\.", tok) else ""  # the word that ends right before the full stop
            nxt = piece[:1]
            strong = last.lower() in _ABBREVIATIONS or (len(last) == 1 and last.isupper())
            weak = 0 < len(last) <= 3 and last.islower() and (nxt.islower() or nxt.isdigit())
            unmatched_open = sum(prev.count(c) for c in "([{") > sum(prev.count(c) for c in ")]}")
            if (prev.endswith(".") and (strong or weak)) or (prev.endswith(").") and nxt.islower()) \
                    or (unmatched_open and nxt.islower()) or (prev.endswith(("?", "!")) and nxt.islower()) \
                    or _REFERENCE_TAIL_RE.fullmatch(piece) \
                    or (re.fullmatch(r"\d+\.", prev.split()[-1]) and len(prev.split()) == 1):
                out[-1] = prev + " " + piece
                continue
        out.append(piece)
    return out


def _prose_view(text: str) -> str:
    """Text as the sentence checks should see it: markdown heading lines (``**1. Titel**``) are
    titles, not sentences; a list item of >= 4 words that starts with a capital counts as a complete
    statement even without a final full stop; list markers are not part of a sentence."""
    lines = []
    for line in _MD_HEADING_LINE_RE.sub("", text).split("\n"):
        if _LIST_MARKER_RE.match(line):
            body = _LIST_MARKER_RE.sub("", line).strip()
            if word_count(body) >= 4 and body[:1].isupper() and not body.endswith(_TERMINALS):
                body += "."
            line = body
        lines.append(line)
    return re.sub(r"\n+", " \n ", "\n".join(lines))


def sentence_ratio(text: str) -> float:
    """Share of words inside complete sentences. List markers are ignored, so a bullet list of
    full sentences counts as prose while a table / label grid does not."""
    total = word_count(_MD_HEADING_LINE_RE.sub("", text))
    if not total:
        return 0.0
    good = 0
    for sent in qc_sentences(_prose_view(text)):
        s = sent.strip()
        n = word_count(s)
        letters = sum(c.isalpha() for c in s)
        starts_ok = s[:1].isupper() or s[:1].isdigit()
        ends_ok = s.rstrip("\"')\u201d")[-1:] in (".", "!", "?", ":", ";")
        if n >= 4 and starts_ok and ends_ok and letters / max(1, len(s)) >= 0.7:
            good += n
    return good / total


def fragment_ratio(text: str) -> float:
    """Share of lines that are short non-sentences (<4 words, no terminal punctuation): table
    cells, axis labels, figure legends."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return 0.0
    frag = sum(1 for l in lines if word_count(l) < 4 and not l.endswith((".", "!", "?", ":", ";"))
               and not _LIST_MARKER_RE.match(l))
    return frag / len(lines)


def reference_score(text: str) -> float:
    n = max(1, word_count(text))
    return (len(_REF_YEAR_RE.findall(text)) + len(_REF_ABBR_RE.findall(text))
            + len(_REF_VOLPAGE_RE.findall(text))) / n


def _compound_known(word: str, dic, depth: int = 2) -> bool:
    """Dutch (and German-style) compounds are productive: "bladmonsters", "kaliumgehalten" are
    not in any dictionary, but they split into known words (with an optional linking s/e/en)."""
    if depth == 0:
        return False
    for i in range(3, len(word) - 2):
        left, right = word[:i], word[i:]
        left_ok = left in dic or any(left.endswith(link) and left[:-len(link)] in dic for link in ("s", "e", "en"))
        if left_ok and (right in dic or _compound_known(right, dic, depth - 1)):
            return True
    return False


def lexical_noise(text: str, language: str, spell, protected: set[str]) -> tuple[float, list[str]]:
    """(share of unprotected out-of-vocabulary words, the offending words). Impossible characters
    for the language always count as noise; a word that splits into known words (Dutch compound)
    is not out-of-vocabulary."""
    allowed = _ALLOWED_ACCENTS.get(language, set())
    tokens = _WORD_RE.findall(text)
    if not tokens:
        return 0.0, []
    candidates, bad = [], []
    for tok in tokens:
        if tok[0].isupper() or tok.isupper():  # names, binomials, headings
            continue
        low = tok.lower()
        if any(ord(c) > 127 and c not in allowed for c in low):
            bad.append(tok)
        else:
            candidates.append(low)
    unknown = {w for w in spell.unknown(candidates) if w not in protected}
    if language == "nl":
        dic = spell.word_frequency.dictionary
        unknown = {w for w in unknown if not _compound_known(w, dic)}
    offenders = [w for w in candidates if w in unknown] + bad
    return len(offenders) / len(tokens), sorted(set(offenders))[:12]


def stopword_ratio(text: str, language: str) -> float:
    """Best stop-word share over the declared language and English (an English abstract inside a
    Dutch report is fine; text that is neither is not running prose)."""
    words = [w.lower() for w in _WORD_RE.findall(text)]
    if not words:
        return 0.0
    return max(sum(1 for w in words if w in _STOPWORDS.get(lang, ())) / len(words) for lang in {language, "en"})


# ── sentence completeness (the strict rule: only complete sentences in a chunk) ─────────

_HYPHEN_BREAK_RE = re.compile(r"[a-z\u00e0-\u00ff]- [a-z\u00e0-\u00ff]+")
_HYPHEN_OK_NEXT = {"en", "of", "tot", "and", "or", "en/of"}


def sentence_issues(text: str) -> dict:
    """Which sentences are not complete: no terminal punctuation, or starting mid-sentence
    (lowercase), or a stray fragment (< 3 words). ``first``/``last`` tell whether the damage sits
    at the chunk edge (a chunk / page / column boundary cut through a sentence)."""
    sentences = [s.strip() for s in qc_sentences(_prose_view(text)) if s.strip()]
    bad: list[str] = []
    flags = []
    for s in sentences:
        starts_ok = s[0].isupper() or s[0].isdigit() or s[0] in "\"'\u201c\u2018("
        ends_ok = s.rstrip("\"')\u201d\u2019")[-1:] in (".", "!", "?", ":", ";", "\u2026")
        ok = starts_ok and ends_ok and word_count(s) >= 3
        flags.append(ok)
        if not ok:
            bad.append(s)
    return {
        "n_sentences": len(sentences), "n_incomplete": len(bad),
        "first_incomplete": bool(flags) and not flags[0], "last_incomplete": bool(flags) and not flags[-1],
        "examples": [b[:80] for b in bad[:3]],
    }


def hyphen_artifacts(text: str) -> list[str]:
    """Line-wrap hyphens that survived joining ("regen- kappen"); a deliberate ellipsis compound
    ("onder- en bovengronds") is not one."""
    out = []
    for m in _HYPHEN_BREAK_RE.finditer(text):
        nxt = m.group(0).split("- ", 1)[1]
        if nxt not in _HYPHEN_OK_NEXT:
            out.append(m.group(0))
    return out[:5]


def repeated_page_residue(chunks: list[dict], min_chunks: int = 4, shingle: int = 6) -> set[str]:
    """Word 6-grams that recur verbatim in >= 4 DIFFERENT chunks of one document AND mostly sit at
    the start of a paragraph: running headers or footers that leaked into the text. A domain phrase
    that merely recurs inside sentences ("Limburgse Boskriek met tussenstam Gisela 5") is not
    residue. (Cards of the same template are skipped by the caller.)"""
    seen: dict[str, set[int]] = {}
    at_start: Counter[str] = Counter()
    occurrences: Counter[str] = Counter()
    for idx, c in enumerate(chunks):
        for unit in c["text"].split("\n\n"):
            words = unit.split()
            for i in range(len(words) - shingle + 1):
                gram = " ".join(words[i:i + shingle]).lower()
                seen.setdefault(gram, set()).add(idx)
                occurrences[gram] += 1
                at_start[gram] += i == 0
    return {g for g, idxs in seen.items()
            if len(idxs) >= min_chunks and at_start[g] / occurrences[g] >= 0.5}


def chunk_signals(chunk: dict, language: str, spell, protected: set[str], residue: set[str] | None = None) -> dict:
    text = chunk["text"]
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    oov, offenders = lexical_noise(text, language, spell, protected)
    issues = sentence_issues(text)
    low = text.lower()
    return {
        "words": word_count(text),
        "sentence_ratio": round(sentence_ratio(text), 3),
        "fragment_ratio": round(fragment_ratio(text), 3),
        "tabular_score": round(tabular_score(text), 3),
        "digit_ratio": round(sum(c.isdigit() for c in text) / max(1, len(text)), 3),
        "reference_score": round(reference_score(text), 3),
        "oov_ratio": round(oov, 3),
        "oov_words": offenders,
        "stopword_ratio": round(stopword_ratio(text, language), 3),
        "duplicate_lines": len(lines) - len(set(lines)),
        "caps_ratio": round(sum(c.isupper() for c in text) / max(1, sum(c.isalpha() for c in text)), 3),
        "incomplete_sentences": issues["n_incomplete"],
        "incomplete_examples": issues["examples"],
        "first_sentence_incomplete": issues["first_incomplete"],
        "last_sentence_incomplete": issues["last_incomplete"],
        "hyphen_artifacts": hyphen_artifacts(text),
        "page_residue": bool(residue) and any(g in low for g in residue),
    }


# ── verdict ─────────────────────────────────────────────────────────────────────────────

ISSUE_LABELS = {
    "ocr": "OCR-ruis", "table": "tabel/cijferdata/figuurtekst", "incomplete": "onvolledige zinnen",
    "page_break": "pagina-/kolom-/chunkgrens door een zin", "columns": "door elkaar lopende kolommen",
    "language": "geen lopende tekst", "references": "bibliografie", "chrome": "website-navigatie/reclame",
}
_CHROME_TITLE_RE = re.compile(r"^(nieuws|reacties?|disqus|gerelateerd\w*|volg ons|nieuwsbrief|contact|"
                              r"uitgever|colofon|over deze praktijksamenvatting|permalink|projectnaam)\b", re.I)


def decide(chunk: dict, s: dict, lm: dict | None = None) -> tuple[str, list[str], list[str]]:
    """(verdict, reasons, issue categories). References first (real text we choose not to index),
    then hard failures, then warnings.

    The strict rule of this project is that a chunk holds ONLY complete sentences: any sentence
    without a capital start / terminal punctuation, or a chunk that begins or ends mid-sentence
    (a page, column or chunk boundary cut through it), is a failure, not a warning."""
    title = " ".join([chunk.get("title", ""), *chunk.get("heading_path", [])])
    if _REF_TITLE_RE.search(title) or (s["words"] >= 25 and s["reference_score"] >= REFERENCE_FAIL) \
            or (s["words"] >= 8 and s["caps_ratio"] >= 0.45 and s["reference_score"] >= 0.05):
        return "references", [f"bibliografie (reference_score={s['reference_score']})"], ["references"]
    if _CHROME_TITLE_RE.match(chunk.get("title", "")):
        return "fail", [f"website-/colofon-sectie ({chunk.get('title', '')[:40]!r})"], ["chrome"]
    standalone = chunk.get("type") in ("probleem",)
    fail: list[tuple[str, str]] = []
    if s["words"] >= MIN_WORDS_FOR_SENTENCE_CHECK and not standalone and s["sentence_ratio"] < SENTENCE_RATIO_FAIL:
        fail.append(("table", f"geen lopende zinnen (sentence_ratio={s['sentence_ratio']})"))
    if s["words"] >= 12 and s["tabular_score"] >= TABULAR_FAIL:
        fail.append(("table", f"tabel/cijferdata (tabular_score={s['tabular_score']})"))
    if s["oov_ratio"] >= OOV_FAIL:
        fail.append(("ocr", f"zware OCR-ruis (oov_ratio={s['oov_ratio']}: {', '.join(s['oov_words'][:5])})"))
    if s["stopword_ratio"] < 0.03 and s["words"] >= 50 and not standalone:
        fail.append(("language", f"geen lopende taal (stopword_ratio={s['stopword_ratio']})"))
    if lm and lm["outliers"] >= 2 and lm["outlier_share"] >= 0.25:
        fail.append(("columns", f"waarschijnlijk door elkaar lopende kolommen ({lm['outliers']} zinnen met "
                                f"afwijkende LM-loss, max z={lm['max_z']})"))
    if s["first_sentence_incomplete"]:
        fail.append(("page_break", "begint midden in een zin"))
    if s["last_sentence_incomplete"]:
        fail.append(("page_break", "eindigt zonder zinseinde"))
    inner = s["incomplete_sentences"] - int(s["first_sentence_incomplete"]) - int(s["last_sentence_incomplete"])
    if inner > 0:
        fail.append(("incomplete", f"{inner} onvolledige zin(nen) midden in de chunk: {s['incomplete_examples'][:2]}"))
    if s["words"] < 8 and not standalone:
        fail.append(("incomplete", f"te weinig tekst ({s['words']} woorden)"))
    if s["page_residue"]:
        fail.append(("page_break", "herhaalde kop-/voettekst van de pagina in de chunk"))
    if fail:
        categories: list[str] = []
        for category, _ in fail:
            if category not in categories:
                categories.append(category)
        return "fail", [message for _, message in fail], categories
    reasons: list[str] = []
    cats: list[str] = []
    if s["oov_ratio"] >= OOV_WARN:
        reasons.append(f"OCR-ruis (oov_ratio={s['oov_ratio']}: {', '.join(s['oov_words'][:5])})")
        cats.append("ocr")
    if s["hyphen_artifacts"]:
        reasons.append(f"afbreekstreepje van regelafbreking over: {s['hyphen_artifacts'][:2]}")
        cats.append("page_break")
    if s["fragment_ratio"] >= 0.3 and s["words"] >= 20:
        reasons.append(f"veel korte fragmenten (fragment_ratio={s['fragment_ratio']})")
        cats.append("table")
    if s["duplicate_lines"]:
        reasons.append(f"{s['duplicate_lines']} dubbele regel(s)")
    if lm and lm["outliers"] >= 1:
        reasons.append(f"{lm['outliers']} zin(nen) met afwijkende LM-loss (z={lm['max_z']}): {lm['worst'][:90]!r}")
        cats.append("columns")
    return ("warn" if reasons else "ok"), reasons, cats


# ── language-model stage ────────────────────────────────────────────────────────────────

_LM_BY_LANGUAGE = {"nl": "GroNLP/gpt2-small-dutch", "en": "distilgpt2"}


class SentenceScorer:
    """Mean next-token loss (nats/token) per sentence, one small causal LM per language."""

    def __init__(self) -> None:
        self._models: dict[str, tuple] = {}

    def _get(self, language: str):
        name = _LM_BY_LANGUAGE.get(language, _LM_BY_LANGUAGE["en"])
        if name not in self._models:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            tok = AutoTokenizer.from_pretrained(name)
            if tok.pad_token is None:
                tok.pad_token = tok.eos_token
            self._models[name] = (tok, AutoModelForCausalLM.from_pretrained(name).eval(), torch)
        return self._models[name]

    def score(self, sentences: list[str], language: str, batch: int = 16) -> list[float]:
        tok, model, torch = self._get(language)
        out: list[float] = []
        for i in range(0, len(sentences), batch):
            enc = tok(sentences[i:i + batch], return_tensors="pt", padding=True, truncation=True, max_length=96)
            with torch.no_grad():
                logits = model(**enc).logits[:, :-1]
            labels, mask = enc["input_ids"][:, 1:], enc["attention_mask"][:, 1:]
            nll = torch.nn.functional.cross_entropy(logits.transpose(1, 2), labels, reduction="none")
            out.extend(float((nll[j] * mask[j]).sum() / mask[j].sum().clamp(min=1)) for j in range(len(labels)))
        return out


def lm_stage(docs: list[dict], scorer=None) -> dict[str, dict]:
    """chunk_id -> {"outliers", "outlier_share", "max_z", "worst"}. Outlier = sentence loss far
    above the corpus median FOR THAT LANGUAGE (robust z via MAD), so the cut-off adapts to how
    predictable this corpus' prose is instead of being a magic constant."""
    scorer = scorer or SentenceScorer()
    per_lang: dict[str, list[tuple[str, str, float]]] = {}
    for doc in docs:
        sentences = [(c["chunk_id"], s) for c in doc["chunks"] for s in split_sentences(c["text"])
                     if word_count(s) >= 8 and sum(ch.isalpha() for ch in s) / max(1, len(s)) >= 0.6]
        if not sentences:
            continue
        losses = scorer.score([s for _, s in sentences], doc["language"])
        per_lang.setdefault(doc["language"], []).extend((cid, s, l) for (cid, s), l in zip(sentences, losses))
    result: dict[str, dict] = {}
    for items in per_lang.values():
        med = statistics.median(l for _, _, l in items)
        mad = statistics.median(abs(l - med) for _, _, l in items) or 1e-6
        by_chunk: dict[str, list[tuple[float, str]]] = {}
        for cid, s, l in items:
            by_chunk.setdefault(cid, []).append(((l - med) / (1.4826 * mad), s))
        for cid, zs in by_chunk.items():
            outliers = [z for z, _ in zs if z > OUTLIER_Z]
            worst = max(zs, key=lambda t: t[0])
            result[cid] = {"outliers": len(outliers), "outlier_share": round(len(outliers) / len(zs), 3),
                           "max_z": round(worst[0], 1), "worst": worst[1]}
    return result


# ── driver ──────────────────────────────────────────────────────────────────────────────

def load_overrides(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


_JUNK_INSIDE_RE = re.compile(r"[A-Za-z]+[\^{}\[\]|\\_~<>#]+[A-Za-z]+|[a-z]\([a-z]")


def find_garbled_tokens(docs: list[dict], spell_by_lang: dict, protected: set[str],
                        include_misspellings: bool = False) -> dict[str, set[str]]:
    """Per language: tokens that are unambiguous OCR damage -- letters with a stray symbol inside
    ("developn^ent", "f(irtilized", "p.stils") and letters that cannot occur in the language
    ("ñeshed" in English). Used to DROP the sentence containing them, never to rewrite it.
    ``include_misspellings`` adds one-off dictionary-unknown words within edit distance 2 of a real
    word ("conditic", "siirays") -- OFF by default: in a horticultural handbook the same rule also
    hits correct technical terms (disked, rotovated, oblanceolate, Latin epithets)."""
    corpus: Counter[str] = Counter()
    for doc in docs:
        for chunk in doc["chunks"]:
            corpus.update(w.lower() for w in _WORD_RE.findall(chunk["text"]))
    garbled: dict[str, set[str]] = {}
    for doc in docs:
        lang = doc["language"]
        bad = garbled.setdefault(lang, set())
        allowed = _ALLOWED_ACCENTS.get(lang, set())
        spell = spell_by_lang[lang]
        for chunk in doc["chunks"]:
            text = chunk["text"]
            bad.update(m.group(0) for m in _JUNK_INSIDE_RE.finditer(text))
            for tok in set(_WORD_RE.findall(text)):
                low = tok.lower()
                if tok[0].isupper() or tok.isupper() or low in protected:
                    continue
                if any(ord(c) > 127 and c not in allowed for c in low):
                    bad.add(tok)
                elif (include_misspellings and lang == "en" and len(low) >= 5 and corpus[low] <= 1
                      and low not in spell and spell.candidates(low)):
                    bad.add(tok)
    return garbled


def _contains_token(sentence: str, token: str) -> bool:
    if not token.isalpha():  # junk pattern such as "developn^ent": plain substring
        return token in sentence
    return re.search(rf"(?<!\w){re.escape(token)}(?!\w)", sentence, re.I) is not None


def _is_complete_sentence(s: str) -> bool:
    starts_ok = s[:1].isupper() or s[:1].isdigit() or s[:1] in "\"'\u201c\u2018("
    ends_ok = s.rstrip("\"')\u201d\u2019")[-1:] in (".", "!", "?", ":", ";", "\u2026")
    return starts_ok and ends_ok and word_count(s) >= 3


SALVAGE_MAX_RATIO = 0.3  # a chunk that is mostly broken is not salvaged, it fails


def repair_chunk(chunk: dict, garbled: set[str] | None = None) -> list[str]:
    """Salvages a chunk by dropping what is not a complete sentence: a leading continuation that
    starts in lowercase, a trailing sentence that never ends, stray label fragments ("Terug",
    "Retired."), sentences with OCR damage (``garbled`` tokens) and -- as long as they are a
    minority (``SALVAGE_MAX_RATIO``) -- broken sentences in the middle (a caption that got glued
    into the paragraph). Nothing is ever rewritten or guessed: text is only dropped, the original
    stays in ``chunk["text_raw"]`` and the dropped pieces in ``chunk["repairs"]``. What remains
    consists of complete sentences only; a chunk that is mostly broken is left alone (and then
    fails QC)."""
    units = chunk["text"].split("\n\n")
    n_sentences = n_broken = 0
    for unit in units:
        for s in qc_sentences(_prose_view(unit)):
            n_sentences += 1
            n_broken += not _is_complete_sentence(s)
    salvage = n_sentences > 0 and n_broken / n_sentences <= SALVAGE_MAX_RATIO
    removed: list[str] = []
    kept_units: list[str] = []
    for ui, unit in enumerate(units):
        lines = [l for l in unit.split("\n") if l.strip()]
        if lines and all(_LIST_MARKER_RE.match(l) for l in lines):
            keep_lines = []
            for line in lines:
                marker = _LIST_MARKER_RE.match(line).group(0)
                body = _LIST_MARKER_RE.sub("", line).strip()
                pieces = qc_sentences(body)
                good = [p for p in pieces if word_count(p) >= 3 or p.rstrip().endswith(_TERMINALS) and word_count(p) >= 2]
                removed.extend(p for p in pieces if p not in good)
                if good and (word_count(" ".join(good)) >= 3 or " ".join(good).endswith(_TERMINALS)):
                    keep_lines.append(marker + " ".join(good))
                else:
                    removed.append(line.strip())
            if keep_lines:
                kept_units.append("\n".join(keep_lines))
            continue
        sentences = qc_sentences(unit)
        while ui == 0 and not kept_units and sentences and sentences[0][:1].islower():
            removed.append(sentences.pop(0))
        keep = []
        for s in sentences:
            core = _LIST_MARKER_RE.sub("", s).lstrip()  # a bullet marker is not part of the sentence
            if word_count(core) < 3 or (word_count(core) < 4 and not core.rstrip("\"')\u201d").endswith(_TERMINALS)):
                removed.append(s)  # stray label / footnote fragment ("Retired.", "Terug")
            elif garbled and any(_contains_token(s, g) for g in garbled):
                removed.append(s)  # OCR damage inside the sentence
            elif salvage and not _is_complete_sentence(core):
                removed.append(s)
            else:
                keep.append(s)
        if ui == len(units) - 1 and keep and not keep[-1].rstrip("\"')\u201d").endswith(_TERMINALS):
            removed.append(keep.pop())
        if keep:
            kept_units.append(" ".join(keep))
    if not removed:
        return []
    new_text = "\n\n".join(kept_units)
    chunk.setdefault("text_raw", chunk["text"])
    chunk["text_with_context"] = chunk.get("text_with_context", chunk["text"]).replace(chunk["text"], new_text)
    chunk["text"] = new_text
    chunk["word_count"] = word_count(new_text)
    chunk.update(chunk_flags(new_text))
    chunk["repairs"] = chunk.get("repairs", []) + removed
    return removed


def reset_repairs(chunk: dict) -> None:
    """Undo an earlier ``repair_chunk`` so that QC is idempotent: the repair always starts from the
    chunk text as the parser produced it."""
    raw = chunk.pop("text_raw", None)
    if raw is None:
        return
    chunk["text_with_context"] = chunk.get("text_with_context", chunk["text"]).replace(chunk["text"], raw)
    chunk["text"] = raw
    chunk["word_count"] = word_count(raw)
    chunk.update(chunk_flags(raw))
    chunk.pop("repairs", None)


def run_qc(docs: list[dict], use_lm: bool = False, overrides: dict[str, str] | None = None,
           scorer=None, repair: bool = False) -> dict:
    """Annotates every chunk of every doc with ``chunk["qc"]`` and returns a summary. With
    ``repair`` the edge fragments are dropped first (see ``repair_chunk``) -- used when building
    the index from the JSON, never when merely inspecting an existing index."""
    from spellchecker import SpellChecker
    overrides = overrides or {}
    n_repaired = 0
    if repair:
        for doc in docs:
            for chunk in doc["chunks"]:
                reset_repairs(chunk)
    spell = {lang: SpellChecker(language=lang) for lang in {d["language"] for d in docs}}
    protected = build_protected_terms(docs)
    if repair:
        garbled = find_garbled_tokens(docs, spell, protected)
        for doc in docs:
            for chunk in doc["chunks"]:
                if chunk.get("type") not in ("probleem",) and repair_chunk(chunk, garbled.get(doc["language"])):
                    n_repaired += 1
    lm = lm_stage(docs, scorer) if use_lm else {}
    counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    for doc in docs:
        prose = [c for c in doc["chunks"] if c.get("type") not in ("probleem",)]
        residue = repeated_page_residue(prose) if len(prose) >= 4 else set()
        for chunk in doc["chunks"]:
            signals = chunk_signals(chunk, doc["language"], spell[doc["language"]], protected, residue)
            verdict, reasons, issues = decide(chunk, signals, lm.get(chunk["chunk_id"]))
            if chunk["chunk_id"] in overrides:
                reasons.append(f"handmatig overruled ({verdict} -> {overrides[chunk['chunk_id']]})")
                verdict = overrides[chunk["chunk_id"]]
            chunk["qc"] = {"verdict": verdict, "reasons": reasons, "issues": issues, "scores": signals,
                           **({"lm": lm[chunk["chunk_id"]]} if chunk["chunk_id"] in lm else {})}
            counts[verdict] += 1
            issue_counts.update(issues)
    return {"counts": dict(counts), "issues": dict(issue_counts), "lm": use_lm,
            "n_chunks": sum(counts.values()), "n_docs": len(docs), "repaired": n_repaired}


def indexable(chunk: dict) -> bool:
    """The single rule every downstream builder (RAG, KG, PG) uses: a chunk without a QC record
    (older JSON) counts as indexable; ``fail`` and ``references`` never are."""
    return chunk.get("qc", {}).get("verdict", "ok") in ("ok", "warn")


def chunks_to_docs(chunks: list[dict]) -> list[dict]:
    """Groups a flat chunk list (the live RAG index) into the ``{"doc_id", "language", "chunks"}``
    shape ``run_qc`` expects, accepting both index layouts: the older one (``section_titles`` /
    ``types`` lists, per-chunk ``language``) and the structured-JSON one (``title`` /
    ``heading_path`` / ``type``). Chunks are copied; the index itself is never modified."""
    docs: dict[str, dict] = {}
    for i, c in enumerate(chunks):
        c = dict(c)
        titles = c.get("section_titles") or []
        c.setdefault("title", titles[0] if titles else c.get("title", ""))
        c.setdefault("heading_path", titles[:1])
        types = c.get("types") or []
        c["type"] = c.get("type") or (types[0] if types else "prose")
        c.setdefault("chunk_index", len(docs.get(c["doc_id"], {"chunks": []})["chunks"]))
        c.setdefault("pages", c.get("pages") or [c.get("page_num", 1)])
        doc = docs.setdefault(c["doc_id"], {"doc_id": c["doc_id"], "title": c.get("title", ""),
                                            "language": c.get("language", "nl"), "chunks": []})
        doc["chunks"].append(c)
    return list(docs.values())


def qc_rag_index(paths: AgentPaths | None = None, use_lm: bool = False, progress=None) -> dict | None:
    """QC over the chunks the advisor actually retrieves from (the live RAG index). Returns
    ``{"docs", "summary", "report"}`` or None when no index has been built yet."""
    paths = paths or AgentPaths.orchard()
    chunks_path = paths.cache_dir / "orchard_rag_chunks.json"
    if not chunks_path.exists():
        return None
    if progress:
        progress("Chunks laden ...")
    docs = chunks_to_docs(json.loads(chunks_path.read_text(encoding="utf-8")))
    if progress:
        progress("Controleren (zinnen, tabellen, OCR, pagina-grenzen)" + (" + taalmodel ..." if use_lm else " ..."))
    summary = run_qc(docs, use_lm=use_lm, overrides=load_overrides(paths.data_root / "orchard_qc_overrides.json"))
    report = format_report(docs, summary)
    try:
        (paths.cache_dir / "orchard_rag_qc_report.md").write_text(report, encoding="utf-8")
    except OSError:
        pass  # read-only deployment: the report is still returned to the caller
    return {"docs": docs, "summary": summary, "report": report}


def per_document_table(docs: list[dict]) -> list[dict]:
    rows = []
    for d in docs:
        verdicts = Counter(c["qc"]["verdict"] for c in d["chunks"])
        issues = Counter(i for c in d["chunks"] for i in c["qc"].get("issues", []))
        rows.append({"document": d["doc_id"], "chunks": len(d["chunks"]), "ok": verdicts["ok"],
                     "warn": verdicts["warn"], "fail": verdicts["fail"], "bibliografie": verdicts["references"],
                     **{ISSUE_LABELS[k]: issues[k] for k in ("ocr", "table", "incomplete", "page_break", "columns")}})
    return rows


def failing_chunks_table(docs: list[dict], verdicts: tuple[str, ...] = ("fail", "warn", "references")) -> list[dict]:
    order = {"fail": 0, "references": 1, "warn": 2}
    rows = [{"verdict": c["qc"]["verdict"], "document": d["doc_id"], "chunk": c["chunk_index"],
             "titel": (c.get("title") or "")[:70], "paginas": ", ".join(str(p) for p in c.get("pages", [])),
             "problemen": ", ".join(ISSUE_LABELS[i] for i in c["qc"].get("issues", [])),
             "reden": " | ".join(c["qc"]["reasons"])[:300], "begin": c["text"][:140].replace("\n", " "),
             "einde": c["text"][-100:].replace("\n", " ")}
            for d in docs for c in d["chunks"] if c["qc"]["verdict"] in verdicts]
    return sorted(rows, key=lambda r: (order[r["verdict"]], r["document"], r["chunk"]))


def format_report(docs: list[dict], summary: dict) -> str:
    lines = ["# Orchard QC-rapport RAG-chunks", "",
             f"{summary['n_chunks']} chunks in {summary['n_docs']} documenten "
             f"(taalmodel-controle: {'ja' if summary['lm'] else 'nee'}).", "",
             "Regel: een chunk mag ALLEEN complete zinnen bevatten -- geen afgebroken zinnen, losse "
             "fragmenten, tabellen, figuurtekst, OCR-ruis of pagina-/kolomresten.", "",
             "## Samenvatting", "", "| Oordeel | Aantal |", "|---|---|"]
    for verdict in ("ok", "warn", "fail", "references"):
        lines.append(f"| {verdict} | {summary['counts'].get(verdict, 0)} |")
    lines += ["", "| Probleemtype | Chunks |", "|---|---|"]
    for key, label in ISSUE_LABELS.items():
        lines.append(f"| {label} | {summary['issues'].get(key, 0)} |")
    lines += ["", "## Per document", "", "| Document | chunks | ok | warn | fail | bibl. | OCR | tabel | onvolledig | pagina | kolom |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in per_document_table(docs):
        lines.append(f"| {r['document']} | {r['chunks']} | {r['ok']} | {r['warn']} | {r['fail']} | {r['bibliografie']} | "
                     f"{r[ISSUE_LABELS['ocr']]} | {r[ISSUE_LABELS['table']]} | {r[ISSUE_LABELS['incomplete']]} | "
                     f"{r[ISSUE_LABELS['page_break']]} | {r[ISSUE_LABELS['columns']]} |")
    for verdict in ("fail", "references", "warn"):
        rows = failing_chunks_table(docs, (verdict,))
        if not rows:
            continue
        lines += ["", f"## {verdict} ({len(rows)})", ""]
        for r in rows:
            lines.append(f"- `{r['document']}` [{r['chunk']}] **{r['titel']}** p.{r['paginas']}: {r['reden']}")
            lines.append(f"  > begin: {r['begin']}")
            lines.append(f"  > einde: ...{r['einde']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lm", action="store_true", help="Ook de taalmodel-stage (GPT-2 per taal)")
    parser.add_argument("--no-repair", action="store_true", help="Randfragmenten NIET weghalen (alleen beoordelen)")
    parser.add_argument("--no-write", action="store_true", help="Alleen rapporteren, JSON niet bijwerken")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    paths = AgentPaths.orchard()
    files = sorted(paths.json_dir.glob("*.json"))
    docs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    summary = run_qc(docs, use_lm=args.lm, repair=not args.no_repair,
                     overrides=load_overrides(paths.data_root / "orchard_qc_overrides.json"))
    report = format_report(docs, summary)
    print(report)
    if not args.no_write:
        for f, d in zip(files, docs):
            f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        (paths.json_dir / "_qc_report.md").write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
