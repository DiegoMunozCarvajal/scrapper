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

## Google Cloud Run (production)

Deploy to Cloud Run Jobs + Cloud Scheduler. Spider config is externalized via Secret Manager, enabling zero-rebuild config changes.

```bash
# Prerequisites
export PROJECT_ID=your-gcp-project
export SUPABASE_URL=https://your-project.supabase.co
export SUPABASE_KEY=your-service-role-key
export OPENAI_API_KEY=sk-...

# Full deploy (code + config)
./deploy_cloud_run.sh

# Incremental deploy (config only, no Docker rebuild)
./deploy_cloud_run.sh --skip-build

# Incremental deploy for a specific spider
./deploy_cloud_run.sh --skip-build --spider reddit

# Execute a job manually
gcloud run jobs execute scrapper-reddit --region us-central1

# View execution logs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=scrapper-reddit" --limit 50
```

### queries.json format for Cloud Run

```json
{
  "reddit": {
    "schedule": "0 10 * * *",
    "cloud_run": { "cpu": 1, "memory": "1Gi", "timeout": "45m" },
    "queries": [
      { "subreddit": "python", "limit": 50 }
    ]
  },
  "reddit-evening": {
    "spider": "reddit",
    "schedule": "0 22 * * *",
    "cloud_run": { "cpu": 1, "memory": "1Gi", "timeout": "45m" },
    "queries": [
      { "subreddit": "django", "limit": 50 }
    ]
  }
}
```

The `spider` field maps job names to Scrapy spider names (e.g. `reddit-evening` → `reddit`).

## Reddit Query Guide

The Reddit spider accepts these `-a` parameters, all usable in `queries.json`:

### Query parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `subreddit` | string | — | Subreddit to scrape (e.g. `"dating"`, `"AskWomen"`) |
| `query` | string | — | Search term within Reddit. Omit to browse subreddit listings. |
| `limit` | int | `25` | Max posts to scrape (capped at 100) |
| `sort` | string | `"new"` | Sort order: `"new"`, `"hot"`, `"top"`, `"rising"`, `"controversial"` |
| `time_filter` | string | auto | Time range: `"hour"`, `"day"`, `"week"`, `"month"`, `"year"`, `"all"`. Auto-calculated from last scrape if unset. |
| `nsfw` | string | `"include"` | `"include"`, `"exclude"`, or `"only"` |
| `include_comments` | bool | `false` | Fetch top comments for each post (up to 5) |
| `date_from` | string | — | Start date for historical scraping (`"YYYY-MM-DD"`) |
| `date_to` | string | — | End date for historical scraping (`"YYYY-MM-DD"`) |

### Scraping modes

**Subreddit browsing** (no query, just subreddit):
```json
{ "subreddit": "dating", "limit": 50 }
```
Scrapes the subreddit's listing sorted by `sort` (default: new).

**Keyword search within a subreddit:**
```json
{ "subreddit": "dating", "query": "first date tips", "limit": 30 }
```

**Keyword search across all of Reddit:**
```json
{ "query": "python programming", "limit": 25, "sort": "top", "time_filter": "week" }
```

**Historical date-range scraping** (uses PullPush archive API):
```json
{ "subreddit": "dating", "date_from": "2025-01-01", "date_to": "2025-06-30", "limit": 100 }
```
When `date_from` or `date_to` is set, the spider switches from native Reddit JSON API to PullPush, which supports date-filtered queries the official API doesn't.

**Full featured query:**
```json
{
  "subreddit": "AskWomen",
  "query": "career advice",
  "limit": 50,
  "sort": "top",
  "time_filter": "month",
  "nsfw": "exclude",
  "include_comments": true
}
```

### Scraping strategy

The spider tries strategies in order with automatic fallback:

```
PullPush (if date_from/date_to set) → falls back to HTML search
JSON API (native old.reddit.com) → falls back to RSS → falls back to HTML → falls back to LLM
```

The strategy used is recorded in `metadata.strategy` on each item.

### Modifying queries in Cloud Run

Queries are stored in `queries.json` and externalized to Secret Manager. Changes don't require rebuilding the Docker image.

```bash
# 1. Edit queries.json locally
vim queries.json

# 2. Update only the changed spider (no rebuild)
./deploy_cloud_run.sh --skip-build --spider reddit

# 3. Or update all spiders
./deploy_cloud_run.sh --skip-build

# 4. Verify by running the job manually
gcloud run jobs execute scrapper-reddit --region us-central1

# 5. Check logs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=scrapper-reddit" --limit 30
```

### Adding a new job alias

Same spider, different schedule or queries:

```json
// Add to queries.json:
"reddit-nsfw": {
  "spider": "reddit",
  "schedule": "0 2 * * 0",
  "cloud_run": { "cpu": 1, "memory": "1Gi", "timeout": "30m" },
  "queries": [
    { "subreddit": "BDSMcommunity", "limit": 30, "nsfw": "only" }
  ]
}
```

```bash
./deploy_cloud_run.sh --skip-build --spider reddit-nsfw
```

This creates a new Cloud Run Job + Scheduler using the existing `reddit` spider code. No rebuild needed since the spider code is already in the image.

## Tests

```bash
# All tests
pytest tests/ -v

# Coverage
pytest tests/ --cov=src/scrapper --cov-report=term-missing

# Lint
ruff check src/ tests/
```
