"""Explicit, deterministic reward for an advisor answer (design doc Deel F #17).

Used (a) to rank sampled answers for DPO pairs (rejection sampling) and (b) later as the signal for any RL-style
optimisation. Nothing here calls a model: every component is a pure function of the answer, the context the model was
given and the gold facts, so the reward cannot be talked around and is the same on every machine.

    reward = gate * (w_cov * coverage + w_focus * focus + w_ground * grounding + w_num * numeric_faithfulness
                     + w_complete * completeness + w_concise * conciseness)       (weights renormalised if focus is absent)

``gate`` is 0 when the answer breaks a compliance rule (a dose per area / per volume, or an unqualified statement that a
product is (not) authorised -- the Ctgb lookup is a documented stub, so the advisor cannot know) and 1 otherwise: a dose
leak can never be compensated by being complete. Components, each in [0, 1]:

* coverage            share of the gold key facts that appear in the answer (alternatives allowed, accent-folded)
* focus               share of the answer's content words that occur in the gold source text (or the question): an answer
                      that wanders into neighbouring fragments (the typical failure of a retrieval-augmented model with 6
                      fragments in its prompt) scores low. Needs ``gold_text``; without it the component is left out and
                      the other weights are renormalised
* grounding           the answer ends with a ``Bronnen:`` line (it cites what it was given)
* numeric_faithfulness share of the numbers in the answer that also occur in the question or the retrieved context
                      (invented numbers are the typical hallucination in an agronomy advisor; fragment / card / page
                      references and list numbering are not counted)
* completeness        the answer is not cut off: it has a Bronnen line or ends in sentence punctuation
* conciseness         1 up to ``concise_words`` words, falling linearly to 0 at ``max_words``

The weights are a first, explicit proposal -- coverage and focus dominate because key-fact coverage was the measured weak point
(design doc G.27) and a smoke test of the base model showed it copies the right card but pads with unrelated fragments;
change them in ONE place (``RewardConfig``) and re-rank, nothing else depends on them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from pipeline.orchard_eval import fact_coverage, forbidden_matches, normalize

GUARD_PATTERNS = ["DOSE", "DOSE2", "CLAIM"]
_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?")
_REFERENCE_RE = re.compile(r"(fragment|kaart|p\.|pagina|blz\.?|stap)\s*\d+(?:\s*[-\u2013,]\s*\d+)*|^\s*\d+[.)]\s", re.I | re.M)
_SOURCES_RE = re.compile(r"(?im)^\W*bronnen?\s*:")
_STEM_LEN = 7
_FOCUS_STEM = 6
# words the answer format itself introduces (labels, citation line): never counted against focus
_FORMAT_WORDS = {"bronnen", "fragment", "fragmenten", "vermijd", "effect", "waarom", "actie", "gevolg", "observatie", "kaart",
                 "status", "bevestigd", "kennisbank", "kersenteelt", "problemen", "samenstelling", "internet", "crawl",
                 "ctgb_toelating", "databank", "etiket", "toelating", "slechtste", "reactie", "praktisch", "relevante",
                 "belangrijk", "daarom", "omdat", "waarbij", "tijdens", "voordat", "zodat", "wanneer", "bijvoorbeeld",
                 "bronnen", "eigen", "logboek"}
_STOPWORDS = {"zonder", "tijdens", "tussen", "daarna", "voordat", "tegen", "boven", "onder", "binnen", "altijd", "alleen",
              "meestal", "eventueel", "bijvoorbeeld", "gebruiken", "gebruik"}


@dataclass(frozen=True)
class RewardConfig:
    w_coverage: float = 0.35
    w_focus: float = 0.20
    w_grounding: float = 0.10
    w_numeric: float = 0.15
    w_complete: float = 0.10
    w_concise: float = 0.10
    concise_words: int = 250
    max_words: int = 600


DEFAULT = RewardConfig()


def _content_stems(text: str) -> set[str]:
    return {w[:_FOCUS_STEM] for w in re.findall(r"[a-z]{6,}", normalize(text)) if w not in _FORMAT_WORDS}


def focus(answer: str, gold_text: str, question: str = "") -> float:
    """Share of the answer's content-word stems that are supported by the gold source text or the question."""
    stems = _content_stems(answer)
    if not stems:
        return 1.0
    allowed = _content_stems(gold_text) | _content_stems(question)
    return len(stems & allowed) / len(stems)


def card_key_facts(steps: list[str]) -> list[list[str]]:
    """Proxy key facts for a problem card with no hand-written ones: per action step the longest content word, as a
    ``_STEM_LEN``-letter stem so inflections match (drainage / drainageslangen). Deliberately crude and cheap; by
    construction every stem occurs in the card, which is in the model's context."""
    facts = []
    for step in steps:
        words = [w for w in re.findall(r"[a-z]{6,}", normalize(step)) if w not in _STOPWORDS]
        if words:
            stem = max(words, key=len)[:_STEM_LEN]
            if [stem] not in facts:
                facts.append([stem])
    return facts


def _numbers(text: str) -> list[str]:
    return [n.replace(",", ".") for n in _NUMBER_RE.findall(_REFERENCE_RE.sub(" ", text))]


def numeric_faithfulness(answer: str, context: str) -> float:
    nums = _numbers(answer)
    if not nums:
        return 1.0
    ctx = {n for n in _numbers(context)}
    return sum(1 for n in nums if n in ctx) / len(nums)


def is_complete(answer: str) -> bool:
    text = answer.strip()
    if not text or ("<think>" in text and "</think>" not in text):
        return False
    if _SOURCES_RE.search(text):
        return not text.rstrip().endswith((",", "-", "(", " en", " of"))
    return text.endswith((".", "!", "?", ")", "**", "]"))


def conciseness(answer: str, cfg: RewardConfig = DEFAULT) -> float:
    n = len(answer.split())
    if n <= cfg.concise_words:
        return 1.0
    return max(0.0, 1.0 - (n - cfg.concise_words) / (cfg.max_words - cfg.concise_words))


def score_answer(answer: str, *, key_facts: list[list[str]], context: str = "", question: str = "",
                 gold_text: str | None = None, cfg: RewardConfig = DEFAULT, guard_patterns: list[str] | None = None) -> dict:
    """Returns the components, the compliance ``gate``, the ``violations`` and the final ``reward``."""
    violations = forbidden_matches(answer, guard_patterns or GUARD_PATTERNS)
    coverage, missing = fact_coverage(answer, key_facts)
    comps = {
        "coverage": coverage,
        "grounding": 1.0 if _SOURCES_RE.search(answer) else 0.0,
        "numeric": numeric_faithfulness(answer, context + " " + question),
        "complete": 1.0 if is_complete(answer) else 0.0,
        "concise": conciseness(answer, cfg),
    }
    weights = {"coverage": cfg.w_coverage, "grounding": cfg.w_grounding, "numeric": cfg.w_numeric,
               "complete": cfg.w_complete, "concise": cfg.w_concise}
    if gold_text is not None:
        comps["focus"] = focus(answer, gold_text, question)
        weights["focus"] = cfg.w_focus
    weighted = sum(weights[k] * comps[k] for k in weights) / sum(weights.values())
    gate = 0.0 if violations else 1.0
    return {**comps, "gate": gate, "violations": violations, "missing_facts": missing, "reward": gate * weighted}
