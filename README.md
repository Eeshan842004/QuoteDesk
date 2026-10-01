# QuoteDesk

**Messy customer emails to draft quotes in seconds.**

> Demo with synthetic data and a fictional company ("Northbeam Industrial Supply"). All brands, products, customers and emails are invented. No real email is ever sent.

- **Live demo:** _add your Vercel URL here after deploy_
- **2-minute video:** _placeholder_
- **Model card:** `https://huggingface.co/<you>/quotedesk-student` (after training)

QuoteDesk is a portfolio project that shows two things end to end:

1. **Fine-tuning a small language model by teacher-student distillation.** Gemma 3 270M with LoRA, trained on a *ground-truth-first* synthetic dataset where the labels come from code, not from the teacher.
2. **A production-style agent harness around it.** Routing to a large model when the small one is unsure, validation and repair, deterministic tools for catalog/stock/pricing, full tracing, human approval, and a retraining loop with a safety gate.

## The problem

An industrial parts distributor receives quote requests as messy emails: typos, shorthand, "same as last time", "whatever fits my unit", missing quantities. A person has to decode each one, find the parts, check stock, apply the customer's pricing and write a quote. That takes days and loses sales.

QuoteDesk uses three roles:

| Role | Who | Job |
|---|---|---|
| Junior clerk | Fine-tuned Gemma 3 270M (CPU) | Reads most emails, fast and cheap |
| Senior expert | Gemini 3.8 Flash | Called only when the clerk is unsure |
| Manager | A human | Approves every quote. Admin corrections become training data |

## Architecture

```
[Vercel: Next.js 16 frontend] --HTTPS + SSE--> [Modal: FastAPI (CPU, scale-to-zero)]
                                                 |-- harness: GUARD > EXTRACT > VALIDATE > [REPAIR] > ROUTE > [ESCALATE] > RESOLVE > DRAFT > approval
                                                 |-- student: Gemma 3 270M + LoRA (weights from HF Hub, cached in a Modal Volume)
                                                 |-- teacher: Gemini 3.8 Flash (via KIE.ai, SSE)
                                                 |-- tools: catalog search, line resolution, compatibility, order history, stock, pricing
                                                 |-- MCP server at /mcp (read-only tools)
                                                 '-- Neon Postgres (SQLite locally)
Offline: datagen (code ground truth -> Gemini writes -> Gemini verifies) -> Kaggle notebook (free T4) -> HF Hub tag
```

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Decisions and trade-offs: [docs/DECISIONS.md](docs/DECISIONS.md) · Plain-English notes: [docs/LEARNING.md](docs/LEARNING.md)

## Results

Every number is generated from `eval/reports/2026-09-30/summary.json` by `python eval/run_eval.py summarize` into **[docs/EVAL_REPORT.md](docs/EVAL_REPORT.md)**, and the Results page reads the same file. The exam (150 emails) and hard exam (30 hand-written emails) are sealed: hashed and checked against every training file. Model: Gemma 3 270M + LoRA (r=16), trained 3 epochs on 1,334 synthetic emails in 9.4 minutes on a free Kaggle T4. Adapter: [Eeshan082004/quotedesk-student](https://huggingface.co/Eeshan082004/quotedesk-student).

**Exam (150 emails)**

| System | Intent | Valid JSON | Item F1 | Missing-info F1 | Exact match | SKU resolution | p50 latency | Cost / 1k emails |
|---|---|---|---|---|---|---|---|---|
| Base Gemma 3 270M, 3-shot | 50.7% | 66.0% | 17.5% | 0.0% | 0.7% | n/a | 1.3 s (GPU) | n/a |
| **Fine-tuned Gemma 3 270M** (CPU) | 98.0% | 98.7% | 93.1% | 16.0% | 58.7% | 93.5% | 7.4 s | $0.35 (estimate) |
| Fine-tuned + rule fixes (CPU) | 98.0% | 98.7% | 93.1% | 66.7% | 71.3% | 93.5% | 7.4 s | $0.35 (estimate) |
| Gemini 3.8 Flash (teacher) | 97.3% | 100.0% | 97.0% | 91.4% | 54.0% | 95.1% | 7.9 s via KIE | $1.06 (measured tokens x published price) |
| **Full harness** (student + router + teacher) | **99.3%** | 100.0% | 96.2% | 74.3% | 74.0% | 95.1% | 8.4 s | $0.45 |

**Hard exam (30 emails: prompt injections, forwarded threads, mangled SKUs, multi-intent)**

| System | Intent | Valid JSON | Item F1 | SKU resolution | Escalated |
|---|---|---|---|---|---|
| Base Gemma 3 270M, 3-shot | 36.7% | 46.7% | 27.6% | n/a | n/a |
| Fine-tuned Gemma 3 270M (CPU) | 60.0% | 66.7% | 69.9% | 83.3% | n/a |
| Gemini 3.8 Flash (teacher) | 100.0% | 100.0% | 100.0% | 100.0% | n/a |
| **Full harness** | 93.3% | 100.0% | 91.8% | 97.2% | 43.3% |

What the numbers say:
- **Fine-tuning works:** item F1 goes from 17.5% to 93.1% on the same 270M model, and valid JSON from 66% to 98.7%.
- **The harness is the point:** escalating the 9% of emails the student is unsure about (router threshold 0.66, chosen on validation data) lifts item F1 to 96.2% at 43% of the teacher's cost. On the hard exam, escalation lifts it from 69.9% to 91.8%.
- **The teacher is not a perfect oracle:** on the easy exam its whole-email exact match (54%) is below the harness (74%), mostly because it words descriptions differently from the labels.
- **Costs:** teacher cost uses Google's published paid price on measured tokens. Student cost is an estimate (CPU seconds x Modal container price).

## How the dataset was built (ground truth first)

1. **World** (`datagen/build_world.py`): 200 SKUs across 10 categories, 40 fictional equipment models with compatibility tables, 20 customers with pricing tiers, and order histories. Seeded and byte-deterministic.
2. **Scenarios** (`datagen/sample_scenarios.py`): pure code samples a customer, intent, 1–5 items (referenced by SKU, alias, description, equipment compatibility, previous order, or vaguely), quantities (or deliberately missing), urgency, deadline and a noise profile. **The scenario is the label.**
3. **Writing** (`datagen/write_emails.py`): Gemini 3.8 Flash writes one messy email per scenario and returns the exact text spans it used.
4. **Verification** (`datagen/verify.py`): code checks that every span, SKU, model number, quantity and deadline appears verbatim, with no stray parts. A *different* model (Gemini 3.7 Flash) then extracts independently and must agree on the hard fields. Mismatches are dropped and logged.
5. **Split** (`datagen/split_export.py`): near-duplicate removal, stratified train / val / exam, plus 30 hand-written hard emails (prompt injections, forwarded threads, mangled SKUs...). Exam emails are hashed, and a test fails if any appears in training data.

## How fine-tuning works

`training/finetune_gemma_lora.ipynb` runs on Kaggle's free T4 (or Colab):
- Unsloth + TRL
- LoRA rank 16 on all linear layers, lr 2e-4, 3 epochs
- loss on the assistant JSON only, with the same system prompt used at inference (`eval/evallib/system_prompt.txt`)

It evaluates on the exam with the shared eval library and pushes the adapter to the HF Hub with a version tag. Click-by-click: [training/README_MANUAL.md](training/README_MANUAL.md).

## How the harness works

- **Guard:** length limit, and prompt-injection heuristics that flag, never block. Email text is always treated as data.
- **Extract → Validate → Repair:**
  1. The student produces JSON.
  2. Pydantic plus semantic checks validate it.
  3. If invalid, there is one retry that includes the error.
- **Route:** confidence = exp(mean token log-prob) × validity × completeness. The threshold is chosen from a sweep on the validation split (`eval/run_eval.py calibrate`).
- **Escalate:** at most one teacher call, within a 30 s budget and a per-request cost cap. If the teacher fails, the result degrades gracefully to "student result, flagged". Public visitors never trigger live teacher calls (`TEACHER_LIVE_MODE=admin_only`). The 8 demo samples use cached teacher outputs, labelled as cached.
- **Resolve:** deterministic tools give the top 3 candidates per line. A line is CONFIDENT only if the top score is ≥ 0.9, it leads the next candidate by ≥ 0.1, the quantity is present and stock is sufficient.
- **Prices come only from the pricing tool** (tier discount + volume breaks). No model ever writes a price.
- **Human approval:** per line, the reviewer can accept, pick another candidate, edit the quantity, remove, or add a line. Each change is classified as EXTRACTION, RESOLUTION or BUSINESS. Only admin EXTRACTION corrections become training data, so public visitors can't poison it.
- **Correct result (admin):** when the model misreads an email, the admin opens **Correct result** in the Playground, edits what the model extracted (intent, urgency, deadline, each item's text, quantity, unit, part number, equipment model, "too vague" / "equipment model missing" flags) and saves. The email plus the corrected extraction becomes one training example, the quote is redrafted from the corrected result, and the counter moves (**Corrections 1/20**). Rules: text must be copied exactly from the email; saving the same quote again replaces its example; the same email counts once; sealed exam emails are refused; **Reject alone is never a correction**. At 20 corrections the existing retraining workflow prepares the next version's bundle (base training data + corrections, exam overlap refused).
- **Retraining (v1.1 manual, v1.2 auto):**
  1. Bundle base train data + corrections (exam overlap asserted).
  2. Train on Kaggle.
  3. Run the gate: exam item F1 ≥ live + margin, JSON validity ≥ live, no intent class drops more than 2 points.
  4. Promote with a hot swap, or reject and store the reason.

## MCP server

The backend mounts a read-only MCP server (official MCP Python SDK 2.x, streamable HTTP) at **`/mcp/`**. It exposes `search_catalog`, `resolve_line_item`, `get_compatible_parts`, `check_stock` and `get_price`.

Connect from an MCP client that supports streamable HTTP, for example with this config:
```json
{ "mcpServers": { "quotedesk": { "type": "http", "url": "https://<workspace>--quotedesk-web.modal.run/mcp/" } } }
```
Locally, use `http://localhost:8000/mcp/`.

## Reproduce from scratch

Everything runs on free tiers with no card. The one exception is the LLM calls for datagen, which use KIE.ai credits, or a free Google AI Studio key with `LLM_PROVIDER=google`.

```bash
# 0) setup
python -m venv .venv && .venv/Scripts/activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu && pip install -r backend/requirements.txt
cp .env.example .env                                    # fill KIE_API_KEY (or GEMINI_API_KEY + LLM_PROVIDER=google)

# 1) data
python -m datagen.build_world
python -m datagen.sample_scenarios
python -m datagen.pilot                                  # 20-email pilot + credit projection
python -m datagen.write_emails && python -m datagen.verify
python -m datagen.exam_hard && python -m datagen.split_export
python -m datagen.make_bundle                            # -> data/quotedesk-data.zip for Kaggle
pytest                                                   # includes the exam-leakage and no-real-brands tests

# 2) train on Kaggle: follow training/README_MANUAL.md, then
python eval/run_eval.py import-notebook --from <downloaded outputs>

# 3) evaluate
python eval/run_eval.py teacher                          # exam + exam_hard + val via Gemini
python eval/run_eval.py student --adapter <you>/quotedesk-student@v1   # CPU latency + accuracy
python eval/run_eval.py calibrate                        # -> ROUTER_CONFIDENCE_THRESHOLD
python eval/run_eval.py harness
python eval/run_eval.py summarize                        # -> summary.json + docs/EVAL_REPORT.md

# 4) run locally
python scripts/cache_sample_teacher.py                   # cached expert answers for the 8 demo emails
cd backend && uvicorn app.main:app --port 8000           # API + /docs + /mcp/
cd frontend && npm install && npm run dev                # http://localhost:3000
```

Deployment (Modal + Neon + Vercel): see [docs/DEPLOY.md](docs/DEPLOY.md).

## Tests

```bash
pytest                          # datagen, eval library, leakage, secrets, real-brand checks
cd backend && pytest            # tools, guard, router, pipeline (fake models), SSE, decisions, gate, MCP
cd frontend && npm run lint && npm run build
python scripts/smoke_test.py --api <backend url>          # end-to-end against a running backend
```

## Limitations

- The data is synthetic. Real emails have attachments, images, long threads and more languages.
- A 270M model on 2 CPU cores decodes at roughly 10-15 tokens/s, so each email takes about 7 s on the student path (p95 about 22 s for long emails).
- **The student's `missing_info` field is unreliable** (16% F1 raw): it lists "quantity" for items that have one and never emits `order_number`. The harness recomputes the rule-derivable kinds in code (quantity, order_number, equipment_model), which lifts it to 67%. `size_or_spec` is not derived and still has low recall.
- **Confidence is not correctness.** The student was once confidently wrong (confidence 0.97, quote request labelled product question), so the router did not escalate it. Mean token probability catches uncertainty, not confident semantic errors.
- **Weak on inputs the training data barely covers:** on the hard exam the student gets multi-intent emails right 1 of 4 times, and shorthand and mangled SKU formats 1 of 3. It handles prompt injection well (6 of 6 valid JSON), because 3% of training emails contained injected instructions with unchanged labels.
- The hand-written hard exam is only 30 emails, so its percentages move in 3-point steps.
- Teacher latency through the KIE proxy varies widely (seconds to minutes, occasional gateway timeouts). The public demo uses cached teacher results for the samples.
- The injection guard uses heuristics. It flags and never blocks, and prices can't be affected anyway.
- Free hosting sleeps. The first request after idle waits for a cold start (the UI shows a "waking up" state).

## Next steps

- Retrain v2 with targeted data for multi-intent, shorthand and mangled SKUs, and the missing-info field (the admin corrections flow is built for this).
- A learned confidence head, or a calibrated verifier, instead of mean log-probability.
- Alias learning from RESOLUTION feedback.
- Attachment and PDF parsing.
- Multi-language emails.
- Evaluate Gemma 4 E2B on GPU hosting.

## Licenses

- **Code:** MIT (add a LICENSE file if you publish).
- **Student model:** a Model Derivative of Gemma 3, distributed under the [Gemma Terms of Use](https://ai.google.dev/gemma/terms). The HF repo ships a `NOTICE` file and the use restrictions.
- **Data:** synthetic, CC0.
