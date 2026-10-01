# Train the student on Kaggle (by hand)

Time: about 10 minutes of clicking, then 20–40 minutes of GPU time. Cost: free (Kaggle gives about 30 GPU hours a week).

## 0. One-time setup
1. Create a Kaggle account → **Settings → Phone verification**. This is required for GPU and internet in notebooks.
2. Create a Hugging Face account, then do three things:
   1. Create a **write** token: Settings → Access Tokens → *Create new token* → fine-grained, with write access to your repos.
   2. Create an empty model repo, e.g. `your-hf-user/quotedesk-student`.
   3. Open https://huggingface.co/google/gemma-3-270m-it and click **Acknowledge license**. The backend later downloads the base model from there.

## 1. Build the dataset bundle (on your machine)
```bash
python -m datagen.make_bundle        # -> data/quotedesk-data.zip
```

## 2. Upload it as a Kaggle dataset
1. kaggle.com → **Datasets → + New Dataset**.
2. Drag in `data/quotedesk-data.zip`. Kaggle unzips it automatically.
3. Title it `quotedesk-data`, keep it **Private**, and click **Create**.
4. To update it later, open the dataset and use **⋮ → New version**, then upload the new zip.

## 3. Import and configure the notebook
1. kaggle.com → **Code → + New Notebook**.
2. **File → Import Notebook** → upload `training/finetune_gemma_lora.ipynb`.
3. Right sidebar → **Session options**:
   - **Accelerator:** `GPU T4 x2` (or `GPU T4`). Either works, but only one GPU is used.
   - **Internet:** **On**. It's needed for `pip install` and the model download.
4. Right sidebar → **Input → + Add Input** → *Your Datasets* → `quotedesk-data`.
5. Top menu → **Add-ons → Secrets** → *Add a new secret*: label `HF_TOKEN`, value = your HF write token → tick the box to attach it to this notebook.
6. In the **Parameters** cell (section 1), set `HF_MODEL_REPO = "your-hf-user/quotedesk-student"` and `VERSION_TAG = "v1"`.

## 4. Run
- **Run All**, or **Save Version → Save & Run All (Commit)** to run it in the background.
- Cell 2 (install) takes about 3–5 min. Training takes about 5–15 min for ~1,200 examples × 3 epochs on a T4. Evaluation and the base baseline take about 5–10 min.
- If a cell fails on a library version, restart the session and **Run All** again. The install cell pins the same versions as the official Unsloth Gemma 3 (270M) notebook.

## 5. Collect the results
- The last cell pushes the adapter to `HF_MODEL_REPO` with the tag `v1`, plus `eval.json`, `base_eval.json`, `run_config.json`, `loss_curve.png`, `NOTICE`, and `GEMMA_TERMS.md`.
- Alternatively, open the notebook's **Output** tab (or the committed version) and download `eval.json`, `base_eval.json`, `run_config.json`, and `loss_curve.png`.
- Send me: the **HF repo ID + tag**, `eval.json`, `base_eval.json`, and `run_config.json`.

Locally, import the notebook reports into the eval folder:
```bash
python eval/run_eval.py import-notebook --from path/to/downloaded/outputs
```
This copies them into `eval/reports/<timestamp>/` as `tuned.json` and `base.json`.

## 6. Point the backend at the new adapter
In `.env` (and later in the Modal secret):
```
HF_MODEL_REPO=your-hf-user/quotedesk-student
STUDENT_ADAPTER_REVISION=v1
```

## Colab alternative
Upload `quotedesk-data.zip` to Google Drive and unzip it to `MyDrive/quotedesk-data/`, or set `DATASET_DIR`. Open the notebook in Colab, choose **Runtime → Change runtime type → T4 GPU**, add `HF_TOKEN` under **Secrets** (key icon), mount Drive, and run all.

## Troubleshooting
| Symptom | Fix |
|---|---|
| `FileNotFoundError: Attach the quotedesk-data dataset` | Add the dataset as an Input (step 3.4) or set `DATASET_DIR`. |
| `pip` errors or no internet | Turn Internet **On** in Session options; phone verification is required. |
| CUDA out of memory | Lower `BATCH_SIZE` to 4 and raise `GRAD_ACCUM` to 4. |
| Push skipped | Check the `HF_TOKEN` secret is attached and that `HF_MODEL_REPO` isn't the placeholder. |
| `exam leakage` assertion | A corrections file contains an exam email. Rebuild the bundle; the orchestrator refuses these automatically. |
