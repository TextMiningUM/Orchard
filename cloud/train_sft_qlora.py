"""QLoRA SFT of Qwen3-8B on the Orchard card dataset (runs on the pod, in ``.venv`` which has torch/peft/bitsandbytes).

    sudo systemctl stop orchard-qwen            # the A30 (24 GB) cannot hold vLLM and training at once
    .venv/bin/python cloud/train_sft_qlora.py --train sft_cards_train.jsonl --val sft_cards_val.jsonl --out _models/Orchard/sft_cards_v1
    sudo systemctl start orchard-qwen           # then serve it: weights="sft_cards_v1" (vLLM LoRA on the AWQ base)

Design choices (each deliberate, see design doc G.28):
* The loss is computed on the ANSWER ONLY. The prompt is the exact inference prompt rendered with Qwen3's chat template and
  ``enable_thinking=False`` (which ends in an empty ``<think></think>`` block), so train and serve prompts are identical.
* Rank 16 = vLLM's default ``max_lora_rank``; all attention + MLP projections; small learning rate (1e-4) and 3 epochs because
  the data is tiny (~100 examples): the goal is the answer FORMAT / completeness, not new knowledge.
* Trained on the bf16 base in 4-bit NF4, served on the AWQ-quantised base: the usual QLoRA deployment gap. The evaluation
  (run_orchard_eval --weights <adapter>) measures the adapter as it is actually served, which is what counts.
* Only Track 1 data (public knowledge-base cards) is ever copied to the pod, never logbook data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

IGNORE = -100
BASE_MODEL = "Qwen/Qwen3-8B"
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def mask_example(prompt_ids: list[int], completion_ids: list[int], max_len: int) -> dict | None:
    """input_ids = prompt + completion; labels = IGNORE over the prompt. Returns None when the example does not fit
    (an over-long example is dropped, never truncated: a truncated answer would teach the model to stop mid-sentence)."""
    if len(prompt_ids) + len(completion_ids) > max_len:
        return None
    return {"input_ids": prompt_ids + completion_ids, "labels": [IGNORE] * len(prompt_ids) + completion_ids,
            "attention_mask": [1] * (len(prompt_ids) + len(completion_ids))}


def build_examples(rows: list[dict], tokenizer, max_len: int) -> tuple[list[dict], int]:
    examples, dropped = [], 0
    for row in rows:
        system, user, answer = row["messages"]
        prompt_text = tokenizer.apply_chat_template([system, user], tokenize=False, add_generation_prompt=True,
                                                    enable_thinking=False)
        prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
        completion_ids = tokenizer(answer["content"] + "<|im_end|>", add_special_tokens=False)["input_ids"]
        ex = mask_example(prompt_ids, completion_ids, max_len)
        if ex is None:
            dropped += 1
        else:
            examples.append(ex)
    return examples, dropped


def collate(batch: list[dict], pad_id: int) -> dict:
    import torch

    width = max(len(b["input_ids"]) for b in batch)
    pad = lambda seq, value: seq + [value] * (width - len(seq))  # noqa: E731
    return {"input_ids": torch.tensor([pad(b["input_ids"], pad_id) for b in batch]),
            "labels": torch.tensor([pad(b["labels"], IGNORE) for b in batch]),
            "attention_mask": torch.tensor([pad(b["attention_mask"], 0) for b in batch])}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default=BASE_MODEL)
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--max-len", type=int, default=6144)
    ap.add_argument("--max-steps", type=int, default=-1, help="smoke test: stop after N optimizer steps")
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args(argv)

    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, Trainer, TrainingArguments,
                              set_seed)

    set_seed(args.seed)
    tok = AutoTokenizer.from_pretrained(args.base)
    train, d1 = build_examples(read_jsonl(Path(args.train)), tok, args.max_len)
    val, d2 = build_examples(read_jsonl(Path(args.val)), tok, args.max_len)
    print(f"examples: train {len(train)} (dropped {d1}), val {len(val)} (dropped {d2}); "
          f"mean tokens {sum(len(e['input_ids']) for e in train) / max(1, len(train)):.0f}", flush=True)

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(args.base, quantization_config=bnb, dtype=torch.bfloat16, device_map={"": 0})
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.05,
                                             target_modules=TARGET_MODULES, task_type="CAUSAL_LM"))
    model.print_trainable_parameters()

    out = Path(args.out)
    targs = TrainingArguments(
        output_dir=str(out / "_checkpoints"), per_device_train_batch_size=1, per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.grad_accum, num_train_epochs=args.epochs, max_steps=args.max_steps,
        learning_rate=args.lr, lr_scheduler_type="cosine", warmup_steps=0.1, weight_decay=0.0, bf16=True,
        gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
        logging_steps=1, eval_strategy="epoch", save_strategy="epoch", save_total_limit=1,
        load_best_model_at_end=args.max_steps < 0, metric_for_best_model="eval_loss", greater_is_better=False,
        report_to=[], seed=args.seed, remove_unused_columns=False,
    )
    trainer = Trainer(model=model, args=targs, train_dataset=train, eval_dataset=val,
                      data_collator=lambda b: collate(b, tok.pad_token_id))
    trainer.train()
    metrics = trainer.evaluate()
    print("final eval:", metrics, flush=True)
    out.mkdir(parents=True, exist_ok=True)
    trainer.model.save_pretrained(str(out))
    tok.save_pretrained(str(out))
    (out / "train_log.json").write_text(json.dumps({"args": vars(args), "log_history": trainer.state.log_history,
                                                    "final_eval": metrics, "n_train": len(train), "n_val": len(val)}, indent=1),
                                        encoding="utf-8")
    print(f"adapter saved to {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
