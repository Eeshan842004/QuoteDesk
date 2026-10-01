# Evaluation report

Generated from `eval/reports/2026-09-30/summary.json` on 2026-10-01T11:26:09. Every number below is copied from that file.

## exam split

| System | Intent acc | JSON valid | Item F1 | Qty acc | Missing-info F1 | Exact match | SKU resolution | p50 s | p95 s | Escalated | Cost / 1k |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Base Gemma 3 270M (3-shot) | 50.7% | 66.0% | 17.5% | 30.5% | 0.0% | 0.7% | – | 1.26 | 1.88 | – | – |
| Fine-tuned Gemma 3 270M (GPU, notebook) | 98.0% | 98.7% | 92.1% | 93.4% | 13.5% | 60.0% | – | 1.03 | 2.06 | – | – |
| Fine-tuned Gemma 3 270M (CPU) | 98.0% | 98.7% | 93.1% | 94.2% | 16.0% | 58.7% | 93.5% | 7.40 | 22.32 | – | $0.345 |
| Fine-tuned Gemma 3 270M (CPU) + rule fixes | 98.0% | 98.7% | 93.1% | 94.2% | 66.7% | 71.3% | 93.5% | 7.40 | 22.32 | – | $0.345 |
| Gemini 3.8 Flash (teacher) | 97.3% | 100.0% | 97.0% | 97.0% | 91.4% | 54.0% | 95.1% | 7.87 | 123.25 | – | $1.064 |
| Full harness (student + router + teacher) | 99.3% | 100.0% | 96.2% | 96.2% | 74.3% | 74.0% | 95.1% | 8.35 | 28.26 | 9.3% | $0.454 |

## exam_hard split

| System | Intent acc | JSON valid | Item F1 | Qty acc | Missing-info F1 | Exact match | SKU resolution | p50 s | p95 s | Escalated | Cost / 1k |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Base Gemma 3 270M (3-shot) | 36.7% | 46.7% | 27.6% | 63.2% | 0.0% | 3.3% | – | 0.91 | 1.08 | – | – |
| Fine-tuned Gemma 3 270M (GPU, notebook) | 60.0% | 66.7% | 69.9% | 82.9% | 0.0% | 26.7% | – | 0.72 | 1.29 | – | – |
| Fine-tuned Gemma 3 270M (CPU) | 60.0% | 66.7% | 69.9% | 82.9% | 0.0% | 26.7% | 83.3% | 7.34 | 14.21 | – | $0.293 |
| Fine-tuned Gemma 3 270M (CPU) + rule fixes | 60.0% | 66.7% | 69.9% | 82.9% | 13.3% | 23.3% | 83.3% | 7.34 | 14.21 | – | $0.293 |
| Gemini 3.8 Flash (teacher) | 100.0% | 100.0% | 100.0% | 100.0% | 93.3% | 83.3% | 100.0% | 5.16 | 65.44 | – | $0.947 |
| Full harness (student + router + teacher) | 93.3% | 100.0% | 91.8% | 97.5% | 30.8% | 60.0% | 97.2% | 9.65 | 62.15 | 43.3% | $0.710 |

Router threshold (chosen on val): **0.66**. See `calibration.png`.

## How we measured

- Exam (150) and exam_hard (30) are sealed: hashed and checked against every training file.
- Item F1 matches items by description similarity (token-set >= 80) AND equal quantity.
- SKU resolution runs the deterministic tools on each system's extraction and checks the top SKU.
- Teacher cost = measured tokens x Google's published paid price for gemini-3.8-flash; calls go through the KIE proxy.
- Student cost is an estimate: CPU inference seconds x Modal CPU container price.
- Latency: teacher = wall-clock via KIE (includes queueing); student = single-email CPU decoding.
