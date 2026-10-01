# Deploying QuoteDesk (free tiers, no card)

Order: **HF Hub model → Neon → Modal backend → Vercel frontend → smoke test.** Total time is about 45 minutes the first time.

## 0. Prerequisites
- You trained the student and pushed it to `https://huggingface.co/<you>/quotedesk-student` with tag `v1` (see `training/README_MANUAL.md`).
- You ran the evaluation locally and `eval/reports/<run>/summary.json` exists (`python eval/run_eval.py summarize`). The Results page is baked into the backend image from `eval/reports/`.
- `backend/app/samples/teacher_cache.json` exists (`python scripts/cache_sample_teacher.py`).
- `ROUTER_CONFIDENCE_THRESHOLD` is taken from `eval/reports/<run>/calibration.json`.

## 1. Neon (database)
1. neon.com → sign up (Free plan) → **New project** `quotedesk`.
2. **Connect** → copy the **pooled** connection string, e.g. `postgresql://USER:PASS@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require`.
3. The backend accepts `postgres://` and `postgresql://` URLs as-is. Tables are created on first start, so there's no manual migration. For later schema changes run `cd backend && alembic stamp head` once, then use `alembic revision --autogenerate` / `alembic upgrade head`.

## 2. Modal (backend)
1. modal.com → sign up with GitHub/Google → confirm the plan is **Starter ($30/month free credits)** → **don't add a card**.
2. Install the client and log in:
   ```bash
   pip install modal==1.6.0
   modal setup                      # opens the browser, writes ~/.modal.toml
   ```
3. Create the secret `quotedesk-secrets`: Modal dashboard → **Secrets → Create new secret → Custom**. Add these keys:

   | Key | Value |
   |---|---|
   | `KIE_API_KEY` | your KIE key (rotate it first, since it was shared in chat) |
   | `LLM_PROVIDER` | `kie` |
   | `GEMINI_MODEL` | `gemini-3-8-flash` |
   | `HF_TOKEN` | HF token (read is enough for the backend) |
   | `HF_MODEL_REPO` | `<you>/quotedesk-student` |
   | `STUDENT_ADAPTER_REVISION` | `v1` |
   | `STUDENT_BASE_MODEL` | `unsloth/gemma-3-270m-it` |
   | `DATABASE_URL` | the Neon pooled URL |
   | `ADMIN_TOKEN` | `python -c "import secrets;print(secrets.token_urlsafe(32))"` |
   | `ALLOWED_ORIGINS` | `https://<your-app>.vercel.app,http://localhost:3000` |
   | `ROUTER_CONFIDENCE_THRESHOLD` | from calibration.json |
   | `TEACHER_LIVE_MODE` | `admin_only` |

   Or from a local file (never commit it): `modal secret create quotedesk-secrets --from-dotenv .env.modal`.
4. Cache the weights in the Volume (one time, about 2 minutes):
   ```bash
   modal run backend/modal_app.py::prefetch
   ```
5. Deploy:
   ```bash
   modal deploy backend/modal_app.py
   ```
   The output shows the URL, e.g. `https://<workspace>--quotedesk-web.modal.run`. Open `/api/health` in a browser: `student.state` should become `ready`.

**Costs:** the app is configured with `min_containers=0`, `max_containers=1` and `scaledown_window=300`, on 2 CPU cores and 4 GiB. That's about $0.126 per warm hour, roughly $7/month for generous demo traffic, against the free $30. Check **Usage** in the Modal dashboard weekly. There is no card on file, so nothing beyond the free credit can be billed.

**Automatic retrain (v1.2, optional):** set `AUTO_RETRAIN_ENABLED=true` (plus `KAGGLE_API_TOKEN`, `KAGGLE_DATASET_SLUG`, `KAGGLE_KERNEL_SLUG`) both in the secret and in your shell, then deploy again. This also deploys a 15-minute cron that advances runs. Leave it off otherwise: then no cron exists and it costs nothing.

## 3. Vercel (frontend)
1. Push the repo to GitHub (public).
2. vercel.com → sign in with GitHub → **Add New → Project** → import the repo.
3. **Root Directory:** `frontend`. The framework is detected as Next.js.
4. **Environment variables:**
   - `NEXT_PUBLIC_API_BASE_URL` = the Modal URL (no trailing slash)
   - optional: `NEXT_PUBLIC_GITHUB_URL`, `NEXT_PUBLIC_NOTEBOOK_URL`, `NEXT_PUBLIC_MODEL_CARD_URL`
5. **Deploy.** Then add the Vercel URL to `ALLOWED_ORIGINS` in the Modal secret and run `modal deploy backend/modal_app.py` again.

## 4. Smoke test and warm-up
```bash
python scripts/smoke_test.py --api https://<workspace>--quotedesk-web.modal.run --frontend https://<your-app>.vercel.app
API=https://<workspace>--quotedesk-web.modal.run bash scripts/warmup.sh     # run before sharing the link
```
To test a cold start: `modal app stop quotedesk`, run `modal deploy backend/modal_app.py` again, then open the site. It shows "Waking up the server…" and recovers on its own.

## 5. Demo a retrain (v1.1, manual)
1. Sign in as admin on the site (key icon) with your `ADMIN_TOKEN`.
2. Create corrections: either correct real mistakes yourself (Playground → process an email → **Correct result** → Save; the counter shows `Corrections n/20`), or seed realistic ones:
   `python scripts/seed_demo_corrections.py --api <modal url> --token <ADMIN_TOKEN>`
   Reject alone does not count. At 20, a training bundle is prepared automatically.
3. On **/models**, the run appears when the counter reaches 20 (or click **Retrain now** earlier), then **Download training bundle**.
4. On Kaggle, upload the zip as a new version of `quotedesk-data`, run the notebook with `VERSION_TAG = "v2"`, and let it push the tag.
5. On **/models**, open **Register a manually trained version**, enter `v2`, and paste the notebook's `eval.json`. The gate promotes it (hot swap) or rejects it with reasons.

## Backup plan (documented only): HF ZeroGPU
If Modal becomes unavailable: free Hugging Face accounts (older than 30 days) can host 2 ZeroGPU **Gradio** Spaces. Two options:
- Mount the FastAPI app into a Gradio app (`gr.mount_gradio_app`), with student inference inside `@spaces.GPU(duration=20)`.
- Expose student inference only, and call it with `gradio_client` from another host.

Limits: Gradio SDK only, and visitor GPU quota is 2 min/day anonymous or 5 min/day for free accounts. Untested.
