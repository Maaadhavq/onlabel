# Runtime image for the API. Sized for Render's free tier (512 MB, ~0.1 CPU):
# ONNX-only inference, no torch, no offline tooling.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN pip install --no-cache-dir uv==0.11.6

# Dependencies first so code edits do not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project && rm -rf /root/.cache

COPY onlabel ./onlabel
COPY scripts ./scripts
RUN python scripts/fetch_models.py

COPY data/index ./data/index

# Render sets $PORT; 8060 is the local default.
CMD ["sh", "-c", "uvicorn onlabel.api.main:app --host 0.0.0.0 --port ${PORT:-8060}"]
