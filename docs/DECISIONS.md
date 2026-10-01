# Decisions log

Each entry: date, decision, why, source. Not legal advice. These are my reading of public terms for a portfolio project.

---

## D1 (2026-09-30): Gemini API terms and training a student model

**Source:** Gemini API Additional Terms of Service, last modified 2026-03-23 (https://ai.google.dev/gemini-api/terms).

Relevant clauses (quoted):
- "You may not use the Services to develop models that compete with the Services (e.g., Gemini API or Google AI Studio). You also may not attempt to reverse engineer, extract or replicate any component of the Services, including the underlying data or models (e.g., parameter weights)."
- Grounded Results / Search Suggestions may not be used to "train on, or otherwise learn from". **We never use Grounding with Google Search**, so this clause does not apply.
- Unpaid Services: "Google uses the content you submit to the Services and any generated responses to provide, improve, and develop Google products..." and "human reviewers may read, annotate, and process your API input and output."
- "You may use only Paid Services when making API Clients available to users in the European Economic Area, Switzerland, or the United Kingdom."

**Decision:**
1. The student is a narrow, single-task extraction model (messy email to a fixed JSON schema) for a fictional company. It is not a general-purpose model and does not compete with the Gemini API.
2. **Training labels are produced by deterministic code, not by Gemini.** Scenarios (the ground truth) are sampled in pure Python. Gemini only writes the synthetic email *text* (the model input) and runs an independent verification pass. The only Gemini-derived part of a target is `description`, which must be a verbatim substring of the email, checked by code. No free-form Gemini response is used as a training target.
3. Only synthetic data is sent to Gemini. The datagen prompts contain only fictional catalog, customer, and scenario data.
4. Visitor-pasted text is untrusted and may contain real personal data. By default it is **not** forwarded to Gemini (see D5).

**Residual risk:** the "competing models" clause is broad. If this becomes a concern, the fallback is to write emails with an open-weights model instead (e.g. Gemma 4 on Kaggle). The labels do not change, because they come from code.

---

## D2 (2026-09-30): Gemma license

**Source:** Gemma Terms of Use, last modified 2026-04-01 (https://ai.google.dev/gemma/terms). These terms cover Gemma 1 to 3. Gemma 4 is released under Apache 2.0 (https://ai.google.dev/gemma/apache_2).

- Student base = **Gemma 3 270M** (`google/gemma-3-270m-it`, gated on HF; license acceptance required). Our LoRA adapter is a "Model Derivative".
- When distributing a derivative, we must pass on the use restrictions (Section 3.2), include a copy of the Gemma Terms, mark modified files, and ship a `NOTICE` file with the text: "Gemma is provided under and subject to the Gemma Terms of Use found at ai.google.dev/gemma/terms". **Action:** the HF model repo will contain `NOTICE`, `GEMMA_TERMS.md`, and a model card stating the use restrictions.
- The Gemma terms govern Gemma's weights and derivatives. They place no restriction on training Gemma on data written by another model. "Google claims no rights in Outputs you generate using Gemma."
- Gemma 4 would avoid these obligations (Apache 2.0), but its smallest size is E2B, which is too slow for 2-vCPU CPU inference. It stays an option only if we get better hardware.

---

## D3 (2026-09-30): Fictional world guarantees

- All customer and company email domains use the reserved `.example` TLD (RFC 2606).
- Brands, equipment model numbers, and SKUs follow invented patterns (e.g. `NB-VLV-2041`, `KVL-AC36-2`). A test fails if any catalog or generated email contains a name from a denylist of real HVAC, plumbing, and electrical brands. Any remaining resemblance to a real product is unintended.
- Industry-generic size codes (filter `16x25x1`, belt `A36`, fuse class `RK5`) are descriptive standards, not brands, and are allowed.

---

## D4 (2026-09-30): LLM provider is KIE.ai (paid), with Google direct as an optional fallback

The user bought KIE.ai credits. KIE is a third-party reseller/proxy for Gemini models. Docs: https://docs.kie.ai/market/gemini/gemini-3-8-flash.md

Probed live on 2026-09-30 with tiny requests:
| Check | Result |
|---|---|
| Endpoint | `POST https://api.kie.ai/gemini/v1/models/gemini-3-8-flash:streamGenerateContent`, `Authorization: Bearer` |
| Non-streaming (`"stream": false`) | Hung past 120s. **Use streaming only (SSE).** |
| `generationConfig.responseSchema` (OpenAPI subset: `OBJECT`/`STRING`/`nullable`) | **Honored** (exact keys returned) |
| `generationConfig.responseJsonSchema` | **Silently ignored** (model invented its own keys). Do not use. |
| `systemInstruction` | Honored |
| `nullable: true` in `responseSchema` | **Ignored**: the model is forced to emit `""` or an enum value instead of null (all items got `reference: "previous_order"`) |
| `anyOf` with a `NULL` type | **Breaks** (HTTP 524 or empty `{}` objects) |
| JSON mode without schema + explicit format in the prompt | Correct nulls. **Used for every output that has nullable fields**; `responseSchema` only for null-free outputs (the email writer) |
| `thinkingConfig.thinkingLevel` | Accepted (`low`); docs list low/high |
| Usage | `usageMetadata` {promptTokenCount, candidatesTokenCount, thoughtsTokenCount?, totalTokenCount} + `credits_consumed` |
| Latency (trivial prompt) | time-to-first-token 7.5s / 19.7s / 50.7s: **high and variable** |
| Rate limit (docs) | 20 new requests per 10 seconds; 429 when exceeded |

Consequences:
- The LLM client speaks Gemini REST over SSE via httpx, behind a small provider interface. `LLM_PROVIDER=kie` is the default. `LLM_PROVIDER=google` uses the official `google-genai` SDK (2.25.0) with `GEMINI_API_KEY` if we ever add a direct key.
- Model IDs differ by provider: KIE `gemini-3-8-flash`, Google `gemini-3.8-flash`.
- **Teacher cost in the Results page** = measured tokens × Google's published paid-tier price for `gemini-3.8-flash` ($0.75 in / $3.75 out per 1M, thinking billed as output, valid through 2026-12-31, https://ai.google.dev/gemini-api/docs/pricing), labelled that way. KIE credits actually spent are logged separately.
- **Teacher latency** is measured through the KIE proxy and labelled "via KIE proxy".
- Pilot (2026-09-30): 20 emails, 10% drop rate, 0.058 credits/email to write + 0.035 to verify, 0.08 per single teacher call. Projected total for datagen + all eval runs: about 260 credits with a 25% margin, against a 477-credit balance. Full run approved by the budget rule and started with a hard cap `DATAGEN_MAX_CREDITS=330`.
- Security: the key lives only in `.env` (gitignored) and host secret settings. It was shared in chat, so rotate it before the repo goes public. KIE's per-key IP allowlist can restrict it to the backend host.
- The agent skill (`npx skills add https://kie.ai`) is not needed. The pipeline code calls the REST endpoint directly.

---

## D5 (2026-09-30): Teacher calls from the public demo (DECIDED: admin_only)

`TEACHER_LIVE_MODE=admin_only`:
- The 8 sample emails use cached teacher outputs, labelled "cached".
- Visitor-pasted emails run student-only. If the router would escalate, the UI shows "would escalate (teacher disabled for public input)" and flags the result for human review.
- The admin can call the teacher live.

Why: visitors' text may be real personal data (D1.4); public traffic would burn paid credits; and KIE latency (up to about 50s observed) breaks the 30s request budget.

---

## D6 (2026-09-30): Backend hosting on Modal Starter (DECIDED)

- **Why not HF Spaces:** the HF docs now state "Gradio and Docker Spaces run on compute and require a paid plan to create: PRO for personal accounts." The user requires zero spend.
- **Choice:** Modal Starter ($30/month free compute, no card; https://modal.com/pricing).
  - One `@modal.asgi_app()` FastAPI function: CPU only (2 cores, 4 GiB), `min_containers=0`, `max_containers=1`, `scaledown_window=300`.
  - Weights come from HF Hub and are cached in a Modal Volume (`HF_HOME` inside it).
  - `@modal.enter(snap=True)` with `enable_memory_snapshot=True` (CPU snapshots are supported).
- **Cost estimate:** $0.0000351/s ≈ $0.126 per warm hour, about $7/month at generous demo use. A 24/7 keep-warm would cost about $92/month, so it is not allowed. A `warmup.sh` script is run before sharing the link instead.
- **Constraint check:** web endpoints have a 150s HTTP cap (our budget is 30s), and SSE streams in real time with `text/event-stream`.
- **Scheduling:** no background scheduler in the web container. The v1.2 automatic retrain would use a Modal cron (Starter allows 5).
- **Backup (documented only):** a free HF ZeroGPU Gradio Space (free accounts older than 30 days can host 2; Gradio only; per-visitor daily GPU quota of 2 min anonymous / 5 min free account).

---

## D7 (2026-09-30): Shared schema and prompt location

The spec has no top-level shared package. The student schema, system prompt, and normalizers live in `eval/evallib/` (the spec's shared library). Datagen, the Kaggle notebook (the bundle ships `evallib/`), the backend, and `run_eval.py` all import the same file, which guarantees an identical prompt at training and inference.

---

## D8 (2026-09-30): Zero-spend constraint and release scope

- No spend beyond the existing KIE credits.
- Every service is on a free tier with no card: Modal Starter, Neon Free, Vercel Hobby, HF Hub, Kaggle.
- If the datagen projection exceeds the remaining KIE credits, we switch to a free Google AI Studio key, **only after asking the user**.
- Release order:
  - v1 = P0, P1, P2a, P2b, P3, P4, P5, P8
  - v1.1 = manual retrain + register + safety gate + /models
  - v1.2 = automatic retrain + MCP
- The spec's "at least one automatic retrain" moves to v1.2. v1.1 shows a manual retrain through the same gate.

---

## D9 (2026-09-30): KIE congestion (HTTP 524) during datagen

During the full run, about 40–50% of calls to *both* `gemini-3-8-flash` and `gemini-3-7-flash` ended in Cloudflare 524 errors (origin timeout at about 126 s). Measured with 6 parallel writer calls per model. **Correction:** I first assumed failed calls were free; that was not verified. The real balance fell by more than the credits KIE reports on successful calls (pilot: balance delta 3.04 vs 1.86 logged), so timed-out calls are probably billed, at least partly. Budget from the balance (`GET /api/v1/chat/credit`), not from the cost log; `DATAGEN_MAX_CREDITS` only counts credits reported on successful calls.

**Decision:** keep Gemini 3.8 Flash (the user's choice) and raise concurrency from 8 to 16. That's still far below KIE's 20 requests per 10 s limit, and gives about 30 emails/min. Retries use exponential backoff, and the writer resumes from `emails.jsonl`.

The same latency makes live escalation in the public demo impractical, which confirms D5 (cached teacher for the samples).

## D10 (2026-09-30): Student base weights = `unsloth/gemma-3-270m-it`

These are the same weights as `google/gemma-3-270m-it`, in an ungated mirror, and they are what the training notebook loads. Using the identical base for inference avoids any mismatch. The Gemma Terms still apply (D2).

## D11 (2026-09-30): Tool matching improvements found with real teacher outputs

Running the 8 samples end to end surfaced three weak spots in deterministic resolution:
1. Fuzzy scores were diluted by matching against one long concatenated text.
2. Plurals and trade shorthand weren't normalized ("bvs", "cond", "stat").
3. Vague single words ("stat") matched the wrong category.

**Fix:**
- Score each alias separately.
- Apply a small synonym/plural normalizer to both sides.
- Restrict fuzzy search to the guessed category.
- For "same as last time", copy the quantity from the matched past order, flagged "confirm".

All of this is deterministic and unit-tested.

## D12 (2026-09-30): Optional dynamic int8 on CPU

Benchmark at 2 threads, which matches Modal:
| Setting | Tokens/s |
|---|---|
| fp32 | 11.5 |
| bf16 | 11.2 |
| dynamic int8 (Linear layers) | 15.2 |

On a test adapter, int8 changed the generated text, so it is **off by default** (`STUDENT_QUANTIZE=`). Enable it only if `eval/run_eval.py student --quantize int8` shows no loss in exam item F1.

## D13 (2026-09-30): MCP SDK 2.x

`mcp==2.2.0` renamed `FastMCP` to `MCPServer`. We mount `MCPServer.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True)` at `/mcp` inside FastAPI, and run its session manager in the app lifespan.

DNS-rebinding protection is disabled because the tools are public, read-only and served over HTTPS; the SDK's default would only allow localhost hosts. Stateless mode suits a scale-to-zero container.

## D14 (2026-09-30): Corrections pool

`split_export` reserves 40 unseen verified emails (`corrections_pool.jsonl`), which are never in train, val or exam. `scripts/seed_demo_corrections.py` runs them through the live system as the admin and submits only the edits needed to fix real disagreements with ground truth. This demonstrates a v2 retrain without leaking val or exam data into training.

## D15 (2026-09-30): Actual datagen cost

Balance went from about 482 credits (start) to 241 after datagen + the start of the teacher baseline. Logged (successful-call) credits: writing 102.7, verification 69.3, samples/pilot/probes about 4. The rest of the drop is the teacher baseline running plus probable charges for timed-out calls (D9). The pilot projection (about 260 credits with margin) held up roughly, but the failed-call overhead was not in it.

## D16 (2026-10-01): Deterministic repair of the student's `missing_info`

First real results (Kaggle v1): intent 98% and item F1 92-93% on exam, but missing-info F1 only 13-16%. Predictions showed the cause: the student never emits `order_number` and lists "quantity" for items that already have one (32 predicted vs 15 true on exam). It is a *derived* field, which a 270M model learns poorly.

Fix (`eval/evallib/postprocess.py`, the harness NORMALIZE step): recompute the rule-derivable kinds from the extraction and the email, and discard the student's own entries.
- `quantity: <desc>`: quote/return item, quantity null, no previous_order reference
- `order_number`: order_status email without an order or PO number
- `equipment_model: <desc>`: item with no `compatible_with` whose own line says it should fit something ("fits my unit") but names no equipment model

Measured on stored CPU predictions (missing-info F1, raw -> rules): exam 0.16 -> 0.67, val 0.09 -> 0.76; whole-email exact match exam 0.59 -> 0.71, val 0.57 -> 0.73. Keeping the student's own entries on top of the derived ones was worse than discarding them (0.57 vs 0.58 exam).

**Caveat:** I found the problem by inspecting exam predictions, so the exam gain is not a clean held-out number. Val (not inspected for this) improved by about the same amount. `size_or_spec` is not derived. The proper long-term fix is retraining v2 with better data, which the corrections flow supports.

## D17 (2026-10-01): Router threshold and its limit

Threshold 0.66, chosen on the validation split as the lowest escalation rate whose item F1 is within 0.01 of the best (val: item F1 0.9845 at 12.7% escalation, $0.53 per 1k). Applied to exam it escalates 9.3% of emails; on hard exam 43.3%.

Limit found during the live test: the student can be confidently wrong. The "ambiguous" demo email I first wrote returned confidence 0.97 with the wrong intent, so it never escalated. I did not lower the bar or hide this: I replaced the demo sample with a realistic mixed return-and-quote email the model really is unsure about (confidence 0.49, then escalated), and documented the limitation in the README.

## D18 (2026-10-01): Resolver keeps confident direct matches

Deriving `equipment_model` entries sent some specific items (e.g. a full size and spec) down the "guess from the customer's equipment" path and lowered SKU resolution from 93.5% to 91.8%. The resolver now keeps the direct catalog match whenever it is confident (score >= 0.9 and a clear margin), which restored 93.5%.

## D19 (2026-10-01): "Correct result" (admin corrections of the extraction)

Before, the only way to create training data was line edits at approval time (quantity, SKU, remove, add). Those can't fix the extraction itself (intent, a missing item, "this description is too vague to pick a part") and the counter counted edit rows. Now:
- `POST /api/quotes/{id}/correction` (admin token required) takes a full corrected extraction.
- **Quality gates, because this becomes training data:** every description, part number, equipment model and deadline must appear verbatim in the email (the same rule the dataset was built with); the schema and semantic checks must pass; a result identical to the model's is refused ("no changes"); sealed exam emails are refused; decided quotes can't be corrected.
- **Label consistency:** `missing_info` is rebuilt by the labeling rules (quantity and order_number from rules, via `derive_missing_info`), and only `size_or_spec` / `equipment_model` come from the admin's per-item checkboxes. A human can't produce a label that breaks the training format.
- **Counting:** one training example per email. Re-saving a quote replaces its example, correcting the same email twice counts once, and line edits on a quote that already has a saved correction don't add a second example.
- **Reject alone is never a correction.** The decision endpoint ignores line edits on reject (it previously processed them), and a test covers it.
- **Threshold behaviour:** at `RETRAIN_THRESHOLD` (20) real corrections the orchestrator now always prepares a run, even when `AUTO_RETRAIN_ENABLED=false`: in manual mode it builds the training bundle (state AWAITING_MANUAL) for you to run on Kaggle; in auto mode (v1.2) it also drives Kaggle. Pause still stops it.
- `scripts/seed_demo_corrections.py` now uses this endpoint and saves a correction only where the model's output differs from the ground-truth label.
