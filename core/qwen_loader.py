"""Shared Qwen3-8B (4-bit NF4) loader for the Cherry Orchard Advisor.

Direct port of Auto Pilot's `core/qwen_loader.py` (see
`C:\\Users\\jcsch\\Documents\\Python\\Auto Pilot\\core\\qwen_loader.py`) -- same model,
same quantization recipe, same adapter-stacking convention, so the two projects' cloud
inference servers/clients stay interchangeable patterns. Orchard currently has a single
domain (no VHF/OOW/Captain-style multi-domain dispatch needed), so this is simplified to
take an `AgentPaths` directly rather than a per-domain factory dict.

Safe to run on an 8 GB laptop GPU for inference; never used for training here.
"""
from __future__ import annotations

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

from core.paths import AgentPaths

MODEL_ID = "Qwen/Qwen3-8B"


def load_qwen(weights: str, paths: AgentPaths):
    """`weights="W0_base"` loads bare Qwen3-8B. `weights="MERGED:<dir>"` loads a standalone
    already-merged model directory under `paths.domain_models_dir` directly as the base --
    no adapters applied. Any other value is a "+"-joined chain of LoRA adapter directory
    names (also under `paths.domain_models_dir`) applied in order via PEFT, each merged
    into the base before the next is applied. `weights="MERGED:<dir>+<adapter>[+...]"`
    combines both: starts from the merged dir as the base, then stacks the given
    adapter(s) on top via PEFT without merging/re-saving."""
    bnb = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
    )
    extra_adapter_names: list[str] = []
    if weights.startswith("MERGED:"):
        rest = weights[len("MERGED:"):]
        merged_name, *extra_adapter_names = rest.split("+")
        merged_dir = paths.domain_models_dir / merged_name
        if not merged_dir.exists():
            raise FileNotFoundError(f"No merged model directory at {merged_dir} for weights={weights!r}")
        model_source = str(merged_dir)
    else:
        model_source = MODEL_ID
    tok = AutoTokenizer.from_pretrained(model_source)
    device_map = {"": 0} if torch.cuda.is_available() else "cpu"
    mdl = AutoModelForCausalLM.from_pretrained(
        model_source, quantization_config=bnb, device_map=device_map,
        torch_dtype=torch.bfloat16, attn_implementation="sdpa",
    )
    if weights != "W0_base" and not weights.startswith("MERGED:"):
        adapter_names = weights.split("+")
        models_dir = paths.domain_models_dir
        for i, name in enumerate(adapter_names):
            adapter_dir = models_dir / name
            if not adapter_dir.exists():
                raise FileNotFoundError(f"No adapter directory at {adapter_dir} for weights={weights!r}")
            mdl = PeftModel.from_pretrained(mdl, str(adapter_dir))
            if i < len(adapter_names) - 1:
                mdl = mdl.merge_and_unload()
    elif extra_adapter_names:
        models_dir = paths.domain_models_dir
        for i, name in enumerate(extra_adapter_names):
            adapter_dir = models_dir / name
            if not adapter_dir.exists():
                raise FileNotFoundError(f"No adapter directory at {adapter_dir} for weights={weights!r}")
            mdl = PeftModel.from_pretrained(mdl, str(adapter_dir))
            if i < len(extra_adapter_names) - 1:
                mdl = mdl.merge_and_unload()
    mdl.eval()
    return tok, mdl
