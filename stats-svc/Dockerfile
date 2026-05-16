# syntax=docker/dockerfile:1
# stats-svc: telnet ingestor + FastAPI dashboard for the DX cluster.
FROM python:3.12-slim AS base

# Faster, quieter, no .pyc clutter; unbuffered logs for container stdout.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first for layer caching (only requirements.txt — not dev deps).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code and bundled data/static assets.
COPY app ./app
COPY data ./data

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness: the FastAPI health route. Uses stdlib only (no curl in slim image).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else sys.exit(1)"]

CMD ["python", "-m", "app.main"]
