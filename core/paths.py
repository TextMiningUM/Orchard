"""Standard directory layout for a domain-scoped agent in the Orchard repo.

Direct port of the ``AgentPaths`` convention used in the Auto Pilot project
(``core/paths.py`` there) -- see ``design_cherry_orchard_advisor.md`` Sec B.8. One place
to change paths if the convention ever evolves, and impossible to have subtly diverging
paths between the Streamlit app, the ingest/build scripts, and the training scripts.

Convention (illustrated for ``domain="Orchard"``)::

    workspace/
    ├── Data/
    │   └── Orchard/                           ← data_root
    │       ├── OrchardKnowledge/               ← source_dir     (Track 1: WUR/Ctgb/EU/USDA, translated NL)
    │       ├── OrchardLogbooks/                ← logbooks_dir   (Track 2: OCR'd handwritten logbooks 2013-2026)
    │       ├── Orchard_Eval/                   ← eval_dir       (held-out evaluation, NEVER trained on)
    │       │   └── orchard_gold_qa.json        ← gold_file
    │       ├── Orchard_JSON/                   ← json_dir       (structured intermediate output)
    │       └── Orchard_Agents_Training/        ← cache_dir      (RAG/KG/PG/traces/SFT/DPO)
    ├── _models/
    │   ├── hf_cache/                           ← hf_cache_dir   (SHARED, not domain-scoped)
    │   └── Orchard/                            ← domain_models_dir  (fine-tuned Mistral artefacts)
    └── .env                                    ← env_file       (SHARED, not domain-scoped)

Every script/notebook/Streamlit page reads paths from an ``AgentPaths`` instance instead
of hardcoding them.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentPaths:
    """All standard folders for one domain-scoped agent.

    Parameters
    ----------
    domain
        Short domain name, used as the folder segment under ``Data/`` and ``_models/``
        (e.g. ``"Orchard"``). A second orchard domain (apples, pears, ...) would get its
        own ``AgentPaths`` classmethod the same way VHF/OOW/Captain/ChiefEngineer do in
        Auto Pilot -- never fork a second copy of this class, add a classmethod.
    source_dirname
        Name of the Track-1 training-sources subfolder inside ``Data/<domain>/``.
    workspace
        Absolute path to the repository root. Defaults to the parent of the ``core/``
        package, which is correct when the repo is checked out as expected.
    """
    domain: str
    source_dirname: str
    workspace: Path

    def __init__(
        self,
        domain: str,
        source_dirname: str,
        workspace: Path | str | None = None,
    ) -> None:
        # frozen=True disables normal __setattr__; use object.__setattr__ instead.
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "source_dirname", source_dirname)
        if workspace is None:
            workspace = Path(__file__).resolve().parent.parent
        object.__setattr__(self, "workspace", Path(workspace).resolve())

    # ── constructors ─────────────────────────────────────────────────────────────────
    @classmethod
    def orchard(cls, workspace: Path | str | None = None) -> "AgentPaths":
        """Paths object pre-configured for the Cherry Orchard Advisor agent layout."""
        return cls(domain="Orchard", source_dirname="OrchardKnowledge", workspace=workspace)

    @classmethod
    def from_env(cls, workspace: Path | str | None = None) -> "AgentPaths":
        """Paths object selected by the ``ORCHARD_DOMAIN`` env var (default ``"Orchard"``).

        Mirrors Auto Pilot's ``AUTOPILOT_DOMAIN`` convention so every pipeline script can
        stay agnostic of which domain it is building for.
        """
        import os
        name = os.environ.get("ORCHARD_DOMAIN", "Orchard").upper()
        factory = {"ORCHARD": cls.orchard}.get(name)
        if factory is None:
            raise ValueError(f"Unknown ORCHARD_DOMAIN={name!r}; add an AgentPaths classmethod for it.")
        return factory(workspace=workspace)

    # ── data folders (per domain) ────────────────────────────────────────────────────
    @property
    def data_root(self) -> Path:
        return self.workspace / "Data" / self.domain

    @property
    def source_dir(self) -> Path:
        """Track 1: translated-to-NL vakkennis/wetgeving, auto-discovered by the ingest pipeline."""
        return self.data_root / self.source_dirname

    @property
    def logbooks_dir(self) -> Path:
        """Track 2: OCR'd/structured output of the handwritten 2013-2026 logbooks.
        Raw scans themselves stay in ``Data/Data Log Books/`` (outside this tree, untouched)."""
        return self.data_root / "OrchardLogbooks"

    @property
    def ctgb_dir(self) -> Path:
        """Disk cache of Ctgb MST public API responses (public data, but a cache -> gitignored)."""
        return self.data_root / "Ctgb"

    @property
    def eval_dir(self) -> Path:
        """Held-out evaluation material. NEVER goes into training."""
        return self.data_root / f"{self.domain}_Eval"

    @property
    def json_dir(self) -> Path:
        """One hierarchical JSON per source document (structured intermediate output)."""
        return self.data_root / f"{self.domain}_JSON"

    @property
    def cache_dir(self) -> Path:
        """RAG chunks, embeddings, KG, PG, reasoning traces, SFT/DPO/Reflection JSONL."""
        return self.data_root / f"{self.domain}_Agents_Training"

    @property
    def chats_dir(self) -> Path:
        """Saved chat sessions (one JSON file per chat) -- "Vraag de Adviseur"'s ChatGPT-style
        chat history, gitignored (may contain real questions about the teler's own orchard)."""
        return self.data_root / f"{self.domain}Chats"

    @property
    def gold_file(self) -> Path:
        """Committed hand-authored gold Q&A file (in eval_dir)."""
        return self.eval_dir / f"{self.domain.lower()}_gold_qa.json"

    @property
    def heldout_file(self) -> Path:
        """Committed held-out v2 set (never trained on, never used to choose a configuration)."""
        return self.eval_dir / f"{self.domain.lower()}_heldout_qa.json"

    def eval_file(self, name: str) -> Path:
        """Any other held-out file in eval_dir, e.g. paths.eval_file('orchard_scenarios.json')."""
        return self.eval_dir / name

    # ── model folders ────────────────────────────────────────────────────────────────
    @property
    def models_root(self) -> Path:
        """Shared model storage root. Honors ``ORCHARD_MODELS_DIR`` if set, else repo-local ``_models/``."""
        import os
        override = os.environ.get("ORCHARD_MODELS_DIR")
        return Path(override) if override else self.workspace / "_models"

    @property
    def hf_cache_dir(self) -> Path:
        """HuggingFace hub cache. SHARED across all domains, not per-agent."""
        return self.models_root / "hf_cache"

    @property
    def domain_models_dir(self) -> Path:
        """Per-domain fine-tuned artefacts (LoRA adapters, merged Mistral models)."""
        return self.models_root / self.domain

    # ── workspace-level ──────────────────────────────────────────────────────────────
    @property
    def env_file(self) -> Path:
        """Shared ``.env`` (API keys, e.g. an optional KNMI key). Not domain-scoped."""
        return self.workspace / ".env"

    # ── utilities ────────────────────────────────────────────────────────────────────
    def mkdirs(self) -> None:
        """Create every standard directory if missing. Idempotent."""
        for p in (
            self.data_root,
            self.source_dir,
            self.logbooks_dir,
            self.eval_dir,
            self.json_dir,
            self.cache_dir,
            self.chats_dir,
            self.models_root,
            self.hf_cache_dir,
            self.domain_models_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)

    def describe(self) -> str:
        """One-liner per standard path, useful for notebook/debug printouts."""
        rows = [
            ("domain", self.domain),
            ("workspace", self.workspace),
            ("source_dir", self.source_dir),
            ("logbooks_dir", self.logbooks_dir),
            ("eval_dir", self.eval_dir),
            ("gold_file", self.gold_file),
            ("json_dir", self.json_dir),
            ("cache_dir", self.cache_dir),
            ("hf_cache_dir", self.hf_cache_dir),
            ("domain_models_dir", self.domain_models_dir),
            ("env_file", self.env_file),
        ]
        width = max(len(k) for k, _ in rows)
        return "\n".join(f"  {k:<{width}}  {v}" for k, v in rows)
