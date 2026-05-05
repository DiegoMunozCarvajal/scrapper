# syntax=docker/dockerfile:1

FROM python:3.12-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# ── System packages (curl for healthcheck, busybox-static for crond) ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl busybox-static \
    && rm -rf /var/lib/apt/lists/*

# ── Virtual environment ────────────────────────────────────────────
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# ── Install Python dependencies + package (pip downloads cached via mount)
COPY pyproject.toml .
COPY src/ src/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install ".[docker]"

# ── Install Playwright system dependencies (as root) ───────────────
RUN playwright install-deps chromium

# ── Non-root user ──────────────────────────────────────────────────
ARG APP_UID=10001
ARG APP_USER=appuser
ENV APP_HOME=/home/$APP_USER
RUN useradd --no-log-init --create-home --shell /bin/bash --uid $APP_UID $APP_USER && \
    rm -rf /app/build /app/src/scrapper.egg-info

# ── Install Chromium browser (cached — before frequently-changing COPY) ─
ENV PLAYWRIGHT_BROWSERS_PATH=$APP_HOME/.cache/ms-playwright
RUN playwright install chromium && \
    chown -R $APP_USER:$APP_USER $APP_HOME/.cache/ms-playwright

# ── Copy everything with appuser ownership ─────────────────────────
COPY --chown=$APP_USER:$APP_USER . .
RUN chmod +x /app/docker-entrypoint.sh && \
    chown $APP_USER:$APP_USER /app

USER $APP_USER

# ── Create runtime directories as appuser ──────────────────────────
RUN mkdir -p eggs logs dbs items metrics rag_output cookies

# ── Expose ports ───────────────────────────────────────────────────
EXPOSE 6800 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD ["curl", "-sf", "http://localhost:6800/daemonstatus.json"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
