"""Automated RAG chunk quality check via next-token-prediction perplexity (design doc Deel F
#13, G.17): flags chunks whose text is likely GARBLED (PDF multi-column interleaving, table/
caption fragments mixed mid-sentence) rather than genuinely unusual-but-fluent Dutch/English
prose. This automates the "read a sample, confirm it makes sense" requirement in
`.github/copilot-instructions.md` instead of relying purely on manual spot-checks.

Idea: a small causal LM (GPT-2-class) assigns LOW per-token surprisal/perplexity to fluent,
grammatical text it has seen the likes of before, and HIGH perplexity to text where tokens
don't predict each other -- which is exactly the signature of two unrelated PDF columns (or a
table + a caption) chopped into alternating lines. Language-aware: Dutch chunks are scored with
a Dutch GPT-2 (`GroNLP/gpt2-small-dutch`), English chunks with `distilgpt2` -- scoring Dutch
text with an English-only LM would flag well-formed Dutch as "garbled" purely for being a
different language, which is not the failure mode we're trying to catch.

CPU-only, no GPU required (both models are small: 124M/117M parameters). Models are loaded once
and cached per run.

Usage::

    .venv\\Scripts\\python.exe -m pipeline.ingest.check_rag_chunk_quality
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from core.paths import AgentPaths  # noqa: E402

import torch  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

_LM_BY_LANGUAGE = {"nl": "GroNLP/gpt2-small-dutch", "en": "distilgpt2"}
_MAX_TOKENS = 256  # cap per chunk -- chunks are already short (<=220 words), this is headroom


class _PerplexityScorer:
    """Loads one causal LM per language on first use, memoized for the rest of the run."""

    def __init__(self) -> None:
        self._models: dict[str, tuple] = {}

    def _get(self, language: str):
        model_name = _LM_BY_LANGUAGE.get(language, _LM_BY_LANGUAGE["en"])
        if model_name not in self._models:
            print(f"Loading {model_name} ...", flush=True)
            tok = AutoTokenizer.from_pretrained(model_name)
            model = AutoModelForCausalLM.from_pretrained(model_name)
            model.eval()
            self._models[model_name] = (tok, model)
        return self._models[model_name]

    def perplexity(self, text: str, language: str) -> float:
        """Pseudo-perplexity via next-token cross-entropy under the language-appropriate LM --
        lower is more fluent/predictable, higher means the token sequence surprised the model
        (consistent with interleaved-column or table-fragment garbling)."""
        tok, model = self._get(language)
        ids = tok(text, return_tensors="pt", truncation=True, max_length=_MAX_TOKENS)["input_ids"]
        if ids.shape[1] < 2:
            return float("nan")  # too short to score (next-token loss needs >=2 tokens)
        with torch.no_grad():
            out = model(ids, labels=ids)
        return float(torch.exp(out.loss))


def score_chunks(chunks: list[dict], scorer: _PerplexityScorer | None = None) -> list[dict]:
    """Returns `chunks` (each dict augmented with a `"perplexity"` field), worst (highest
    perplexity, most likely garbled) first. Pure except for the LM calls -- a `scorer` can be
    injected for testing without loading real models."""
    scorer = scorer or _PerplexityScorer()
    scored = []
    for c in chunks:
        ppl = scorer.perplexity(c["text"], c.get("language", "nl"))
        scored.append({**c, "perplexity": ppl})
    scored.sort(key=lambda c: (c["perplexity"] != c["perplexity"], -c["perplexity"]))  # NaN last
    return scored


def main() -> None:
    paths = AgentPaths.orchard()
    chunks_path = paths.cache_dir / "orchard_rag_chunks.json"
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    print(f"Scoring {len(chunks)} chunks ...")
    scored = score_chunks(chunks)

    print("\n=== 25 meest verdachte chunks (hoogste perplexity -- waarschijnlijk kapot) ===")
    for c in scored[:25]:
        preview = c["text"][:160].replace("\n", " ")
        print(f"  ppl={c['perplexity']:7.1f}  {c['doc_id']} p{c['page_num']}  :: {preview!r}")

    out_path = paths.cache_dir / "orchard_rag_chunk_quality.json"
    out_path.write_text(
        json.dumps(
            [{"chunk_id": c["chunk_id"], "doc_id": c["doc_id"], "page_num": c["page_num"],
              "perplexity": c["perplexity"]} for c in scored],
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nVolledige scorelijst geschreven: {out_path}")


if __name__ == "__main__":
    main()
