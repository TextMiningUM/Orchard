"""The pure parts of the SFT trainer: loss masking and example building (no torch needed)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cloud.train_sft_qlora import IGNORE, build_examples, mask_example  # noqa: E402


class FakeTokenizer:
    """One 'token' per character; chat template = role-tagged text ending in the Qwen3 non-thinking generation prefix."""

    def apply_chat_template(self, messages, tokenize, add_generation_prompt, enable_thinking):
        assert not tokenize and add_generation_prompt and enable_thinking is False
        return "".join(f"<{m['role']}>{m['content']}" for m in messages) + "<assistant><think></think>"

    def __call__(self, text, add_special_tokens):
        assert add_special_tokens is False
        return {"input_ids": [ord(c) for c in text]}


def test_mask_example_supervises_only_the_answer():
    ex = mask_example([1, 2, 3], [4, 5], 10)
    assert ex["input_ids"] == [1, 2, 3, 4, 5] and ex["labels"] == [IGNORE] * 3 + [4, 5] and ex["attention_mask"] == [1] * 5


def test_over_long_examples_are_dropped_not_truncated():
    assert mask_example([1] * 8, [2] * 3, 10) is None
    assert mask_example([1] * 7, [2] * 3, 10) is not None


def test_build_examples_uses_the_inference_prompt_and_ends_the_answer_with_im_end():
    rows = [{"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "U"},
                          {"role": "assistant", "content": "ANTWOORD"}]},
            {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "U" * 50},
                          {"role": "assistant", "content": "A"}]}]
    examples, dropped = build_examples(rows, FakeTokenizer(), max_len=60)
    assert dropped == 1 and len(examples) == 1
    ids, labels = examples[0]["input_ids"], examples[0]["labels"]
    text = "".join(chr(i) for i in ids)
    assert text.startswith("<system>S<user>U<assistant><think></think>ANTWOORD<|im_end|>")
    supervised = "".join(chr(l) for l in labels if l != IGNORE)
    assert supervised == "ANTWOORD<|im_end|>"
