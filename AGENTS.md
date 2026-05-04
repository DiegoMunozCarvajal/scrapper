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

# Health check (for Scrapyd)
./bin/health-check.sh
```

## Architecture

**Scrapy + scrapy-playwright + playwright-stealth v2 + curl-cffi + OpenAI + Supabase + portalocker + loguru**

- `src/scrapper/spiders/` — Scrapy spiders (reddit, hotmart, generic, corte, rama + deprecated: amazon, mercadolibre, quora)
- `src/scrapper/spiders/reddit.py` — Triple strategy: RSS discovery → old.reddit.com HTML fallback → LLM extraction. Extracts score, comment_count, published_at, top comment. Incremental scraping via Supabase cutoff date.
- `src/scrapper/spiders/hotmart.py` — Triple strategy: internal API interception (via scrapy-playwright PageMethod) → Playwright DOM fallback → LLM extraction. Extracts price, rating, review_count. Handles pagination via PageMethod load-more clicking.
- `src/scrapper/spiders/generic.py` — Universal spider: curl-cffi → Playwright fallback → LLM extraction with type-hinted prompts. Supports listing, article, product, forum page types.
- `src/scrapper/items.py` — `PostItem`, `ProductItem`, `GenericItem` (with `scraped_at` timestamps in UTC)
- `src/scrapper/pipelines.py` — Validate → DataQuality → Dedup → Supabase upsert (with 3 retries + DropItem on failure)
- `src/scrapper/middlewares.py` — Retry backoff, proxy rotation (incl. Playwright), UA rotation (incl. Playwright)
- `src/scrapper/stealth_handler.py` — Custom Playwright download handler wrapping `playwright-stealth` v2 + canvas/WebGL spoofing + cookie persistence + human simulation (with logging)
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
- `bin/health-check.sh` — Scrapyd health monitoring script
- `scripts/setup_supabase.sql` — DB schema with RLS policies
- `generate_schedule.py` — Generates crontab from `queries.json` for Scrapyd scheduling

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
| `PROXY_LIST` | — | Comma-separated proxy URLs |
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
| `SCHEDULE_ENABLED` | `false` | Enable Scrapyd cron scheduling |
| `RAG_EXPORT_ENABLED` | `true` | Export scraped items as Markdown + JSONL |
| `LOG_LEVEL` | `INFO` | Log verbosity level |
| `ALERT_WEBHOOK_URL` | — | Discord/Slack webhook for error alerts |
| `ALERT_SMTP_HOST` | `smtp.gmail.com` | SMTP host for email alerts |
| `ALERT_SMTP_PORT` | `587` | SMTP port for email alerts |
| `ALERT_EMAIL_FROM` | — | Sender email address |
| `ALERT_EMAIL_PASSWORD` | — | SMTP password (Gmail App Password) |
| `ALERT_EMAIL_TO` | — | Recipient email address |
| `ALERT_ERROR_THRESHOLD` | `5` | Error count to trigger email alert |
| `SCRAPYD_API_URL` | `http://localhost:6800/schedule.json` | Scrapyd API endpoint |

## Testing

- 228 tests passing (items, pipelines, settings, middleware, spiders, stealth, llm_cache, llm_extractor, prompts, curl_cffi, utils, extensions, dashboard, rag_export, generic, pagination)
- 73% coverage (core modules at 80-100%, spiders need Playwright for full coverage)
- Integration tests use fixture files (XML/JSON/HTML) for deterministic offline testing
- `asyncio_mode = "auto"` in pyproject.toml
- Supabase deprecation warnings suppressed via `filterwarnings` in pyproject.toml
- Test structure: `tests/unit/` (unit), `tests/integration/` (spider/config), `tests/fixtures/` (sample data)