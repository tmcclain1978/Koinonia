# ----------------------------
# Base image (common to all)
# ----------------------------
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps you’re likely to need (psycopg2, builds, curl for healthcheck)
RUN adduser --disabled-password app && \
    apt-get update && apt-get install -y --no-install-recommends \
      build-essential libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ----------------------------
# Dependencies layer (cached)
# ----------------------------
FROM base AS deps
COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install -r requirements.txt

# ----------------------------
# Development image (hot-reload)
#   docker build -t options-analytics:dev --target dev .
#   docker run -p 8000:8000 --env-file .env options-analytics:dev
# ----------------------------
FROM deps AS dev
ENV ENV=development
COPY . .
USER app
EXPOSE 8000
CMD ["uvicorn","api.main:app","--host","0.0.0.0","--port","8000","--reload"]

# ----------------------------
# Production image (gunicorn)
#   docker build -t options-analytics:prod --target prod .
#   docker run -p 10000:10000 --env-file .env.production options-analytics:prod
# ----------------------------
FROM deps AS prod
ENV ENV=production
COPY . .

# (Optional) Warm-up step (e.g., compile, download models, etc.)
# RUN python - <<'PY'
# print("Warm-up step placeholder")
# PY

# Healthcheck hits /healthz (make sure your FastAPI mounts it)
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD curl -fsS http://localhost:10000/healthz || exit 1

USER app
EXPOSE 10000
CMD ["gunicorn","-k","uvicorn.workers.UvicornWorker","api.main:app","--workers","2","--threads","2","--timeout","30","--graceful-timeout","30","--bind","0.0.0.0:10000"]
