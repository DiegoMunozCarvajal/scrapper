# Web Scraping Platform — Design Spec

**Date:** 2026-04-30
**Status:** Approved
**Goal:** Build a reliable, maintainable multi-site web scraping + crawling platform for structured data collection from Reddit, Quora, MercadoLibre, Amazon, Hotmart (and 10-20 sites eventually).

## Architecture

**Scrapy + scrapy-playwright + Supabase (Postgres).**

Scrapy handles crawling engine concerns (queues, deduplication, rate limiting, retries, middleware). Playwright renders JavaScript-heavy pages via `scrapy-playwright`. Supabase provides cloud-hosted Postgres with auto-generated REST API and a generous free tier. Scrapyd + ScrapydWeb provide deployment, scheduling, and a web UI dashboard.

## Target Sites & Data

| Site | Type | Fields | Browser needed |
|------|------|--------|---------------|
| Reddit | Post | title, url, author, score, content (top comment) | No (old.reddit.com is static) |
| Quora | Post | title, url, author, content | Yes |
| Amazon | Product | title, url, price, currency, rating, review_count | Yes |
| MercadoLibre | Product | title, url, price, currency (COP), rating | Yes |
| Hotmart | Product | title, url, price, currency | Yes |
| Instagram | Post | (future — not in initial scope) | Yes |

- Discovery via search queries (not known URLs)
- Reddit/Quora: summary list + full text of top-voted answer/comment
- Amazon/MercadoLibre/Hotmart: summary search results only (not full product pages initially)

## Scale & Frequency

- Volume: start at hundreds/day, scale to thousands/day
- Modes: batch (daily via ScrapydWeb cron), on-demand (CLI), near-real-time (periodic every 30-60 min)
- Budget: $4-14/month (Hetzner VPS $4 + optional $0-10 datacenter proxy)

## Database Schema

Four tables in Supabase Postgres:

- **sites** — lookup of known target sites (name, type, base_url, active)
- **scrape_jobs** — each run creates a job record (site, query, status, items_scraped, timing)
- **posts** — social/Q&A content with `UNIQUE(site, url)` for upsert dedup
- **products** — e-commerce content with `UNIQUE(site, url)` for upsert dedup

Both items tables have `metadata JSONB` for site-specific fields and `scrape_job_id` FKs for provenance.

## Component Design

### Project Structure
```
scrapper/
├── scrapy.cfg
├── pyproject.toml
├── .env.example
├── docker-compose.yml         # Scrapyd + ScrapydWeb
├── Dockerfile
├── scripts/setup_supabase.sql
└── src/scrapper/
    ├── settings.py             # Scrapy settings
    ├── items.py                # PostItem, ProductItem
    ├── pipelines.py            # Validate → Dedup → Supabase upsert
    ├── middlewares.py           # Retry, Proxy, UA rotation
    ├── extensions.py           # Stats logging, error alerts
    └── spiders/
        ├── reddit.py
        ├── amazon.py
        ├── mercadolibre.py
        ├── hotmart.py
        └── quora.py
```

### Item Pipeline
1. **ValidatePipeline** (priority 100): drops items with missing url/title
2. **DedupInMemoryPipeline** (priority 200): drops items already seen in the same run
3. **SupabasePipeline** (priority 300): upserts into posts/products tables by (site, url) UNIQUE constraint

### Spider Pattern
Each spider: `start_requests()` → yields Scrapy.Request with `meta={"playwright": True}` → parse rendered page with CSS selectors → yields PostItem/ProductItem → follows pagination → stops at limit.

Reddit uses httpx (static HTML, no browser overhead). All others use Playwright.

### Middleware Stack
- **RetryWithBackoffMiddleware** (750): exponential backoff on 429/5xx, max 4 retries
- **ProxyRotationMiddleware** (800): rotates through PROXY_LIST per request
- **UARotationMiddleware** (850): random user agent per request

### Spider-Specific Settings
- `CONCURRENT_REQUESTS = 2`, `DOWNLOAD_DELAY = 2` (baseline)
- `AUTOTHROTTLE_ENABLED = True` (adaptive rate limiting)
- `ROBOTSTXT_OBEY = True`
- Spiders override via `custom_settings` dict for site-specific tuning

## Deployment & Operations

### Infrastructure
- Dev: local machine, `scrapy crawl <spider>` directly
- Prod: single Hetzner VPS ($4/mo) running Docker Compose (Scrapyd + ScrapydWeb)
- Supabase cloud (free tier, 500MB) — no database container needed

### Scheduling
- ScrapydWeb built-in cron for batch jobs
- CLI for on-demand
- ScrapydWeb periodic jobs (30-60 min intervals) for near-real-time

### Monitoring
- ScrapydWeb dashboard: job history, stats, log viewer
- ErrorAlerter extension: POSTs to Discord webhook on spider failures
- Loguru structured JSON logs, rotated weekly
- Health check: poll Scrapyd `/daemonstatus.json`

## Anti-Bot Strategy

Tiered approach matching budget reality:

| Level | Measures | Monthly Cost | Sites |
|-------|----------|-------------|-------|
| L1 — Polite | robots.txt, 2-5s delays, rotating UAs, AutoThrottle | $0 | Reddit, Quora |
| L2 — Basic stealth | L1 + 1 datacenter proxy, random viewport, referer header | $5-10 | MercadoLibre, Hotmart |
| L3 — Playwright stealth | L2 + playwright-stealth plugin, human-like scrolls | $5-10 | Amazon |
| L4 — Residential | L3 + residential rotating proxies, session pools | $100+ | Instagram (future) |

Start at L1-L2. `playwright-stealth` is a pip package. Proxy middleware accepts a `PROXY_LIST` setting — add proxies as needed.

## Future: Incremental Scraping (Week 2+)

Two-tier approach:
1. **Built-in dedup**: `UNIQUE(site, url)` + upsert means re-scraping the same search is harmless (no duplicates in DB)
2. **Delta scraping**: query Supabase for the most recent `scraped_at` per site/query, stop paginating when encountering older items (saves bandwidth at scale)
