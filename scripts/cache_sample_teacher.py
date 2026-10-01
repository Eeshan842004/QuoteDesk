"""Cache the teacher's output for the 8 demo samples so the live demo works even if the LLM quota runs out.

    python scripts/cache_sample_teacher.py          # -> backend/app/samples/teacher_cache.json
The UI labels these results "cached". About 8 teacher calls (~0.6 KIE credits).
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT)]

from datagen.config import LLMSettings  # noqa: E402
from evallib.llm import client_from_settings  # noqa: E402
from evallib.prompt import teacher_system_prompt, user_message  # noqa: E402
from evallib.schema import Extraction  # noqa: E402

SAMPLES = ROOT / "backend" / "app" / "samples"


def main():
    s = LLMSettings()
    client = client_from_settings(s, s.teacher_model, max_attempts=5, cost_log=ROOT / "data" / "generated" / "cost_log.jsonl")
    samples = json.loads((SAMPLES / "samples.json").read_text(encoding="utf-8"))
    out_path = SAMPLES / "teacher_cache.json"
    cache = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    for smp in samples:
        if smp["id"] in cache and "--force" not in sys.argv:
            print("cached already:", smp["id"])
            continue
        r = client.generate(teacher_system_prompt(), user_message(smp["sender"], smp["subject"], smp["body"]),
                            Extraction, tag="sample_cache", use_cache=False)
        cache[smp["id"]] = {"text": json.dumps(r.parsed), "model": r.model, "provider": r.provider,
                            "prompt_tokens": r.prompt_tokens, "output_tokens": r.billable_output_tokens,
                            "latency_s": round(r.latency_s, 2), "cached_at": time.strftime("%Y-%m-%d")}
        print(f"{smp['id']}: {len(r.parsed['items'])} items, intent={r.parsed['intent']} ({r.latency_s:.1f}s)")
        out_path.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    print("wrote", out_path)


if __name__ == "__main__":
    main()
