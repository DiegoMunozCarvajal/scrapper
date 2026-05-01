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

# Lint
ruff check src/ tests/

# Run a Scrapy spider (primary method)
scrapy crawl reddit -a query="python" -a limit=5 -s ROBOTSTXT_OBEY=False -o results.json
scrapy crawl hotmart -a query="python" -a limit=5 -s ROBOTSTXT_OBEY=False -o results.json
scrapy crawl amazon -a query="laptop" -a limit=5
scrapy crawl mercadolibre -a query="iphone" -a limit=5

# List available spiders
scrapy list

# Health check (for Scrapyd)
./bin/health-check.sh
```

## Architecture

**Scrapy + scrapy-playwright + Supabase**

- `src/scrapper/spiders/` — Scrapy spiders (reddit, amazon, mercadolibre, hotmart, quora)
- `src/scrapper/items.py` — `PostItem`, `ProductItem` (with `scraped_at` timestamps)
- `src/scrapper/pipelines.py` — Validate → Dedup → Supabase upsert
- `src/scrapper/middlewares.py` — Retry backoff, proxy rotation, UA rotation
- `src/scrapper/extensions.py` — StatsLogger, ErrorAlerter webhook
- `src/scrapper/settings.py` — Scrapy settings with Playwright config
- `bin/health-check.sh` — Scrapyd health monitoring script
- `scripts/setup_supabase.sql` — DB schema with RLS policies

## Spider Status

| Spider | Status | Notes |
|--------|--------|-------|
| Reddit | ✅ Works | old.reddit.com, incremental scraping |
| Hotmart | ✅ Works | Playwright, title/author/rating |
| Amazon | ❌ | Needs residential proxies |
| MercadoLibre | ❌ | Needs proxies |
| Quora | ❌ | Cloudflare + login required |

## Testing

- 39 tests passing (items, pipelines, settings, utils)
- 40% coverage
- No integration/playwright tests yet.
- `asyncio_mode = "auto"` in pyproject.toml.