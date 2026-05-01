# Scraper Overhaul — Reddit & Hotmart Enhancement

**Date:** 2026-05-01
**Status:** Approved

---

## 1. Goal

Comprehensive overhaul of the scrapper focusing on the two working spiders (Reddit, Hotmart). Fix critical bugs, add dual-strategy data extraction (fast API/RSS path + Playwright fallback), upgrade the anti-bot stealth stack, add integration tests, and deprecate broken spiders.

## 2. Non-Goals

- Fixing Amazon, MercadoLibre, or Quora (require residential proxies)
- Changing the Supabase schema or pipelines
- Adding new spiders or target sites
- Real-time/streaming scraping

## 3. Architecture

```
┌─ Spider ────────────────────────────────────────┐
│  Strategy 1: Lightweight (RSS / JSON API)       │
│  Strategy 2: Playwright-rendered DOM scraping   │
│  (Strategy 2 fires only when Strategy 1 fails)  │
├─ Middlewares ───────────────────────────────────┤
│  RetryWithBackoff, ProxyRotation (incl. PW),    │
│  UARotation (incl. PW override)                 │
├─ Pipelines ─────────────────────────────────────┤
│  Validate → DedupInMemory → Supabase (no change)│
└─────────────────────────────────────────────────┘
```

No new framework. Scrapy stays. Stealth layer upgraded from `scrapy-playwright-stealth` to custom integration with `playwright-stealth` v2.

## 4. Reddit Spider

### 4.1 Bug fix
Move `parse_post` (currently module-level function at line 73) into the `RedditSpider` class as `parse_post_page` method. It currently references `self.cutoff_date` which only works inside a class.

### 4.2 Strategy 1 — RSS Discovery
- Fetch `https://www.reddit.com/search.rss?q={query}&sort=relevance`
- Parse XML with `feedparser` (new dependency)
- Extract: `title`, `link` (url), `author`, `published` (datetime)
- Yield lightweight `PostItem` objects (score/comment_count/content not in RSS)
- Paginate via RSS `?after=` parameter

### 4.3 Strategy 2 — old.reddit.com HTML (fallback)
- Keep current search result scraping as fallback
- CSS selectors remain the same
- Follow detail pages for `content` + `top_comment`
- **New:** extract `score` from `.score`, `comment_count` from `.comments`, `published_at` from `<time>`

### 4.4 New fields extracted

| Field | Source | Strategy |
|-------|--------|----------|
| `score` | `.score::text` | Strategy 2 |
| `comment_count` | `.comments::text` | Strategy 2 |
| `published_at` | `time[datetime]` | Both |

### 4.5 Graceful degradation
- If content div missing → yield item with title+url only (no crash)
- If score/comment_count missing → leave as 0 (no crash)
- If cutoff date loading fails → log warning, proceed without cutoff

### 4.6 Rate limiting
- `DOWNLOAD_DELAY=2` already set, extend to detail page requests
- Max one concurrent request (already set)

## 5. Hotmart Spider

### 5.1 Strategy 1 — Internal API Interception
- Use Playwright's `page.route()` on a single warm-up page load to identify API endpoints
- Expected: GraphQL query to `/graphql` or REST to `/api/v1/search`
- Once identified, send direct HTTP requests to the API endpoint with proper headers
- Parse JSON response → extract all product fields including price
- Paginate via API query params (`?page=2`, `offset=20`, etc.)

### 5.2 Strategy 2 — Playwright DOM scraping (fallback)
- Keep current card-based extraction as fallback
- **Fix:** extract price from `.product-card-alt__price` or equivalent selector
- **New:** extract `review_count` from review text element
- **New:** handle "Load more" / infinite scroll for pagination
- **New:** `_parse_price()` called with actual price text

### 5.3 New fields extracted

| Field | Source | Strategy |
|-------|--------|----------|
| `price` | API JSON or DOM `.product-card-alt__price` | Both |
| `review_count` | API JSON or DOM review element | Both |

### 5.4 API endpoint discovery procedure
1. Navigate to search page with Playwright (headless)
2. Intercept all XHR/fetch requests for 10 seconds
3. Filter for URLs containing "search", "product", "graphql", "api"
4. Log candidates, try each with `requests.get()` (no Playwright needed)
5. Cache the working endpoint URL for subsequent runs
6. If no API endpoint found → fall back to Strategy 2

## 6. Stealth & Anti-Bot Stack

### 6.1 Dependencies

| Remove | Add |
|--------|-----|
| `scrapy-playwright-stealth>=0.1` | `playwright-stealth>=2.0` |
| — | `curl-cffi>=0.7` (optional, TLS bypass) |
| — | `feedparser>=6.0` (RSS parsing for Reddit) |

### 6.2 Custom Playwright stealth download handler
- Create `src/scrapper/stealth_handler.py`
- Wraps `playwright-stealth` v2's `Stealth().use_async()` as a Scrapy download handler
- Replaces current `DOWNLOAD_HANDLERS` config
- Applies: `navigator.webdriver` removal, WebGL spoofing, plugin normalization, language/font masking
- Browser launch args: `--disable-blink-features=AutomationControlled`

### 6.3 Proxy injection for Playwright
- `ProxyRotationMiddleware.process_request()` currently skips Playwright requests
- **Fix:** When `request.meta.get("playwright")` and proxies available, set `request.meta["playwright_context_kwargs"]["proxy"] = {"server": proxy_url}`

### 6.4 UA rotation update
- Chrome 130+, Firefox 130+, Safari 17+, mobile UAs
- For Playwright requests: set via context kwargs or `page.set_extra_http_headers()`

### 6.5 Human behavior simulation (Playwright only)
- Random scroll on page load: `page.evaluate("window.scrollBy(0, {random})")`
- Random delays between interactions: 1–3s base + jitter
- Configurable via `settings.py`: `PLAYWRIGHT_HUMAN_SIMULATION = True`

### 6.6 Headless mode
- Configurable via `HEADLESS` env var
- `settings.py`: read env var, default `True`

### 6.7 Cookie persistence
- Keep current file-based persistence
- Add: rotate between cookie sets per run to avoid session fingerprinting

### 6.8 TLS fingerprint bypass (optional, non-Playwright)
- For RSS and API calls, use `curl_cffi` to impersonate Chrome TLS fingerprint
- Wrapped in a utility function `tls_aware_request(url)` in `utils.py`

## 7. Broken Spiders

| Spider | Action |
|--------|--------|
| Amazon (`amazon.py`) | Add class attribute `DEPRECATED = True`. Emit `logger.warning` with explanation on run. Keep code. |
| MercadoLibre (`mercadolibre.py`) | Same as Amazon |
| Quora (`quora.py`) | Same as Amazon |

The spider list (`scrapy list`) should still show them, but running them emits a clear deprecation warning with the reason ("Needs residential proxies").

## 8. Testing

### 8.1 Reorganize tests
```
tests/
├── unit/
│   ├── test_items.py
│   ├── test_pipelines.py
│   ├── test_extensions.py
│   ├── test_middlewares.py      # NEW
│   └── test_utils.py
├── integration/
│   ├── conftest.py              # NEW: Scrapy test fixtures
│   ├── test_reddit_spider.py    # NEW
│   ├── test_hotmart_spider.py   # NEW
│   └── test_stealth.py          # NEW
└── fixtures/
    ├── reddit_search.html
    ├── reddit_rss.xml
    ├── hotmart_api_response.json
    └── hotmart_search.html
```

### 8.2 New test cases (minimum)

| File | Tests |
|------|-------|
| `test_middlewares.py` | Retry backoff calculates correct delays; UA rotation picks from list; proxy middleware sets meta for both regular and Playwright requests |
| `test_reddit_spider.py` | RSS parsing yields PostItems; HTML fallback fires when RSS empty; `parse_post_page` extracts all fields; graceful degradation on missing selectors; cutoff date filtering; pagination follows next link |
| `test_hotmart_spider.py` | API response parsing yields ProductItems with prices; DOM fallback extracts cards; `_parse_price` handles various currency formats; pagination via API params; pagination via "Load more" click |
| `test_stealth.py` | Playwright context created with stealth patches; context args include `--disable-blink-features`; proxy injected into context kwargs; UA rotation sets correct headers |

### 8.3 Test approach
- Use `responses` or `httpx` mocks for HTTP requests
- Use `pytest-playwright` for browser tests (or mock Playwright context)
- Fixture files: saved HTML/JSON from real pages for deterministic offline tests
- Coverage target: 70%+ (from current 40%)

## 9. Files Changed

| File | Change |
|------|--------|
| `src/scrapper/spiders/reddit.py` | Bug fix + RSS + field extraction + graceful degradation |
| `src/scrapper/spiders/hotmart.py` | API interception + pagination + price extraction |
| `src/scrapper/spiders/amazon.py` | Add deprecation notice |
| `src/scrapper/spiders/mercadolibre.py` | Add deprecation notice |
| `src/scrapper/spiders/quora.py` | Add deprecation notice |
| `src/scrapper/settings.py` | New download handler, updated PLAYWRIGHT config |
| `src/scrapper/middlewares.py` | Proxy injection for Playwright, updated UAs |
| `src/scrapper/stealth_handler.py` | **NEW** — custom download handler with playwright-stealth v2 |
| `src/scrapper/utils.py` | Add `tls_aware_request()` and `_parse_price` (moved from hotmart.py) |
| `pyproject.toml` | Updated dependencies |
| `tests/` | Reorganized + new integration tests + fixtures |

## 10. Rollout Order

1. Fix the `parse_post` bug (critical — crashes on post detail pages)
2. Upgrade stealth stack (new handler + deps)
3. Reddit: RSS discovery + field extraction
4. Hotmart: API discovery + price extraction + pagination
5. Fix proxy middleware for Playwright
6. Deprecate broken spiders
7. Reorganize tests + add integration tests

Each step is independently testable and mergeable.
