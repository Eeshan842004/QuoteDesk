# Architecture

## Components

| Component | Where | What |
|---|---|---|
| `datagen/` | laptop | Fictional world, ground-truth scenarios, Gemini email writing + independent verification, splits, Kaggle bundle |
| `eval/evallib/` | everywhere | **Shared contract:** extraction schema, the single system prompt, normalizers, metrics, eval runner, Gemini client |
| `training/` | Kaggle T4 | Unsloth + TRL LoRA notebook → adapter, eval.json, base_eval.json, loss curve, run config |
| `eval/run_eval.py` | laptop | Teacher/student/base/harness evaluations, router calibration, summary.json + EVAL_REPORT.md |
| `backend/` | Modal (CPU) | FastAPI: harness pipeline, tools, SSE, traces, decisions, retraining, MCP |
| `frontend/` | Vercel | Next.js 16: landing, playground, traces, results, models, how-it-works |

## Request flow (`POST /api/quotes/process`, SSE)

```
RECEIVED   customer lookup by sender domain
GUARD      length limit; prompt-injection heuristics -> flag (never block)
EXTRACT    student (Gemma 3 270M + LoRA, greedy, token log-probs)            [skipped in teacher-only mode]
VALIDATE   JSON -> pydantic schema -> semantic checks
REPAIR     one student retry with the validation error (max 1)
ROUTE      confidence = exp(mean logprob) x validity x completeness vs ROUTER_CONFIDENCE_THRESHOLD
ESCALATE   teacher (max 1 call, deadline = remaining of 30 s, cost cap); public -> cached sample or "would escalate"
RESOLVE    tools: search/resolve (top-3 + CONFIDENT/NEEDS_REVIEW), compatibility, history, stock, price
DRAFT      quote lines priced ONLY by get_price; non-quote intents -> suggested action
PENDING_APPROVAL
```
Each step is a span (timing, model, tokens, cost, retries, inputs/outputs), streamed as `event: step` and stored in `spans`.

## Data model

`emails`, `traces`, `spans`, `quotes`, `quote_lines`, `corrections`, `model_versions`, `retrain_runs`, `eval_runs`, plus `app_state` for flags such as the live version and the pause switch.

## Retraining

```
admin EXTRACTION corrections --(threshold)--> run: bundle = train + corrections (exam-hash check)
   manual (v1.1): AWAITING_MANUAL -> you run the notebook -> POST /api/models/register -> gate
   auto (v1.2):   UPLOADING_DATA -> Kaggle dataset version + kernel push -> TRAINING (polled by tick) -> EVALUATING -> gate
gate: exam item F1 >= live + margin, JSON validity >= live, no intent drop > 2 pts  ->  PROMOTED (hot-swap) | REJECTED (reason)
```

## Deployment

- **Modal:** one `@app.cls` with `@modal.asgi_app`, CPU 2 cores / 4 GiB, `min_containers=0`, `max_containers=1`, `scaledown_window=300`, `enable_memory_snapshot=True`. The model loads in `@modal.enter(snap=True)`, and the HF cache lives in a Modal Volume.
- **Neon Postgres** holds state. **Vercel** hosts the static and dynamic pages that call the backend directly (CORS allowlist).

## Security and data handling

- Secrets live only in `.env` (gitignored) and the host secret stores. `tests/test_no_secrets.py` guards this.
- Email text is delimited and treated as data. Injection attempts are flagged, and prices can't be influenced.
- Public visitors: no live teacher calls, sandboxed decisions (never training data), per-IP rate limiting, and a maximum email length.
- The admin token is compared in constant time and sent only in the `X-Admin-Token` header.
