# AGENTS.md

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
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

# Run with visible browser (debugging)
HEADLESS=false scrapy crawl hotmart -a query="python" -a limit=5

# Disable human simulation (faster but more detectable)
PLAYWRIGHT_HUMAN_SIMULATION=false scrapy crawl hotmart -a query="python" -a limit=5

# Deprecated spiders (emit warning on run)
scrapy crawl amazon -a query="laptop" -a limit=5
scrapy crawl mercadolibre -a query="iphone" -a limit=5
scrapy crawl quora -a query="startups" -a limit=5

# List available spiders
scrapy list

# Coverage report
pytest tests/ --cov=src/scrapper --cov-report=term-missing

# Health check (for Scrapyd)
./bin/health-check.sh
```

## Architecture

**Scrapy + scrapy-playwright + playwright-stealth v2 + Supabase**

- `src/scrapper/spiders/` — Scrapy spiders (reddit, hotmart + deprecated: amazon, mercadolibre, quora)
- `src/scrapper/spiders/reddit.py` — Dual strategy: RSS discovery → old.reddit.com HTML fallback. Extracts score, comment_count, published_at, top comment.
- `src/scrapper/spiders/hotmart.py` — Dual strategy: internal API interception → Playwright DOM fallback. Extracts price, rating, review_count. Handles pagination.
- `src/scrapper/items.py` — `PostItem`, `ProductItem` (with `scraped_at` timestamps)
- `src/scrapper/pipelines.py` — Validate → Dedup → Supabase upsert
- `src/scrapper/middlewares.py` — Retry backoff, proxy rotation (incl. Playwright), UA rotation (incl. Playwright)
- `src/scrapper/stealth_handler.py` — Custom Playwright download handler wrapping `playwright-stealth` v2
- `src/scrapper/extensions.py` — StatsLogger, ErrorAlerter webhook
- `src/scrapper/settings.py` — Scrapy settings, Playwright config, env-driven headless/human simulation toggles
- `bin/health-check.sh` — Scrapyd health monitoring script
- `scripts/setup_supabase.sql` — DB schema with RLS policies

## Spider Status

| Spider | Status | Strategy | Notes |
|--------|--------|----------|-------|
| Reddit | ✅ Works | RSS → HTML fallback | old.reddit.com, incremental scraping, score/comments/published_at |
| Hotmart | ✅ Works | API → Playwright fallback | Playwright for API discovery, price/review extraction, pagination |
| Amazon | ⛔ Deprecated | — | Needs residential proxies |
| MercadoLibre | ⛔ Deprecated | — | Needs residential proxies |
| Quora | ⛔ Deprecated | — | Cloudflare + login + residential proxies required |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SUPABASE_URL` | — | Supabase project URL |
| `SUPABASE_KEY` | — | Supabase service role key |
| `PROXY_LIST` | — | Comma-separated proxy URLs |
| `ALERT_WEBHOOK_URL` | — | Discord/Slack webhook for error alerts |
| `HEADLESS` | `true` | Run Playwright in headless mode |
| `PLAYWRIGHT_HUMAN_SIMULATION` | `true` | Enable random scroll/delay simulation |

## Testing

- 75 tests passing (items, pipelines, settings, middleware, spiders, stealth)
- 41% coverage (core modules at 80-100%, spiders need Playwright for full coverage)
- Integration tests use fixture files (XML/JSON/HTML) for deterministic offline testing
- `asyncio_mode = "auto"` in pyproject.toml
- Test structure: `tests/unit/` (unit), `tests/integration/` (spider/config), `tests/fixtures/` (sample data)