# Portable fallback image (Modal is the primary host; see backend/modal_app.py).
# Build from the repo root:  docker build -f backend/Dockerfile -t quotedesk-backend .
FROM python:3.11-slim

RUN useradd -m -u 1000 user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/hf QD_DATA_DIR=/app/data QD_EVAL_DIR=/app/eval QD_WORK_DIR=/home/user/work \
    PYTHONPATH=/app/backend:/app:/app/eval TOKENIZERS_PARALLELISM=false PORT=8000
WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r /app/backend/requirements.txt

COPY --chown=user backend/app /app/backend/app
COPY --chown=user eval/evallib /app/eval/evallib
COPY --chown=user eval/reports /app/eval/reports
COPY --chown=user datagen /app/datagen
COPY --chown=user training /app/training
COPY --chown=user data/catalog.json data/customers.json data/orders.json data/equipment.json /app/data/
COPY --chown=user data/splits /app/data/splits

USER user
EXPOSE 8000
CMD ["sh", "-c", "cd /app/backend && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
