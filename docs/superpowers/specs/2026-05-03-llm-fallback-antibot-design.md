# LLM Fallback + Anti-Bot Hardening Design

> **Goal:** Add LLM-based extraction as third fallback level and harden anti-bot measures with curl-cffi + stealth improvements. Reddit and Hotmart spiders only.

**Architecture:** Seven new modules, two spider modifications, one handler replacement. One new dependency (`openai`); curl-cffi already installed.

**Tech Stack:** Python 3.12+, Scrapy, OpenAI API (gpt-4o-mini), curl-cffi v0.7+, playwright-stealth v2, SQLite

---

## 1. Architecture Overview

### New modules

| File | Responsibility |
|------|---------------|
| `src/scrapper/llm_extractor.py` | Generic LLM extraction via OpenAI — HTML + prompt → structured items |
| `src/scrapper/llm_cache.py` | SQLite cache for LLM responses (per URL+query, TTL 24h) |
| `src/scrapper/prompts/hotmart.py` | Prompt template for Hotmart product extraction |
| `src/scrapper/prompts/reddit.py` | Prompt template for Reddit post extraction |
| `src/scrapper/curl_cffi_handler.py` | Composite download handler: Playwright for JS, curl-cffi for everything else |

### Modified modules

| File | Change |
|------|--------|
| `src/scrapper/spiders/hotmart.py` | Add `_fallback_to_llm()` as 3rd fallback level, `item_class` and `LLM_PROMPT` class attrs |
| `src/scrapper/spiders/reddit.py` | Add `_fallback_to_llm()` as 3rd fallback level, `item_class` and `LLM_PROMPT` class attrs |
| `src/scrapper/stealth_handler.py` | Canvas/WebGL spoofing, human-like scroll, `PLAYWRIGHT_HUMAN_SIMULATION` toggle respected, cookie persistence |
| `src/scrapper/settings.py` | LLM + curl-cffi env vars, new download handler registration |
| `pyproject.toml` | Add `openai>=1.0` dependency |

### Fallback chains

```
Hotmart:  API (parse_api) → Playwright DOM (parse_dom) → [NEW] LLM extraction
Reddit:   RSS (parse_rss) → old.reddit.com HTML (parse) → [NEW] LLM extraction
```

---

## 2. LLM Extractor Details

### `LLMExtractor` class (`llm_extractor.py`)

```python
class LLMExtractor:
    def __init__(self, model="gpt-4o-mini", cache_ttl=86400, cache_path="llm_cache.db")
    def extract(self, html, prompt_template, item_class, site, query) -> list[dict]
    # item_class is a Scrapy Item subclass (PostItem or ProductItem)
    # Field names are extracted from item_class.__init__ signature or .fields
```

Internal flow:
1. Compute `cache_key = sha256(site:query:first_1000_chars_of_html)` → return cached result if valid
2. If HTML > 100K chars, split into semantic chunks via BeautifulSoup (by section/container elements)
3. For each chunk: call OpenAI with `temperature=0`, `response_format={"type": "json_object"}`, `max_tokens=4096`
4. Validate returned dicts against the item class field names — strip unknown fields, keep valid ones
5. Store in cache, return list of dicts

### `LLMCache` class (`llm_cache.py`)

SQLite, one table:
```sql
CREATE TABLE cache (
    key TEXT PRIMARY KEY,
    result TEXT,          -- JSON string
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```
- TTL configurable via `LLM_CACHE_TTL` (default 86400s / 24h)
- Path via `LLM_CACHE_PATH` (default `llm_cache.db`)
- `get(key)` → returns parsed JSON or None if expired
- `set(key, value)` → upsert with current timestamp

### Combined strategy: page → item

1. **Page-level:** Send full HTML to LLM asking for all items at once
2. **Item-level (fallback):** If page-level returns 0 or fewer items than expected, extract individual card/container HTML sections and retry one at a time

### OpenAI config

| Parameter | Value | Note |
|-----------|-------|------|
| Model | `gpt-4o-mini` | $0.15/1M input, $0.60/1M output tokens |
| Temperature | `0` | Deterministic extraction |
| Max tokens | `4096` | ~50 items per call |
| Cost per page | ~$0.002 | 50K char HTML ≈ 12K input tokens |

### Env vars

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | OpenAI API key (required for LLM fallback) |
| `LLM_MODEL` | `gpt-4o-mini` | Model to use |
| `LLM_CACHE_TTL` | `86400` | Cache TTL in seconds |
| `LLM_CACHE_PATH` | `llm_cache.db` | SQLite cache file path |
| `LLM_ENABLED` | `true` | Global toggle to disable LLM fallback |

---

## 3. Prompt Templates

### Hotmart (`prompts/hotmart.py`)

Fields extracted: `title`, `url`, `price`, `rating`, `review_count`, `seller`

```
HOTMART_PROMPT = """\
You are a web scraper assistant. Extract product information from this HTML page
of Hotmart marketplace search results.

For each product found, extract these fields:
- title: the product name (string)
- url: the product page URL / href (string)
- price: the numeric price value, e.g. 49.99 (float or null)
- rating: the numeric rating, e.g. 4.5 (float or null, 1-5 scale)
- review_count: number of reviews as integer, e.g. 234 (int or 0)
- seller: the author/seller name (string or "")

Rules:
- Ignore banners, ads, navigation, and footer content
- If a field is not found, use "" for strings, 0 for integers, null for floats
- Only extract products that appear as cards in the search results

Return a JSON object with a "products" key containing an array of objects:
{"products": [{"title": "Example Course", "url": "...", "price": 49.99, ...}]}

HTML:
{html}"""
```

### Reddit (`prompts/reddit.py`)

Fields extracted: `title`, `url`, `author`, `score`, `comment_count`, `published_at`

```
REDDIT_PROMPT = """\
You are a web scraper assistant. Extract Reddit posts from this search results
page on old.reddit.com.

For each post found, extract these fields:
- title: the post title (string)
- url: the post URL, relative or absolute (string)
- author: username of the poster, e.g. "u/someuser" (string)
- score: upvote count as integer, e.g. 142 (int or 0)
- comment_count: number of comments as integer, e.g. 23 (int or 0)
- published_at: date in ISO 8601 format if available (string or null)

Rules:
- Ignore promoted posts, ads, and sticky/pinned content
- If a field is not found, use "" for strings, 0 for integers, null for dates
- Only extract posts from the search results listing, not the sidebar

Return a JSON object with a "posts" key containing an array of objects:
{"posts": [{"title": "...", "url": "...", "author": "u/...", "score": 142, ...}]}

HTML:
{html}"""
```

---

## 4. Anti-Bot Details

### 4a. `CurlCffiDownloadHandler` (`curl_cffi_handler.py`)

Composite handler extending `ScrapyPlaywrightStealthDownloadHandler`:

- **Playwright requests** (`meta["playwright"]=True`): delegates to parent class (unchanged)
- **Regular requests**: uses `curl_cffi.requests.Session` with Chrome 124 impersonation via `twisted.internet.threads.deferToThread`
- Fingerprint configurable via `CURL_CFFI_IMPERSONATE` env var (default `chrome124`)
- `CURL_CFFI_ENABLED=false` disables the handler at registration time in `settings.py` (falls back to default Scrapy HTTP handler)
- Graceful fallback: if curl-cffi import fails at runtime, logs warning and delegates to default Scrapy HTTP handler

Registered in `settings.py`:
```python
DOWNLOAD_HANDLERS = {
    "http": "scrapper.curl_cffi_handler.CurlCffiDownloadHandler",
    "https": "scrapper.curl_cffi_handler.CurlCffiDownloadHandler",
}
```

### 4b. Stealth handler improvements (`stealth_handler.py`)

| Improvement | Technique | Detail |
|-------------|-----------|--------|
| Canvas spoofing | `page.add_init_script()` | Adds subtle random noise to `toDataURL()` and `getImageData()` |
| WebGL spoofing | `page.add_init_script()` | Overrides `WEBGL_debug_renderer_info` to hide real GPU vendor |
| Human-like scroll | `page.evaluate()` with variable timing | 2-4 scrolls with random pauses (200-800ms), varying speed |
| Toggle enforced | `os.getenv("PLAYWRIGHT_HUMAN_SIMULATION")` | Scroll + init scripts only execute when toggle is `true` |
| Cookie persistence | `context.storage_state()` | Save/load cookies in `cookies/{spider_name}.json` between runs |
| Extra launch args | `PLAYWRIGHT_LAUNCH_OPTIONS["args"]` | Add `--disable-features=IsolateOrigins`, `--disable-site-isolation-trials` |

### Env vars

| Variable | Default | Description |
|----------|---------|-------------|
| `CURL_CFFI_IMPERSONATE` | `chrome124` | Fingerprint to impersonate |
| `CURL_CFFI_ENABLED` | `true` | Toggle curl-cffi handler |
| `COOKIE_PERSIST_ENABLED` | `true` | Enable cookie persistence between runs |

---

## 5. Spider Integration

### Hotmart (`hotmart.py`)

Activation point: `parse_dom()` — when CSS selectors iterate all cards and `count == 0`:

```python
# hotmart.py
from ..llm_extractor import llm_fallback

def parse_dom(self, response):
    # ... existing CSS selector extraction ...
    if count == 0:
        self.logger.warning("DOM selectors found nothing, trying LLM fallback")
        yield from llm_fallback(self, response, ProductItem)
        return
```

New class attributes:
```python
class HotmartSpider(scrapy.Spider):
    item_class = ProductItem
    LLM_PROMPT = HOTMART_PROMPT
```

### Reddit (`reddit.py`)

Activation point: `parse()` — when `div.search-result-link` selectors yield `count == 0`:

```python
# reddit.py
from ..llm_extractor import llm_fallback

def parse(self, response):
    # ... existing CSS selector extraction ...
    if count == 0:
        self.logger.warning("HTML selectors found nothing, trying LLM fallback")
        yield from llm_fallback(self, response, PostItem)
        return
```

New class attributes:
```python
class RedditSpider(scrapy.Spider):
    item_class = PostItem
    LLM_PROMPT = REDDIT_PROMPT
```

### Shared `_fallback_to_llm()` method

To avoid duplicating logic, a standalone `llm_fallback` function in `llm_extractor.py` is called by both spiders:

```python
# llm_extractor.py
def llm_fallback(spider, response, item_class):
    """Shared LLM fallback for any spider. Yields item_class instances."""
    import os
    if not os.getenv("OPENAI_API_KEY") or os.getenv("LLM_ENABLED") == "false":
        spider.logger.warning("LLM fallback disabled or no API key, skipping")
        return

    query = response.meta["query"]
    limit = response.meta.get("limit", 10)
    extractor = LLMExtractor()

    items = extractor.extract(
        html=response.text,
        prompt_template=spider.LLM_PROMPT,
        item_class=item_class,
        site=spider.site,
        query=query,
    )

    for item in items[:limit]:
        item["metadata"]["strategy"] = "llm"
        item["metadata"]["query"] = query
        yield item_class(item)
```

Each spider adds the class attribute and calls the shared function:

```python
# hotmart.py
class HotmartSpider(scrapy.Spider):
    item_class = ProductItem
    LLM_PROMPT = HOTMART_PROMPT

# In parse_dom():
    yield from llm_fallback(self, response, ProductItem)

# reddit.py
class RedditSpider(scrapy.Spider):
    item_class = PostItem
    LLM_PROMPT = REDDIT_PROMPT

# In parse():
    yield from llm_fallback(self, response, PostItem)
```

### Behavior guarantees

- **LLM is fallback, not replacement.** CSS selectors and API remain primary strategies
- **Silent degradation.** No API key or `LLM_ENABLED=false` → spider runs as before
- **LLM failure is non-fatal.** API errors, invalid JSON, empty responses → logged, spider continues

---

## 6. Error Handling

### LLM Extractor error matrix

| Error type | Handling | Spider impact |
|-----------|----------|---------------|
| `openai.RateLimitError` | Log warning, return `[]` | Skips LLM, continues normally |
| `openai.AuthenticationError` | Log error, return `[]` | Skips LLM permanently for this run |
| `openai.APIError` | Log error, return `[]` | Skips LLM, continues normally |
| `json.JSONDecodeError` | Retry once, then return `[]` | Skips LLM after retry |
| `sqlite3.OperationalError` (cache) | Log warning, bypass cache | Works without cache |
| HTML > 500K chars | Truncate to 500K | May lose content, logged |

### Curl-cffi handler error matrix

| Error | Handling |
|-------|----------|
| ImportError (curl-cffi missing) | Log warning, fallback to default Scrapy HTTP handler |
| Network error | Retry via Scrapy's built-in retry middleware |
| TLS error | Retry with next proxy if available |
| Thread pool exhaustion | Queue with timeout (30s) |

### Stealth handler error matrix

| Error | Handling |
|-------|----------|
| Script injection fails | Log debug, continue without spoofing |
| Scroll fails (page closed) | Silent pass, already handled in current code |
| Cookie save/load fails | Log warning, continue without persistence |

---

## 7. Testing Strategy

### Unit tests (new files)

| Test file | What it tests | Mock strategy |
|-----------|--------------|---------------|
| `tests/unit/test_llm_extractor.py` | Extraction, chunking, validation, caching | `unittest.mock.patch("openai.OpenAI")` |
| `tests/unit/test_llm_cache.py` | SQLite CRUD, TTL, collision, corruption | `tmp_path` fixture |
| `tests/unit/test_curl_cffi_handler.py` | Handler creation, routing logic, graceful degradation | Mock `curl_cffi.requests` |
| `tests/unit/test_stealth_enhanced.py` | Canvas/WebGL scripts injected, scroll toggle respected | Mock Playwright page |

### Test fixtures (new)

```
tests/fixtures/
  hotmart_search.html           # Real Hotmart search page HTML
  old_reddit_search.html        # Real old.reddit.com search HTML
  llm_hotmart_response.json     # Mock LLM response for Hotmart
  llm_reddit_response.json      # Mock LLM response for Reddit
```

### Integration tests

| Test | What it verifies |
|------|-----------------|
| Spider fallback chain | Mocked LLM extractor yields items when selectors fail |
| LLM extractor with fixture HTML | Correct fields extracted from known HTML |
| Curl-cffi handler routing | Playwright requests go to Playwright, regular to curl-cffi |
| Cache hit/miss | Second call with same HTML skips OpenAI API |

### Coverage target

80%+ on new modules (`llm_extractor.py`, `llm_cache.py`, `curl_cffi_handler.py`), matching the project's core module standard.

---

## 8. Migration & Rollback

- All new features are **opt-in via env vars** (`LLM_ENABLED`, `OPENAI_API_KEY`, `CURL_CFFI_ENABLED`)
- Without `OPENAI_API_KEY`, behavior is identical to current version
- Setting `CURL_CFFI_ENABLED=false` restores original download handler
- `LLM_ENABLED=false` disables the entire LLM fallback path
- No database migrations — LLM cache is a new SQLite file, cookies are new JSON files
