# syntax=docker/dockerfile:1

# Dockerfile optimizado para Google Cloud Run Jobs.
# Multi-stage build para reducir tamaño de imagen final.
# No incluye Scrapyd, crond, ni healthchecks — es un contenedor one-off.

# ═══════════════════════════════════════════════════════════════════
# Stage 1: Builder — instala dependencias y compila el paquete
# ═══════════════════════════════════════════════════════════════════
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Build tools necesarios para compilar extensiones nativas
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar archivos de dependencias y código fuente
COPY pyproject.toml setup.py ./
COPY src/ src/

# Crear virtualenv e instalar dependencias
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -e ".[dev]"

# ═══════════════════════════════════════════════════════════════════
# Stage 2: Runtime — imagen mínima con solo deps de ejecución
# ═══════════════════════════════════════════════════════════════════
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HEADLESS=true \
    PLAYWRIGHT_HUMAN_SIMULATION=true \
    RAG_EXPORT_ENABLED=false \
    COOKIE_PERSIST_ENABLED=false \
    PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright

WORKDIR /app

# Runtime system deps para Chromium + utilidades
# Lista basada en Playwright Docker deps para Debian 12 (bookworm)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 \
    libx11-6 libxext6 libxcb1 libdbus-1-3 \
    fonts-liberation fontconfig curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Crear usuario no-root (seguridad + Chromium sandbox requiere no-root)
RUN groupadd --system --gid 1000 appgroup && \
    useradd --system --gid appgroup --create-home --uid 1000 appuser

# Copiar virtualenv pre-construido desde builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Instalar navegador Chromium como usuario no-root
USER appuser
RUN playwright install chromium

# Crear directorios de trabajo necesarios
RUN mkdir -p logs metrics cookies rag_output && touch llm_cache.db

# Copiar código fuente con permisos correctos
USER root
COPY --chown=appuser:appgroup src/ src/
COPY --chown=appuser:appgroup queries.json cloud_run_runner.py ./
USER appuser

# Entrypoint: ejecuta el runner y sale
ENTRYPOINT ["python", "cloud_run_runner.py"]
