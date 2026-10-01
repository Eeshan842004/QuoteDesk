# QuoteDesk: Build Plan

**Status (2026-09-30):** P0, P1 (dataset), P2a (notebook + eval library), P3, P5, P6 (manual + auto code), P7 and the P8 deployment files are built and tested locally. **Trained and evaluated (2026-10-01):** v1 adapter on HF (`Eeshan082004/quotedesk-student`), CPU evaluation, router calibration (threshold 0.66), harness evaluation and the report are done; see docs/EVAL_REPORT.md. **Remaining, needs you:** create the Modal / Neon / Vercel accounts and deploy (docs/DEPLOY.md), rotate the KIE key.

**P1 result (real numbers):** 1,800 scenarios → 1,800 emails written → 1,674 kept after verification (126 dropped, 7.0%: mostly compatible_with / quantity disagreements) → split 1,334 train / 150 val / 150 exam / 30 hand-written exam_hard / 40 reserved for the corrections demo. Leakage, secrets and real-brand tests pass. KIE balance fell from about 482 to 241 credits during datagen plus the start of the teacher baseline (timed-out calls appear to be billed; see DECISIONS D9/D15).
**Repo root:** this folder (becomes the public `quotedesk` GitHub repo)
**Companion docs:** [docs/DECISIONS.md](docs/DECISIONS.md) (terms, licensing, provider probes, hosting) · [docs/LEARNING.md](docs/LEARNING.md) (plain-English notes per phase)

---

## 0. Ground rules added after review

1. **Zero spend.** Nothing may cost money beyond the existing KIE credits. Every service is on a free tier with **no card on file**: Modal Starter, Neon Free, Vercel Hobby, HF Hub, Kaggle.
2. **Release order**

   | Release | Phases | Contents |
   |---|---|---|
   | **v1** | P0, P1, P2a, P2b, P3, P4, P5, P8 | dataset, notebook, eval, harness, student, frontend (no /models page), Modal deploy |
   | **v1.1** | P6 (manual path) | manual retrain + register + safety gate, `/models` page |
   | **v1.2** | P6-auto + P7 | automatic retrain (evaluate Modal GPU vs Kaggle API), MCP server |

3. **Dataset first.** You train on Kaggle yourself. P0 → P1 → P2a produces the Kaggle bundle and the notebook.
4. **LLM provider = KIE.ai** (paid credits) for Gemini 3.8 Flash; see the probe in DECISIONS D4. **KIE budget rule:** after the 20-email pilot I project total credit use. If it exceeds your remaining credits, I **ask you** before switching datagen to `LLM_PROVIDER=google` (free AI Studio key, slower pacing).
5. **Teacher from public visitors:** `TEACHER_LIVE_MODE=admin_only` (decided).
6. **Backend host = Modal** (Starter, $30/month free credits, no card), CPU only, scale to zero. The backup (documented only) is a free HF ZeroGPU Gradio Space.
7. **docs/LEARNING.md:** at the end of every phase I add a plain-English section (what was built, why, and 3 likely interview questions with good answers).
8. Verifier uses `gemini-3-7-flash`, a different model from the writer. The shared schema and prompt live in `eval/evallib/`. About 3% of training emails contain embedded instruction text with an unchanged label. There is a `vague` item type that produces `size_or_spec` missing info.

---

## 1. Architecture summary

```
[Vercel Hobby: Next.js 16 frontend]
        |  HTTPS + SSE (text/event-stream)
        v
[Modal Starter: one ASGI web function, CPU only, scale-to-zero, max 1 container]
   |-- FastAPI app: harness pipeline, tools, API (MCP mounted in v1.2)
   |-- Student: Gemma 3 270M + LoRA (weights from HF Hub, cached in Modal Volume, loaded in @modal.enter(snap=True))
   |-- Teacher client: Gemini 3.8 Flash via KIE (SSE, responseSchema); admin_only for public traffic
   |-- Tools: catalog / fuzzy / compat / history / stock / pricing (pure Python)
   '-- SQLAlchemy --> Neon Postgres Free (SQLite locally)
Offline (my laptop): datagen/ (code ground truth -> KIE writes -> KIE verifies -> split/export) -> Kaggle bundle
Kaggle (you, free T4): notebook -> adapter + eval.json -> HF Hub tag vN
v1.1: admin corrections -> orchestrator builds zip -> you run notebook -> POST /api/models/register -> safety gate
v1.2: automatic retrain via Modal cron + GPU (or Kaggle API), MCP server at /mcp
```

Principles:
- Labels come from code.
- Prices come only from tools.
- Every step is a traced span.
- Every UI number is read from an `eval/reports/<ts>/*.json` file.

**Modal app layout (P8):** `backend/modal_app.py`
- Image: `debian_slim` + Python 3.11 + `backend/requirements.txt`, with the CPU torch wheel.
- `modal.Volume.from_name("quotedesk-hf-cache", create_if_missing=True)` mounted at `/cache`, with `HF_HOME=/cache/hf`.
- Secret `modal.Secret.from_name("quotedesk-secrets")`.
- `@app.cls(cpu=2.0, memory=4096, scaledown_window=300, min_containers=0, max_containers=1, enable_memory_snapshot=True)`:
  - `@modal.enter(snap=True)` loads the base model, merges the LoRA, and loads the catalog.
  - `@modal.concurrent(max_inputs=8)` + `@modal.asgi_app()` return the FastAPI app.
- **No APScheduler in v1.** Scale-to-zero containers can't run background schedulers reliably, so v1.2 uses a Modal cron instead (Starter allows 5).

---

## 2. Verified versions and limits (checked 2026-09-30)

| Item | Pinned | Source / note |
|---|---|---|
| Teacher model | `gemini-3-8-flash` (KIE) / `gemini-3.8-flash` (Google) | ai.google.dev/gemini-api/docs/models; KIE docs; live probe |
| Verifier model | `gemini-3-7-flash` (KIE) | KIE docs; confirmed by probe in P1 |
| KIE API | SSE `streamGenerateContent`; `responseSchema` honored; `responseJsonSchema` ignored; 20 req / 10 s; balance `GET https://api.kie.ai/api/v1/chat/credit` | docs.kie.ai; live probe (D4) |
| Teacher price for cost metric | $0.75 in / $3.75 out per 1M tokens (thinking billed as output), through 2026-12-31 | ai.google.dev/gemini-api/docs/pricing |
| Student base | `google/gemma-3-270m-it` (gated, 32K ctx); notebook loads `unsloth/gemma-3-270m-it` (same weights) | HF model card; Unsloth notebook |
| Student fallback | `google/gemma-3-1b-it` | only if 270M accuracy is too low and CPU p95 stays OK |
| Gemma 4 option | E2B (Apache 2.0), Unsloth supported | not recommended: too slow on 2 CPU cores |
| google-genai | 2.25.0 | PyPI (optional provider only) |
| pydantic / rapidfuzz / httpx | 2.13.5 / 3.14.6 / 0.28.1 | PyPI |
| unsloth / trl | 2026.9.12 / 1.14.1 | PyPI. **Notebook installs what the official Unsloth Gemma3 (270M) notebook pins on training day**; resolved versions go to `run_config.json` |
| transformers / peft / torch (backend CPU) | 5.17.0 / 0.21.1 / 2.14.0 (CPU wheel) | PyPI. Backend majors matched to `run_config.json` in P4 |
| fastapi / sse-starlette / slowapi | 0.142.2 / 3.5.0 / 0.1.10 | PyPI |
| sqlalchemy / alembic | 2.1.1 / 1.20.0 | PyPI |
| mcp (Python SDK), v1.2 | 2.2.0 | PyPI; mount API re-verified when built |
| huggingface_hub | 2.0.0 | PyPI |
| kaggle CLI (v1.2 only) | 2.2.4; auth `KAGGLE_API_TOKEN` or legacy `kaggle.json`; kernel-metadata `enable_gpu`, `enable_internet`, `machine_shape: "NvidiaTeslaT4"` | github.com/Kaggle/kaggle-cli docs |
| **modal** client | 1.6.0 | PyPI |
| **Modal Starter** | $30/month free compute, no card; 100 containers, 5 deployed crons, 3 seats | modal.com/pricing |
| **Modal prices** | CPU $0.0000131 / core / s (min 0.125 core); memory $0.00000222 / GiB / s; volumes $0.09 / GiB / month (pricing page notes "includes 1 TiB / mo free") | modal.com/pricing |
| **Modal web endpoints** | `@modal.asgi_app()` for full FastAPI; URL `https://<workspace>--<app>-<fn>.modal.run`; **150 s max HTTP request** (then 303 redirect); SSE streams in real time when MIME is `text/event-stream` | modal.com/docs/guide/webhooks, webhook-timeouts, streaming-endpoints |
| **Modal cold start** | `scaledown_window` default 60 s (range 2 s to 20 min); `min_containers` for keep-warm (not used); `@modal.enter(snap=True)` + `enable_memory_snapshot=True` work on CPU (docs: "3-10x faster") | modal.com/docs/guide/cold-start, memory-snapshot |
| **Modal volumes** | `Volume.from_name(..., create_if_missing=True)`; `volumes={"/cache": vol}`; set `HF_HOME` inside the volume; `commit()` / `reload()` | modal.com/docs/guide/volumes |
| Next.js / React / Tailwind | 16.3.7 / 19.3.0 / 4.3.3 | npm; use `create-next-app@16` defaults (TS 7.0.2 is latest but may not be supported yet) |
| shadcn CLI / recharts / mermaid | 4.21.0 / 3.10.1 / 12.0.0 | npm |
| Neon Free | 0.5 GB/project, 100 CU-hours/project, scale-to-zero after 5 min, no card | neon.com/pricing |
| HF ZeroGPU (backup only) | free accounts (verified email, account > 30 days) host up to 2 ZeroGPU Spaces; **Gradio SDK only**; visitor daily quota 2 min (anonymous) / 5 min (free account); `@spaces.GPU(duration=...)`; Python 3.10/3.12 | hf.co/docs/hub/spaces-zerogpu |
| Local toolchain | Python 3.11.9, Node 24.13.0, git 2.53 | this machine |

### Modal monthly credit estimate (must stay well under $30)
Container: 2 cores + 4 GiB → 2 × $0.0000131 + 4 × $0.00000222 = **$0.0000351/s ≈ $0.126 per warm hour**.

| Usage | Container time | Est. cost |
|---|---|---|
| One demo visit (cold start about 1 min + 5 min use + 5 min `scaledown_window`) | about 11 min | ≈ $0.023 |
| 200 visits/month (generous for a portfolio) | about 37 h | ≈ $4.60 |
| `warmup.sh` before sharing, 20 × 30 min | 10 h | ≈ $1.26 |
| My dev/test deploys | about 10 h | ≈ $1.26 |
| HF cache volume (about 1.5 GB) | n/a | ≈ $0.14 or less |
| **Total** | | **≈ $7/month (about 25% of the free $30)** |
| For contrast: 24/7 keep-warm (`min_containers=1`) | 730 h | ≈ $92, **not allowed** |

Guards:
- `max_containers=1`
- no keep-warm
- `scaledown_window=300`
- `/api/health` doesn't load the model
- per-IP rate limit (`slowapi`)
- with no card on file, nothing beyond the free credit can be billed; I'll confirm on the dashboard in P8
- check Modal's usage page weekly

---

## 3. Repo tree

```
./ (quotedesk)
  PLAN.md  README.md  .env.example  .gitignore  requirements-dev.txt  pytest.ini
  docs/            ARCHITECTURE.md  DECISIONS.md  EVAL_REPORT.md  LEARNING.md
  data/
    catalog.json  customers.json  orders.json  equipment.json
    generated/     scenarios.jsonl  emails.jsonl  verified.jsonl  verify_report.json  cost_log.jsonl  pilot_report.json  cache/ (gitignored)
    splits/        train.jsonl  val.jsonl  exam.jsonl  exam_hard.jsonl  fewshot.jsonl  exam_hashes.json  split_report.json
    kaggle_bundle/ (gitignored; zipped for upload)
  datagen/
    config.py  llm_client.py  world_vocab.py  build_world.py  sample_scenarios.py
    write_emails.py  verify.py  pilot.py  split_export.py  exam_hard.py  make_bundle.py
    tests/
  eval/
    evallib/       schema.py  prompt.py  system_prompt.txt  normalize.py  metrics.py  pricing.json  runner.py
    run_eval.py    reports/<timestamp>/*.json   tests/
  training/        finetune_gemma_lora.ipynb  kernel-metadata.json  README_MANUAL.md
  backend/         modal_app.py  Dockerfile (portable fallback)  requirements.txt
                   app/{main.py, config.py, harness/, models/, tools/, retrain/, db/, prompts/, api/, samples/}  alembic/  tests/
  frontend/        (Next.js App Router)
  scripts/         warmup.sh  seed_demo_corrections.py (v1.1)
  tests/           test_no_exam_leakage.py  test_no_real_brands.py  test_no_secrets.py
```

---

## 4. Environment variables (`.env.example`)

| Var | Used by | Default / example | Notes |
|---|---|---|---|
| `LLM_PROVIDER` | datagen, backend, eval | `kie` | `kie` or `google` |
| `KIE_API_KEY` | datagen, backend, eval | (secret) | kie.ai/api-key |
| `KIE_BASE_URL` | same | `https://api.kie.ai` | |
| `GEMINI_API_KEY` | same | (empty) | only if `LLM_PROVIDER=google` (free AI Studio key) |
| `GEMINI_MODEL` | teacher (backend + baselines) | `gemini-3-8-flash` | provider-specific ID (`gemini-3.8-flash` on Google) |
| `GEMINI_DATAGEN_MODEL` | email writer | `gemini-3-8-flash` | |
| `GEMINI_VERIFY_MODEL` | verifier | `gemini-3-7-flash` | |
| `GEMINI_THINKING_LEVEL` | all Gemini calls | `low` | |
| `LLM_MAX_CONCURRENCY` / `LLM_MIN_INTERVAL_S` | datagen/eval | `4` / `0.6` | KIE limit 20 req / 10 s; for free Google, use `1` / `6` |
| `DATAGEN_BATCH_SIZE` / `DATAGEN_SEED` / `DATAGEN_MAX_CREDITS` | datagen | `5` / `42` / set after pilot | hard stop on spend |
| `HF_TOKEN` | Kaggle notebook secret, Modal secret | (secret) | write scope |
| `HF_MODEL_REPO` | notebook, backend | `<you>/quotedesk-student` | |
| `STUDENT_BASE_MODEL` | backend | `google/gemma-3-270m-it` | |
| `STUDENT_ADAPTER_REVISION` | backend | (empty = teacher-only mode) | e.g. `v1` |
| `HF_HOME` | backend on Modal | `/cache/hf` | inside the Modal Volume |
| `DATABASE_URL` | backend | `sqlite:///./quotedesk.db` | Neon: `postgresql+psycopg://...?sslmode=require` |
| `ADMIN_TOKEN` | backend | (secret) | `python -c "import secrets;print(secrets.token_urlsafe(32))"` |
| `ROUTER_CONFIDENCE_THRESHOLD` | backend | set in P4 from the sweep | never guessed |
| `TEACHER_LIVE_MODE` | backend | `admin_only` | `off` / `admin_only` / `all` |
| `MAX_EMAIL_CHARS` / `RATE_LIMIT` / `REQUEST_TIMEOUT_S` / `MAX_COST_PER_REQUEST_USD` | backend | `6000` / `10/minute` / `30` / `0.01` | |
| `ALLOWED_ORIGINS` | backend | `http://localhost:3000` (+ Vercel URL) | |
| `NEXT_PUBLIC_API_BASE_URL` | frontend | `http://localhost:8000` | prod: `https://<workspace>--quotedesk-web.modal.run` |
| `RETRAIN_THRESHOLD` / `PROMOTION_MARGIN` | backend (v1.1) | `20` / `0.0` | |
| `AUTO_RETRAIN_ENABLED` | backend (v1.2) | `false` | |
| `KAGGLE_API_TOKEN` (or `KAGGLE_USERNAME` + `KAGGLE_KEY`), `KAGGLE_DATASET_SLUG`, `KAGGLE_KERNEL_SLUG` | v1.2 only | (secret) | only if v1.2 picks the Kaggle path |
| *Modal auth* | local deploy only | n/a | **not in .env**: `modal setup` writes `~/.modal.toml` |

Production secrets live in the Modal secret `quotedesk-secrets` (KIE_API_KEY, HF_TOKEN, DATABASE_URL, ADMIN_TOKEN, …) and in Vercel env vars. They are never in the repo.

---

## 5. Accounts and keys checklist (MANUAL (me)). All free, no card.

- [x] **KIE.ai**: key created. MANUAL (me), later: rotate the key before the repo goes public (it was pasted in chat); optionally use the key's IP allowlist.
- [ ] **Hugging Face** (hf.co/join)
  1. Settings → Access Tokens → *Create new token* → fine-grained, write access to your namespace → `HF_TOKEN`.
  2. Open https://huggingface.co/google/gemma-3-270m-it → *Acknowledge license*.
  3. *New model* → `quotedesk-student` → `HF_MODEL_REPO=<you>/quotedesk-student`.
- [ ] **Kaggle** (kaggle.com)
  1. Settings → *Phone verification* (needed for GPU + internet in notebooks).
  2. In the notebook editor: Add-ons → Secrets → add `HF_TOKEN`.
  3. (v1.2 only) Settings → API → *Create New Token*.
- [ ] **Modal** (modal.com, Starter, no card; needed at P8)
  1. Sign up with GitHub or Google. Confirm the plan shows **Starter, $30/month credits**, and **don't add a card**.
  2. Locally: `pip install modal==1.6.0` → `modal setup` (browser login, writes `~/.modal.toml`).
  3. Dashboard → Secrets → *Create* → custom → name `quotedesk-secrets`, keys `KIE_API_KEY`, `HF_TOKEN`, `DATABASE_URL`, `ADMIN_TOKEN`, `ALLOWED_ORIGINS` (I'll give you the exact list at P8).
  4. Note your workspace name (it's part of the endpoint URL).
- [ ] **Neon** (neon.com, Free): New project `quotedesk` → *Connect* → pooled connection string → `DATABASE_URL`. Needed at P8; SQLite until then.
- [ ] **GitHub**: create an empty public repo `quotedesk`. I've run `git init` locally; you add the remote.
- [ ] **Vercel Hobby** (P8): sign in with GitHub → *Add New Project* → import → Root Directory `frontend` → env `NEXT_PUBLIC_API_BASE_URL`.
- [ ] **ADMIN_TOKEN**: generate with the one-liner in section 4.
- [ ] Only if KIE credits run short (and you approve): **Google AI Studio** free key → `GEMINI_API_KEY`, with no billing enabled.

---

## 6. Dataset design (the fast-track deliverable)

### 6.1 World (`build_world.py`, pure code, seeded, byte-identical on rerun)
- **catalog.json**: 200 SKUs, 20 in each of 10 categories: valves, fittings, contactors, capacitors, filters, motors, thermostats, belts, fuses, sealants.
  - SKU pattern `NB-<CAT>-<4 digits>`.
  - Typed `attributes` per category.
  - 3–6 `aliases` generated from attributes.
  - `unit`, `list_price`, and `stock_qty`, where about 10% are 0 and about 15% are low.
  - `compatible_equipment`.
- **equipment.json**: about 40 fictional equipment models from 8 invented brands. Each maps to compatible parts.
- **customers.json**: 20 customers on the `.example` TLD. Tiers A 15%, B 10%, C 5%. Volume breaks: 10+ gives an extra 3%, 50+ an extra 7%.
- **orders.json**: 3–10 past orders per customer.

### 6.2 Scenarios (`sample_scenarios.py`, pure code): the ground truth
- **Intent mix:** quote_request 65%, product_question 10%, order_status 10%, return_request 8%, other 7%.
- **Item reference types:** sku 20%, alias 30%, description 22%, compatibility 13% (about 25% of those without a model), previous_order 10%, vague 5%.
- **Quantity:** missing for about 12% of items. Otherwise digits 85% or number words 15%. An explicit unit word is present for about 50% of items.
- **Urgency and dates:** urgency is expressed with a cue phrase. `needed_by` is a sampled phrase that the email must contain verbatim.
- **Noise flags:** typos 0–3, abbreviations, shorthand, forwarded thread, signature junk, mixed units, all-lowercase, embedded instruction (about 3%).
- **Difficulty:** easy / medium / hard. Generate about 1,800 scenarios.

### 6.3 Labeling rules (target JSON; enforced in `evallib/schema.py`)
- **Serialization:** compact JSON, keys in schema order.
- **`intent`:** one of 5 values. A mixed-intent email is `quote_request` if any item is requested for quote.
- **`urgency`:** `high` for ASAP / urgent / emergency / unit down, or needed within 3 days. `low` for no rush / whenever. Otherwise `normal`.
- **`needed_by`:** the exact phrase, or `null`.
- **`items[].description`:** the exact email span (returned by the writer, verified as a substring).
- **`quantity`:** integer (number words converted) or `null`.
- **`unit`:** canonical `each|box|case|roll|pack|ft|tube|pair` if an explicit unit word is present, else `null`.
- **`part_number`:** the SKU exactly as written, or `null`.
- **`compatible_with`:** the equipment model exactly as written, or `null`.
- **`reference`:** `"previous_order"` or `null`.
- **`missing_info`**, in item order:
  - `quantity: <description>` for quote or return items with no quantity, unless `reference` is `previous_order`
  - `equipment_model: <description>`
  - `size_or_spec: <description>`
  - `order_number` for order_status emails with no order reference
- **Other rules:** `product_question` items have quantity `null`. `order_status` and `other` have `items: []`.
- The student never outputs prices, and never outputs SKUs that aren't in the email.

### 6.4 Write (`write_emails.py`, KIE `gemini-3-8-flash`)
- 5 scenarios per request, `responseSchema` output with body and exact spans. The prompt forbids missing or invented items and forbids altering SKU or equipment characters.
- SSE streaming, concurrency 4, pacing, backoff on 429/5xx/timeouts, content-hash cache, resume from checkpoint.
- Per-call cost log with tokens and credits.
- **Pilot: 20 scenarios** (writer + verifier). Report: credits per email, remaining balance, projected total for the full run **plus** later eval usage (P2b + P4 + sample cache), and 5 sample emails. Then stop for your OK.

### 6.5 Verify (`verify.py`)
- **Code checks (hard):**
  - spans are substrings of the email
  - the SKU appears when referenced
  - a quantity is present when not missing, absent when missing
  - the equipment model appears
  - the needed_by phrase is present
  - no stray catalog SKUs
  - length is within bounds
- **Independent extraction (hard):** `gemini-3-7-flash` sees only the email (10 per request). It must agree on intent, item count, each quantity, part numbers, and compatible_with.
- **Soft fields** are logged, not dropped.
- Output: `verify_report.json` with the drop rate and reasons.

### 6.6 Split and export (`split_export.py`)
- Near-duplicate removal with rapidfuzz `ratio > 90`.
- Stratified split by (intent, difficulty): **about 1,200 train / 150 val / 150 exam**.
- **exam_hard (30):** written by hand in `exam_hard.py`, with no LLM involved. **MANUAL (me): review.**
- `exam_hashes.json` plus `tests/test_no_exam_leakage.py`.
- Chat JSONL `{"messages":[system, user, assistant]}` with the system prompt from `evallib/system_prompt.txt`.

### 6.7 Kaggle bundle (`make_bundle.py`)
- The splits + `fewshot.jsonl` + `evallib/` + `dataset-metadata.json` + `manifest.json` (counts, sha256, git SHA) → `quotedesk-data.zip`.

---

## 7. Phases

Legend: `[ ]` todo · `[x]` done · **MANUAL (me)** = you do it. Every phase ends with tests, ticked boxes, a summary, and a new **docs/LEARNING.md** section.

### v1

#### P0: Setup (≈0.5 h)
- [x] `git init` (no commits unless you ask), `.gitignore`, `.env.example`, `requirements-dev.txt`, `pytest.ini`, README stub
- [x] `.venv` + dev deps
- [x] `tests/test_no_secrets.py`
- [x] docs/LEARNING.md (P0 section)
- **Accept:** `pytest` green; `.env` untracked; `.env.example` lists every section-4 var.

#### P1: World + dataset (≈5 h build; datagen wall-clock ≈1–2 h after pilot approval)
Part A (now, up to the pilot):
- [x] `world_vocab.py`, `build_world.py` → catalog/equipment/customers/orders + determinism test
- [x] `evallib/schema.py`, `system_prompt.txt`, `prompt.py`, `normalize.py` + tests
- [x] `sample_scenarios.py` + distribution/label tests
- [x] `llm_client.py` (KIE SSE + google-genai, pydantic → OpenAPI `responseSchema`, pacing, retry, cache, cost log, credit cap, balance check)
- [x] `write_emails.py`, `verify.py`, `pilot.py` → **20-email pilot → `pilot_report.json` → STOP for your OK**
- [x] `tests/test_no_real_brands.py`

Part B (after your OK):
- [x] Full write + verify run (or switch provider, per the rule in section 0)
- [x] `exam_hard.py` (30 hand-written) → **MANUAL (me): review**
- [x] `split_export.py`, `tests/test_no_exam_leakage.py`, `make_bundle.py` → zip
- **Accept:**
  - splits of about 1,200 / 150 / 150 / 30 in `split_report.json`
  - drop rate + reasons logged
  - leakage test passes
  - every target validates and every span is verbatim
  - the world build is deterministic
  - no real-brand hits

#### P2a: Notebook + eval library (≈3 h)
- [x] `evallib/metrics.py`:
  - intent accuracy
  - JSON validity
  - item P/R/F1 (Hungarian match on description similarity + quantity)
  - quantity accuracy
  - missing-info F1
  - exact match
  - latency p50/p95
  - escalation rate
  - cost per 1k
- [x] Unit tests
- [x] `evallib/runner.py`
- [x] `training/finetune_gemma_lora.ipynb`:
  - parameters cell: r 16, alpha 32, lr 2e-4, 3 epochs, all linear targets, seed 3407
  - Kaggle/Colab path detection
  - Unsloth `FastModel` + `gemma3` chat template + `train_on_responses_only`
  - per-epoch eval loss + a generation-metrics callback on 50 val emails
  - exam + exam_hard → `eval.json`
  - `loss_curve.png`, `run_config.json`
  - optional base-baseline cell → `base_eval.json`
  - optional HF push with tag `vN` + NOTICE/GEMMA_TERMS
  - corrections-aware
- [x] `kernel-metadata.json` (T4, GPU on, internet on)
- [x] `training/README_MANUAL.md` (click-by-click)
- **Accept:** evallib tests pass; the notebook runs top to bottom on Kaggle T4, which you confirm.
- **MANUAL (me):**
  1. Upload the zip as a Kaggle dataset.
  2. Import the notebook.
  3. Set T4 and internet on, and add the `HF_TOKEN` secret.
  4. Run all (≈20–40 min).
  5. Send me the HF repo ID + tag, `eval.json`, and `base_eval.json`.

#### P2b: Teacher baseline (≈1.5 h; runs while you train)
- [ ] `eval/run_eval.py --system teacher` on exam + exam_hard via KIE → `eval/reports/<ts>/teacher.json` (cost at Google's published price and KIE credits both logged, labelled)

#### P3: Backend harness + tools + tests (≈7 h; teacher-only mode until the adapter exists)
- [x] FastAPI, config, SQLAlchemy models (all 9 tables), Alembic
- [x] 6 tools, pydantic in and out, unit tested; CONFIDENT/NEEDS_REVIEW rule
- [x] Harness state machine with traced spans:
  - GUARD
  - EXTRACT → VALIDATE → REPAIR
  - ESCALATE (`TEACHER_LIVE_MODE=admin_only`: public requests get a "would escalate" span + review flag)
  - RESOLVE → DRAFT → PENDING_APPROVAL
- [x] Budgets: 30 s total, cost cap, graceful degradation
- [x] SSE `POST /api/quotes/process` and the section-16 v1 endpoints (not models/retrain), slowapi, CORS
- [x] Cached teacher outputs for the 8 samples, labelled `cached`
- [x] Tests: tools, validation, router branches, guard, SSE order, price-only-from-tools invariant
- **Accept:** `pytest backend` green; 8 samples end-to-end locally; every quote has a trace.

#### P4: Student integration + router calibration + full eval (≈3 h + run time)
- [x] CPU loader (base + adapter from an HF tag, merged), greedy decoding, token cap. Confidence = mean token logprob combined with validity and completeness.
- [ ] Threshold sweep on **val** → chart + JSON → `ROUTER_CONFIDENCE_THRESHOLD`
- [ ] Full eval: base, tuned, teacher, harness, plus end-to-end SKU resolution → `eval/reports/<ts>/`, generated `docs/EVAL_REPORT.md`
- **Accept:** 4 systems × all metrics; threshold chosen from data; CPU p95 recorded.

#### P5: Frontend (≈8 h)
- [x] Next 16 + TS + Tailwind 4 + shadcn/ui, light/dark theme, synthetic-data banner, cold-start "waking up the server" state with auto-retry
- [x] `/`, `/playground`, `/traces` (+ waterfall), `/results` (reads eval JSON only), `/how-it-works` (Mermaid + FAQ). `/models` moves to v1.1.
- **Accept:** pages work against the local backend; the 8 samples work; a grep test shows no hardcoded metrics.

#### P8: Deploy on Modal + Vercel + README + smoke (≈4 h)
- [x] `backend/modal_app.py`:
  - image from `backend/requirements.txt` (CPU torch)
  - Volume `quotedesk-hf-cache` at `/cache` (`HF_HOME=/cache/hf`)
  - Secret `quotedesk-secrets`
  - `@app.cls(cpu=2.0, memory=4096, scaledown_window=300, min_containers=0, max_containers=1, enable_memory_snapshot=True)` with `@modal.enter(snap=True)` model load and `@modal.concurrent(max_inputs=8)` + `@modal.asgi_app()`
- [x] One-off `modal run backend/modal_app.py::prefetch` to fill the volume with base + adapter weights
- [ ] `modal deploy backend/modal_app.py` → URL `https://<workspace>--quotedesk-web.modal.run`; CORS = the Vercel URL; Neon `DATABASE_URL` + `alembic upgrade head`
- [ ] Measure cold start (volume + snapshot) and record it in the README
- [ ] Vercel project (root `frontend`, `NEXT_PUBLIC_API_BASE_URL` = Modal URL)
- [ ] `scripts/warmup.sh`: hits `/api/health`, then processes one cached sample so the model is warm; run it before sharing the link
- [ ] Smoke test: 8 samples in prod, including after a forced cold start (`modal app stop` + first request)
- [ ] Budget check: record Modal usage after smoke tests; confirm no card is on file
- [ ] README: problem, live link, video placeholder, diagram, results table **generated from the eval JSON**, fine-tuning + harness write-ups, limitations, next steps, reproduce-from-scratch, ZeroGPU backup note
- **Accept:** v1 definition of done:
  - the live link works on all 8 samples, including after a cold start
  - Results shows real numbers for 4 systems
  - every quote has a trace
  - no secrets in the repo
  - tests pass
  - the README is reproducible

### v1.1

#### P6-manual: Corrections + manual retrain + safety gate + /models (≈6 h)
- [x] Decision endpoint; diff classifier (EXTRACTION / RESOLUTION / BUSINESS); public = sandbox; only admin corrections count
- [x] Corrections counter vs `RETRAIN_THRESHOLD`
- [x] "Prepare retrain" builds the zip (train + corrections, deduped, exam-overlap assert) + instructions
- [x] `POST /api/models/register` (admin): upload eval.json + HF tag → gate (item-F1 ≥ current + margin, validity ≥ current, no intent drop > 2 pts) → PROMOTED (hot-swap) or REJECTED with a stored reason
- [x] Rollback
- [x] `/models` page: live version, progress bar, timeline, rollback (admin token)
- [x] `scripts/seed_demo_corrections.py`
- **Accept:** gate tests cover promote and reject; one real v2 run shown on /models (promoted or rejected, with reasons).

### v1.2
- [ ] **P6-auto:** automatic trigger. Compare **Modal GPU** (Modal cron + T4 function, within $30) vs Kaggle API; pick one and write it up in DECISIONS; add pause/resume.
- [x] **P7:** MCP server (read-only tools, `mcp` SDK streamable HTTP at `/mcp`) + README instructions.

---

## 8. Risks and fallbacks

| Risk | Fallback |
|---|---|
| KIE credits insufficient for the full datagen | The pilot projects the total. If it's over budget, **ask you**, then `LLM_PROVIDER=google` (free AI Studio key, `LLM_MAX_CONCURRENCY=1`, slower pacing, resume across days). |
| KIE latency 7–50 s; outages | Datagen/eval are offline with concurrency + resume. Runtime teacher is admin_only, and the samples are cached. |
| KIE drops `responseSchema` pass-through | Pydantic validation, one repair retry, then drop + log; provider switch. |
| Modal free credits burn | `max_containers=1`, no keep-warm, `scaledown_window=300`, rate limits, weekly usage check. Estimate ≈ $7/month vs $30. No card on file, so no overage billing. |
| Modal cold start (torch CPU image + model) | Weights cached in a Volume; `@modal.enter(snap=True)` memory snapshot (3–10× per docs); friendly waking UI; `warmup.sh` before sharing. |
| Modal 150 s HTTP cap | Our request budget is 30 s; SSE streams finish well within it. |
| Modal Starter terms change or account issue | **Backup (documented only, not built):** a free HF ZeroGPU Gradio Space (free account > 30 days old, max 2 Spaces). Either (a) the whole FastAPI app is mounted into a Gradio app via `gr.mount_gradio_app` with student inference inside `@spaces.GPU(duration=20)`, or (b) a student-only Gradio endpoint called with `gradio_client` from another host. Caveats: Gradio SDK only; the per-visitor daily GPU quota (2 min anonymous / 5 min free) limits demo volume; Python 3.10/3.12 only; compatibility untested. |
| Neon scale-to-zero (5 min) | First query after idle takes about 1 s; hidden behind the waking state. |
| Gemini "competing models" clause | Labels come from code; the model is narrow (D1). |
| Verifier bias toward easy emails | Hard/soft field split; hand-written exam_hard; drop reasons published. |
| 270M accuracy too low | More epochs, rank 32, targeted data; then Gemma 3 1B if CPU p95 < ~15 s (also re-check the Modal cost). |
| CPU latency (2 cores) | Merged LoRA, greedy decoding, compact JSON, token cap, optional int8 dynamic quantization. |
| Unsloth/transformers churn on Kaggle | Follow the official notebook's pins on the day; record them; Colab fallback. |
| Next 16 / TS 7 | `create-next-app@16` defaults. |

**Cut order if behind:** v1.2 items first (already deferred) → threshold sweep chart. **Never cut:** the eval table, the trace view, human approval.

---

## 9. Decisions log (answers to the plan questions)
- Q1 host → **Modal Starter** (no HF PRO, zero spend). ZeroGPU is the documented backup.
- Q2 → **`TEACHER_LIVE_MODE=admin_only`**.
- Q3 → **manual retrain + register + gate in v1.1**; automatic retrain (Modal GPU vs Kaggle API) in **v1.2**.
