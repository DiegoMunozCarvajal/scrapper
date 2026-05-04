# syntax=docker/dockerfile:1

# ── Builder: compile Python deps + download Playwright browsers ───
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libxml2-dev libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir ".[docker]"

RUN playwright install chromium

# ── Runtime: slim image with only what's needed ──────────────────
FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl cron \
    && rm -rf /var/lib/apt/lists/*

# System libraries Playwright needs at runtime (no browser download)
RUN playwright install-deps chromium

# Non-root user
RUN useradd --no-log-init --create-home --shell /bin/bash --uid 10001 appuser

WORKDIR /app

# Copy compiled venv + browsers from builder
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=appuser:appuser /root/.cache/ms-playwright /home/appuser/.cache/ms-playwright

ENV PATH="/opt/venv/bin:$PATH"
ENV PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright

# Copy source + config files
COPY --chown=appuser:appuser . .

RUN chmod +x /app/docker-entrypoint.sh && \
    mkdir -p eggs logs dbs items metrics

USER appuser

EXPOSE 6800 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -sf http://localhost:6800/daemonstatus.json || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
