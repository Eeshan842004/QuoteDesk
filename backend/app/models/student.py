"""Student model on CPU: Gemma 3 270M + LoRA adapter (merged for speed), greedy decoding with token log-probs.

The prompt is built exactly like training: evallib chat messages -> chat template -> strip leading <bos>
(the tokenizer adds it back), matching the official Unsloth Gemma 3 notebook.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class StudentOutput:
    text: str
    mean_logprob: float
    min_token_prob: float
    n_tokens: int
    prompt_tokens: int
    latency_s: float


class StudentModel:
    def __init__(self, base_model: str, adapter: Optional[str] = None, revision: Optional[str] = None,
                 hf_token: Optional[str] = None, max_new_tokens: int = 384, threads: Optional[int] = None,
                 quantize: Optional[str] = None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if threads:
            torch.set_num_threads(threads)
        self.base_model, self.adapter, self.revision = base_model, adapter, revision
        self.max_new_tokens = max_new_tokens
        tok_src, tok_rev = (adapter, revision) if adapter else (base_model, None)
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(tok_src, revision=tok_rev, token=hf_token)
        except Exception:
            self.tokenizer = AutoTokenizer.from_pretrained(base_model, token=hf_token)
        model = AutoModelForCausalLM.from_pretrained(base_model, dtype=torch.float32, token=hf_token,
                                                     attn_implementation="eager")
        if adapter:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, adapter, revision=revision, token=hf_token)
            model = model.merge_and_unload()
        model.eval()
        if quantize == "int8":
            # dynamic int8 on Linear layers: ~30% faster CPU decoding in our benchmark; accuracy must be re-checked
            # with `eval/run_eval.py student --quantize int8` before enabling it in production
            model = torch.ao.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
        self.quantize = quantize
        self.model = model
        self._lock = threading.Lock()
        self.version = revision or ("local" if adapter else "base")

    def prompt_text(self, messages: list[dict]) -> str:
        text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        return text.removeprefix("<bos>")

    def generate(self, messages: list[dict], max_new_tokens: Optional[int] = None) -> StudentOutput:
        import torch

        text = self.prompt_text(messages)
        enc = self.tokenizer(text, return_tensors="pt")
        t0 = time.perf_counter()
        with self._lock, torch.inference_mode():
            out = self.model.generate(**enc, max_new_tokens=max_new_tokens or self.max_new_tokens, do_sample=False,
                                      output_scores=True, return_dict_in_generate=True,
                                      pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id)
            scores = self.model.compute_transition_scores(out.sequences, out.scores, normalize_logits=True)[0]
        latency = time.perf_counter() - t0
        gen_ids = out.sequences[0, enc["input_ids"].shape[1]:]
        logps = [float(x) for x in scores.tolist() if math.isfinite(float(x))]
        return StudentOutput(
            text=self.tokenizer.decode(gen_ids, skip_special_tokens=True).strip(),
            mean_logprob=sum(logps) / len(logps) if logps else -99.0,
            min_token_prob=math.exp(min(logps)) if logps else 0.0,
            n_tokens=len(gen_ids), prompt_tokens=int(enc["input_ids"].shape[1]), latency_s=latency)
