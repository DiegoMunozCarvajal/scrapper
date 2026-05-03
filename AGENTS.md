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

# Health check (for Scrapyd)
./bin/health-check.sh
```

## Architecture

**Scrapy + scrapy-playwright + playwright-stealth v2 + curl-cffi + OpenAI + Supabase**

- `src/scrapper/spiders/` — Scrapy spiders (reddit, hotmart + deprecated: amazon, mercadolibre, quora)
- `src/scrapper/spiders/reddit.py` — Triple strategy: RSS discovery → old.reddit.com HTML fallback → LLM extraction. Extracts score, comment_count, published_at, top comment.
- `src/scrapper/spiders/hotmart.py` — Triple strategy: internal API interception → Playwright DOM fallback → LLM extraction. Extracts price, rating, review_count. Handles pagination.
- `src/scrapper/items.py` — `PostItem`, `ProductItem` (with `scraped_at` timestamps)
- `src/scrapper/pipelines.py` — Validate → DataQuality → Dedup → Supabase upsert
- `src/scrapper/middlewares.py` — Retry backoff, proxy rotation (incl. Playwright), UA rotation (incl. Playwright)
- `src/scrapper/stealth_handler.py` — Custom Playwright download handler wrapping `playwright-stealth` v2 + canvas/WebGL spoofing + cookie persistence
- `src/scrapper/curl_cffi_handler.py` — Composite download handler: Playwright for JS, curl-cffi with TLS impersonation for everything else
- `src/scrapper/llm_extractor.py` — `LLMExtractor` class (OpenAI gpt-4o-mini, JSON mode, SQLite cache) + shared `llm_fallback()` function
- `src/scrapper/llm_cache.py` — SQLite cache with TTL expiry for LLM responses
- `src/scrapper/prompts/` — Prompt templates per site (hotmart.py, reddit.py)
- `src/scrapper/extensions.py` — StatsLogger, EmailAlerter with anomaly detection
- `src/scrapper/dashboard.py` — Static HTML metrics dashboard
- `src/scrapper/rag_export.py` — Markdown + JSONL export pipelines for RAG/vector DBs
- `src/scrapper/settings.py` — Scrapy settings, Playwright config, env-driven headless/human simulation toggles, LLM + curl-cffi config
- `bin/health-check.sh` — Scrapyd health monitoring script
- `scripts/setup_supabase.sql` — DB schema with RLS policies

## Spider Status

| Spider | Status | Strategy | Notes |
|--------|--------|----------|-------|
| Reddit | ✅ Works | RSS → HTML fallback → LLM | old.reddit.com, incremental scraping, score/comments/published_at |
| Hotmart | ✅ Works | API → Playwright fallback → LLM | Playwright for API discovery, price/review extraction, pagination |
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
| `PLAYWRIGHT_HUMAN_SIMULATION` | `true` | Enable random scroll/delay + canvas/WebGL spoofing |
| `OPENAI_API_KEY` | — | OpenAI API key for LLM fallback extraction |
| `LLM_ENABLED` | `true` | Enable LLM extraction fallback |
| `LLM_MODEL` | `gpt-4o-mini` | OpenAI model for extraction |
| `LLM_CACHE_TTL` | `86400` | LLM response cache TTL in seconds |
| `LLM_CACHE_PATH` | `llm_cache.db` | SQLite cache file path |
| `CURL_CFFI_ENABLED` | `true` | Use curl-cffi with TLS impersonation |
| `CURL_CFFI_IMPERSONATE` | `chrome124` | Browser fingerprint to impersonate |
| `COOKIE_PERSIST_ENABLED` | `true` | Persist cookies between runs |

## Testing

- 165 tests passing (items, pipelines, settings, middleware, spiders, stealth, llm_cache, llm_extractor, prompts, curl_cffi)
- 41% coverage (core modules at 80-100%, spiders need Playwright for full coverage)
- Integration tests use fixture files (XML/JSON/HTML) for deterministic offline testing
- `asyncio_mode = "auto"` in pyproject.toml
- Test structure: `tests/unit/` (unit), `tests/integration/` (spider/config), `tests/fixtures/` (sample data)