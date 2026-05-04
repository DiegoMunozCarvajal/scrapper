# scrapper

Multi-site web scraper built on **Scrapy + Playwright + curl-cffi + OpenAI + Supabase**.

Active spiders: Reddit, Hotmart. Deprecated: Amazon, Mercado Libre, Quora.

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
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

```bash
docker-compose up -d
```

Scheduled jobs via `scrapyd.conf`:
- Reddit: every 6 hours
- Hotmart: 8 AM and 8 PM daily

Health monitoring: `./bin/health-check.sh`

## Tests

```bash
# All tests
pytest tests/ -v

# Coverage
pytest tests/ --cov=src/scrapper --cov-report=term-missing

# Lint
ruff check src/ tests/
```
