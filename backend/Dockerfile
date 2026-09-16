FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads

EXPOSE 8000

# Applies migrations, ensures reference/admin/sample data exists, then starts the
# API. All three steps are idempotent — safe to run on every container start/restart,
# not just the first one. $PORT is read from the environment for hosting providers
# (e.g. Render) that assign it dynamically; 8000 is the fallback for docker-compose.
CMD ["sh", "-c", "alembic upgrade head && python -m seed.seed && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
