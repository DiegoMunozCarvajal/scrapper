# AGENTS.md

## Setup

```bash
# Option 1: editable install (development)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m playwright install chromium

# Option 2: from requirements.txt (pinned versions, portable)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
python -m playwright install chromium

# Option 3: from pyproject.toml only (minimal)
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m playwright install chromium
```

## Commands

```bash
# Run all tests
pytest tests/ -v

# Run a specific test suite
pytest tests/unit/ -v
pytest tests/integration/ -v

# Lint
ruff check src/ tests/

# Run a Scrapy spider
scrapy crawl reddit -a query="python" -a limit=5 -s ROBOTSTXT_OBEY=False -o results.json
scrapy crawl hotmart -a query="python" -a limit=5 -s ROBOTSTXT_OBEY=False -o results.json
scrapy crawl generic -a url="https://books.toscrape.com" -a type="listing" -a limit=30 -s ROBOTSTXT_OBEY=False -o results.json
scrapy crawl corte -a query="libertad de expresion" -a limit=30 -s ROBOTSTXT_OBEY=False -o results.json
scrapy crawl rama -a query="sucesion" -a limit=10 -a download=1 -a download_dir=./providencias -s ROBOTSTXT_OBEY=False -o results.json

# Run with visible browser (debugging)
HEADLESS=false scrapy crawl hotmart -a query="python" -a limit=5

# Disable human simulation (faster but more detectable)
PLAYWRIGHT_HUMAN_SIMULATION=false scrapy crawl hotmart -a query="python" -a limit=5

# Disable curl-cffi (use default HTTP handler)
CURL_CFFI_ENABLED=false scrapy crawl reddit -a query="python" -a limit=5

# Disable LLM fallback
LLM_ENABLED=false scrapy crawl hotmart -a query="python" -a limit=5

# Deprecated spiders (emit warning on run)
scrapy crawl amazon -a query="laptop" -a limit=5
scrapy crawl mercadolibre -a query="iphone" -a limit=5
scrapy crawl quora -a query="startups" -a limit=5

# List available spiders
scrapy list

# Coverage report
pytest tests/ --cov=src/scrapper --cov-report=term-missing
```

## Scheduling & Deployment

### Local (runner_local.py)

Ejecuta spiders desde `queries.json` sin necesidad de Docker ni cron:

```bash
# Ver qué ejecutaría (sin correr)
python runner_local.py --dry-run

# Ejecutar un spider específico
python runner_local.py --spider reddit

# Ejecutar todos los spiders
python runner_local.py

# Acumular resultados en un solo archivo JSONL
python runner_local.py --append
```

**Salida:**
- Por defecto: `output/YYYYMMDD_HHMMSS/spider_query.json` (archivos separados por ejecución)
- Con `--append`: `output/spider_history.jsonl` (acumulativo)

### Docker (local con Scrapyd)

```bash
# Build and start all services
docker-compose up -d --build

# View logs
docker-compose logs -f

# Trigger a spider via Scrapyd API
curl -s -X POST 'http://localhost:6800/schedule.json' \
  --data-urlencode 'project=scrapper' \
  --data-urlencode 'spider=reddit' \
  --data-urlencode 'query=python' \
  --data-urlencode 'limit=5' \
  --data-urlencode 'setting=ROBOTSTXT_OBEY=False'

# Check job status
curl -s 'http://localhost:6800/listjobs.json?project=scrapper'

# Scrapyd health
curl -s http://localhost:6800/daemonstatus.json
```

### Google Cloud Run (producción)

Arquitectura: **Cloud Run Jobs** (one-off containers) + **Cloud Scheduler** (cron triggers). Resultados van a Supabase.

```bash
# 0. Configurar variables de entorno
export PROJECT_ID=tu-proyecto-gcp
export REGION=us-central1
export SUPABASE_URL=https://tu-proyecto.supabase.co
export SUPABASE_KEY=tu-service-role-key
export OPENAI_API_KEY=sk-...

# 1. Deploy completo (build + push + jobs + schedulers)
./deploy_cloud_run.sh

# 2. Ejecutar un job manualmente (debug)
gcloud run jobs execute scrapper-reddit --region us-central1

# 3. Ver logs de una ejecución
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=scrapper-reddit" --limit 50
```

**Configuración por spider** en `queries.json`:

```json
{
  "reddit": {
    "schedule": "*/30 * * * *",
    "cloud_run": { "cpu": 1, "memory": "1Gi", "timeout": "15m" },
    "queries": [...]
  }
}
```

**Costo estimado:** Dentro del free tier de Cloud Run (~$0.35/mes si se excede ligeramente). $300 de créditos gratis para nuevas cuentas.

## Architecture

**Scrapy + scrapy-playwright + playwright-stealth v2 + curl-cffi + OpenAI + Supabase + portalocker + loguru**

- `src/scrapper/spiders/` — Scrapy spiders (reddit, hotmart, generic, corte, rama + deprecated: amazon, mercadolibre, quora)
- `src/scrapper/spiders/reddit.py` — Triple strategy: RSS discovery → old.reddit.com HTML fallback → LLM extraction. Extracts score, comment_count, published_at, top comment. Incremental scraping via Supabase cutoff date.
- `src/scrapper/spiders/hotmart.py` — Triple strategy: internal API interception (via scrapy-playwright PageMethod) → Playwright DOM fallback → LLM extraction. Extracts price, rating, review_count. Handles pagination via PageMethod load-more clicking.
- `src/scrapper/spiders/generic.py` — Universal spider: curl-cffi → Playwright fallback → LLM extraction with type-hinted prompts. Supports listing, article, product, forum page types.
- `src/scrapper/items.py` — `PostItem`, `ProductItem`, `GenericItem` (with `scraped_at` timestamps in UTC)
- `src/scrapper/models.py` — `Post`, `Product`, `ScrapeResult` dataclasses (used across spiders and pipelines)
- `src/scrapper/pipelines.py` — Validate → DataQuality → Dedup → Supabase upsert (with 3 retries + DropItem on failure)
- `src/scrapper/pagination.py` — `PaginationDetector` class for detecting next-page URLs and pagination type (links/load-more/scroll) from HTML
- `src/scrapper/middlewares.py` — Retry backoff, proxy rotation (incl. Playwright + Decodo residential proxy support with health tracking), UA rotation (incl. Playwright)
- `src/scrapper/stealth_handler.py` — Custom Playwright download handler wrapping `playwright-stealth` v2 + canvas/WebGL spoofing + cookie persistence + human simulation (with logging). **Has fallback for both old and new playwright-stealth APIs** (Linux wheels ship a different API than macOS).
- `src/scrapper/curl_cffi_handler.py` — Composite download handler inheriting from `ScrapyPlaywrightStealthDownloadHandler`: Playwright for JS, curl-cffi with TLS impersonation for everything else
- `src/scrapper/llm_extractor.py` — `LLMExtractor` class (OpenAI gpt-4o-mini, JSON mode, SQLite cache) + shared `llm_fallback()` function (properly closes cache)
- `src/scrapper/llm_cache.py` — SQLite cache with TTL expiry, thread-safe access, timezone-aware timestamps
- `src/scrapper/prompts/` — Prompt templates per site (hotmart.py, reddit.py, generic.py)
- `src/scrapper/extensions.py` — StatsLogger (with corrupted JSON recovery + portalocker cross-platform locking), EmailAlerter with anomaly detection
- `src/scrapper/dashboard.py` — Static HTML metrics dashboard (template in `templates/dashboard.html`)
- `src/scrapper/templates/` — HTML templates (dashboard.html with `__DATA__` placeholder)
- `src/scrapper/rag_export.py` — Markdown + JSONL export pipelines for RAG/vector DBs (with OSError handling)
- `src/scrapper/settings.py` — Scrapy settings, Playwright config, env-driven headless/human simulation toggles, LLM + curl-cffi config, loguru file rotation setup
- `src/scrapper/utils.py` — `USER_AGENTS`, `random_user_agent()`, `ensure_dir()`, `slugify()`, `FakeFailure`
- `setup.py` — Minimal shim for `scrapyd-deploy` compatibility (Scrapyd needs `entry_points` for spider discovery; `setup()` reads package config from `pyproject.toml`)
- `Dockerfile` — Multi-stage-like build with `busybox-static` (non-root crond), Playwright Chromium, BuildKit cache mount, non-root `appuser` (UID 10001), healthcheck via Scrapyd API. **Para uso local con Docker Compose.**
- `Dockerfile.cloudrun` — Imagen optimizada para Cloud Run Jobs (one-off, sin Scrapyd/crond). Usa `playwright install chromium` + entrypoint `cloud_run_runner.py`.
- `docker-compose.yml` — Single-service stack: `cap_drop: ALL`, `no-new-privileges`, `shm_size: 2gb` (Chromium), volume mounts for persistence. **Para uso local.**
- `docker-entrypoint.sh` — Graceful shutdown (SIGTERM → SIGKILL after 10s), writability checks, SQLite file bootstrap, crontab generation, Scrapyd + dashboard startup, log streaming. **Para Docker local.**
- `bin/health-check.sh` — Scrapyd health monitoring script
- `scripts/setup_supabase.sql` — DB schema with RLS policies (5 tables: sites, scrape_jobs, posts, products, scraped_pages). **Run in Supabase SQL Editor to initialize.** Idempotent (`IF NOT EXISTS`).
- `generate_schedule.py` — Generates crontab from `queries.json` for Scrapyd scheduling (uses busybox crond in Docker, not scrapyd.conf schedule). **Para Docker local.**
- `queries.json` — Configuración de spiders, queries, schedules y recursos de Cloud Run (leído por `cloud_run_runner.py`, `runner_local.py`, `generate_schedule.py` y `deploy_cloud_run.sh`)
- `runner_local.py` — Ejecuta spiders localmente desde `queries.json` con salida timestamped o acumulativa. **Para desarrollo/pruebas.**
- `cloud_run_runner.py` — Entrypoint para Cloud Run Jobs. Lee `queries.json`, ejecuta un spider y sale. **Para producción en GCP.**
- `deploy_cloud_run.sh` — Script de deployment: build + push a Artifact Registry, crea/actualiza Cloud Run Jobs + Cloud Schedulers. Lee config de `queries.json`.

## Spider Status

| Spider | Status | Strategy | Notes |
|--------|--------|----------|-------|
| Reddit | ✅ Works | RSS → HTML fallback → LLM | old.reddit.com, incremental scraping, score/comments/published_at |
| Hotmart | ✅ Works | API → Playwright fallback → LLM | Playwright for API discovery via PageMethod, price/review extraction, pagination |
| Generic | ✅ Works | curl-cffi → Playwright → LLM + pagination | 10 page types + pagination (links/load-more/scroll), type-hinted prompts |
| Corte Constitucional | ✅ Works | Playwright → Google CSE DOM | Jurisprudence search via /buscador?q=, pagination, visible browser required |
| Rama Judicial | ✅ Works | Playwright → PrimeFaces JSF XML | CSJ search via POST+ViewState, XML interception, virtual pagination, download support |
| Amazon | ⛔ Deprecated | — | Needs residential proxies |
| MercadoLibre | ⛔ Deprecated | — | Needs residential proxies |
| Quora | ⛔ Deprecated | — | Cloudflare + login + residential proxies required |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SUPABASE_URL` | — | Supabase project URL |
| `SUPABASE_KEY` | — | Supabase service role key (⚠️ bypasses RLS) |
| `PROXY_LIST` | — | Comma-separated proxy URLs (takes precedence over Decodo) |
| `DECODO_USER` | — | Decodo residential proxy username |
| `DECODO_PASSWORD` | — | Decodo residential proxy password |
| `DECODO_ENDPOINT` | `gate.decodo.com` | Decodo proxy gateway endpoint |
| `DECODO_PORT` | `7000` | Decodo proxy gateway port |
| `HEADLESS` | `true` | Run Playwright in headless mode |
| `PLAYWRIGHT_HUMAN_SIMULATION` | `true` | Enable random scroll/delay + canvas/WebGL spoofing |
| `OPENAI_API_KEY` | — | OpenAI API key for LLM fallback extraction |
| `LLM_ENABLED` | `true` | Enable LLM extraction fallback |
| `LLM_MODEL` | `gpt-4o-mini` | OpenAI model for extraction |
| `LLM_CACHE_TTL` | `86400` | LLM response cache TTL in seconds |
| `LLM_CACHE_PATH` | `llm_cache.db` | SQLite cache file path |
| `CURL_CFFI_ENABLED` | `true` | Use curl-cffi with TLS impersonation |
| `CURL_CFFI_IMPERSONATE` | `chrome124` | Browser fingerprint to impersonate |
| `COOKIE_PERSIST_ENABLED` | `true` | Persist cookies between runs |
| `RAG_EXPORT_ENABLED` | `true` | Export scraped items as Markdown + JSONL |
| `LOG_LEVEL` | `INFO` | Log verbosity level |
| `ALERT_WEBHOOK_URL` | — | Discord/Slack webhook for error alerts |
| `ALERT_SMTP_HOST` | `smtp.gmail.com` | SMTP host for email alerts |
| `ALERT_SMTP_PORT` | `587` | SMTP port for email alerts |
| `ALERT_EMAIL_FROM` | — | Sender email address |
| `ALERT_EMAIL_PASSWORD` | — | SMTP password (Gmail App Password) |
| `ALERT_EMAIL_TO` | — | Recipient email address |
| `ALERT_ERROR_THRESHOLD` | `5` | Error count to trigger email alert |

> **Nota:** Las variables `SCHEDULE_ENABLED` y `SCRAPYD_API_URL` solo aplican al setup Docker local con Scrapyd.

## Testing

- 320 tests passing (items, models, pipelines, settings, middleware, spiders, stealth, llm_cache, llm_extractor, prompts, curl_cffi, utils, extensions, dashboard, rag_export, generic, pagination)
- 65% coverage (core modules at 77-100%, spiders need Playwright for full coverage)
- Integration tests use fixture files (XML/JSON/HTML) for deterministic offline testing
- `asyncio_mode = "auto"` in pyproject.toml
- Supabase deprecation warnings suppressed via `filterwarnings` in pyproject.toml
- Test structure: `tests/unit/` (unit), `tests/integration/` (spider/config), `tests/fixtures/` (sample data)
