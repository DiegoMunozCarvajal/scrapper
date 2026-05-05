# scrapper

Multi-site web scraper built on **Scrapy + Playwright + curl-cffi + OpenAI + Supabase**.

Active spiders: Reddit, Hotmart, Generic, Corte Constitucional, Rama Judicial. Deprecated: Amazon, Mercado Libre, Quora.

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m playwright install chromium
```

## Usage

All spiders run via Scrapy CLI:

```bash
# Reddit (active)
scrapy crawl reddit -a query="python" -a limit=5 -s ROBOTSTXT_OBEY=False -o results.json

# Hotmart (active)
scrapy crawl hotmart -a query="marketing" -a limit=5 -s ROBOTSTXT_OBEY=False -o results.json
```

### Debugging & feature flags

```bash
# Visible browser
HEADLESS=false scrapy crawl hotmart -a query="python" -a limit=5

# Disable human simulation (faster, more detectable)
PLAYWRIGHT_HUMAN_SIMULATION=false scrapy crawl reddit -a query="python" -a limit=5

# Disable curl-cffi TLS impersonation
CURL_CFFI_ENABLED=false scrapy crawl reddit -a query="python" -a limit=5

# Disable LLM fallback extraction
LLM_ENABLED=false scrapy crawl hotmart -a query="python" -a limit=5

# List all spiders
scrapy list
```

## Spider Status

| Spider | Status | Strategy | Notes |
|--------|--------|----------|-------|
| Reddit | Active | RSS → HTML fallback → LLM | old.reddit.com, incremental via Supabase cutoff |
| Hotmart | Active | API interception → Playwright DOM → LLM | PageMethod API discovery, pagination |
| Amazon | Deprecated | — | Requires residential proxies |
| MercadoLibre | Deprecated | — | Requires residential proxies |
| Quora | Deprecated | — | Cloudflare + login required |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SUPABASE_URL` | — | Supabase project URL |
| `SUPABASE_KEY` | — | Supabase service role key |
| `OPENAI_API_KEY` | — | OpenAI API key for LLM fallback |
| `PROXY_LIST` | — | Comma-separated proxy URLs |
| `ALERT_WEBHOOK_URL` | — | Discord/Slack webhook for alerts |
| `HEADLESS` | `true` | Run Playwright headless |
| `PLAYWRIGHT_HUMAN_SIMULATION` | `true` | Scroll/delay + canvas/WebGL spoofing |
| `LLM_ENABLED` | `true` | Enable LLM extraction fallback |
| `LLM_MODEL` | `gpt-4o-mini` | OpenAI model for extraction |
| `LLM_CACHE_TTL` | `86400` | LLM cache TTL in seconds |
| `CURL_CFFI_ENABLED` | `true` | Use curl-cffi TLS impersonation |
| `CURL_CFFI_IMPERSONATE` | `chrome124` | Browser fingerprint to mimic |
| `COOKIE_PERSIST_ENABLED` | `true` | Persist cookies between runs |

## Architecture

**Stack**: Scrapy + scrapy-playwright + playwright-stealth v2 + curl-cffi + OpenAI + Supabase + portalocker + loguru

- **Triple strategy extraction**: Primary (RSS/API) → Fallback (DOM/Playwright) → LLM (OpenAI)
- **Anti-bot**: TLS impersonation (curl-cffi), canvas/WebGL spoofing, cookie persistence, human simulation
- **Pipelines**: Validate → DataQuality → Dedup → Supabase upsert (3 retries) → RAG export (Markdown + JSONL)
- **Monitoring**: StatsLogger (JSON metrics), EmailAlerter (anomaly detection), HTML dashboard

## Docker + Scrapyd

### Setup

```bash
# 1. Copy and configure environment
cp .env.example .env   # or create .env with SUPABASE_URL, SUPABASE_KEY, etc.

# 2. Create required host files (prevents Docker creating directories)
touch llm_cache.db

# 3. Build and start (all services: Scrapyd + cron + dashboard)
docker-compose up -d --build
```

### What runs inside

| Service | Port | Description |
|---------|------|-------------|
| Scrapyd | `:6800` | Spider execution engine (JSON API) |
| Dashboard | `:8080` | HTML metrics dashboard (generated after first crawl) |
| Cron | — | Busybox crond (non-root), triggers spiders per `queries.json` |

### Scheduling

Edit `queries.json` to configure cron schedules. The entrypoint auto-generates a crontab from it on start. Spiders run via the Scrapyd API.

```json
{
  "reddit": {
    "schedule": "*/30 * * * *",
    "queries": [
      { "query": "python", "limit": 10 }
    ]
  },
  "generic": {
    "schedule": "0 */6 * * *",
    "tasks": [
      { "url": "https://books.toscrape.com", "type": "listing" }
    ]
  }
}
```

### Trigger a spider manually

```bash
curl -s -X POST 'http://localhost:6800/schedule.json' \
  --data-urlencode 'project=scrapper' \
  --data-urlencode 'spider=reddit' \
  --data-urlencode 'query=python' \
  --data-urlencode 'limit=5' \
  --data-urlencode 'setting=ROBOTSTXT_OBEY=False'
```

### Health monitoring

```bash
curl -s http://localhost:6800/daemonstatus.json     # Scrapyd status
curl -s 'http://localhost:6800/listjobs.json?project=scrapper'  # Job list
./bin/health-check.sh                               # Scrapyd health script
```

### Volumes

| Host path | Container path | Purpose |
|-----------|---------------|---------|
| `./logs/` | `/app/logs` | Spider + cron logs |
| `./items/` | `/app/items` | Scraped data exports |
| `./eggs/` | `/app/eggs` | Scrapyd project eggs |
| `./queries.json` | `/app/queries.json` | Cron schedule config |
| `./llm_cache.db` | `/app/llm_cache.db` | LLM extraction cache |

### Cross-platform notes

- Works on macOS, Linux, and Windows (Docker Desktop).
- **Linux only**: bind-mount volumes are owned by UID 10001. If permissions fail, run `chown -R 10001:10001 .` in the project root.
- Chromium sandbox requires `shm_size: 2gb` (set in `docker-compose.yml`).

## Tests

```bash
# All tests
pytest tests/ -v

# Coverage
pytest tests/ --cov=src/scrapper --cov-report=term-missing

# Lint
ruff check src/ tests/
```
