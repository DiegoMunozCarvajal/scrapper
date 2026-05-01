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
scrapy crawl amazon -a query="laptop" -a limit=5
scrapy crawl mercadolibre -a query="iphone" -a limit=5

# List available spiders
scrapy list
```

## Architecture

**Scrapy + scrapy-playwright + Supabase**

- `src/scrapper/spiders/` — Scrapy spiders (reddit, amazon, mercadolibre, hotmart, quora)
- `src/scrapper/items.py` — `PostItem`, `ProductItem`
- `src/scrapper/pipelines.py` — Validate → Dedup → Supabase upsert
- `src/scrapper/middlewares.py` — Retry backoff, proxy rotation, UA rotation
- `src/scrapper/extensions.py` — ErrorAlerter webhook
- `src/scrapper/settings.py` — Scrapy settings with Playwright config

## Spider Notes

| Spider | Browser | Notes |
|--------|---------|-------|
| Reddit | No | Uses `old.reddit.com`, static HTML |
| Quora | Yes | Playwright for JS rendering |
| Amazon | Yes | Playwright, anti-bot sensitive |
| MercadoLibre | Yes | Playwright, `.com.co` |
| Hotmart | Yes | Playwright |

## Testing

- Tests cover items and pipelines (13 passing).
- No integration/playwright tests yet.
- `asyncio_mode = "auto"` in pyproject.toml.