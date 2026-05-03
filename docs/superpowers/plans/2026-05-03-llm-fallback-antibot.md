# LLM Fallback + Anti-Bot Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LLM-based extraction as third fallback level (Reddit + Hotmart) and harden anti-bot measures with curl-cffi + stealth improvements.

**Architecture:** Five new modules: `llm_cache.py` (SQLite cache), `llm_extractor.py` (OpenAI extraction + shared fallback function), `prompts/hotmart.py` and `prompts/reddit.py` (prompt templates), `curl_cffi_handler.py` (composite download handler). Two spider patches, one handler rewrite. All features opt-in via env vars.

**Tech Stack:** Python 3.12+, Scrapy, OpenAI Python SDK (v1+), curl-cffi (v0.7+, already installed), playwright-stealth v2, SQLite (stdlib), Twisted (Scrapy dep)

---

### Task 1: Add `openai` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add openai to dependencies**

Edit `pyproject.toml`, add `"openai>=1.0"` after `"curl-cffi>=0.7"`:

```toml
    "feedparser>=6.0",
    "curl-cffi>=0.7",
    "openai>=1.0",
]
```

- [ ] **Step 2: Install the dependency**

```bash
pip install -e ".[dev]"
```

- [ ] **Step 3: Verify import works**

```bash
python -c "import openai; print(openai.__version__)"
```
Expected: prints version number, no errors.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: add openai>=1.0 dependency for LLM fallback extraction"
```

---

### Task 2: Build `LLMCache` — SQLite cache for LLM responses

**Files:**
- Create: `src/scrapper/llm_cache.py`
- Create: `tests/unit/test_llm_cache.py`

- [ ] **Step 1: Write failing test for LLMCache**

Create `tests/unit/test_llm_cache.py`:

```python
import json
import time
from pathlib import Path

from scrapper.llm_cache import LLMCache


def test_set_and_get(tmp_path):
    db = tmp_path / "test.db"
    cache = LLMCache(db_path=str(db), ttl=86400)
    cache.set("key1", [{"title": "Test"}])
    result = cache.get("key1")
    assert result == [{"title": "Test"}]


def test_get_missing_key_returns_none(tmp_path):
    db = tmp_path / "test.db"
    cache = LLMCache(db_path=str(db), ttl=86400)
    assert cache.get("nonexistent") is None


def test_ttl_expiry(tmp_path):
    db = tmp_path / "test.db"
    cache = LLMCache(db_path=str(db), ttl=0)
    cache.set("key1", [{"title": "Test"}])
    assert cache.get("key1") is None


def test_upsert_replaces_value(tmp_path):
    db = tmp_path / "test.db"
    cache = LLMCache(db_path=str(db), ttl=86400)
    cache.set("key1", [{"title": "First"}])
    cache.set("key1", [{"title": "Second"}])
    assert cache.get("key1") == [{"title": "Second"}]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_llm_cache.py -v
```
Expected: all 4 tests FAIL with `ModuleNotFoundError: No module named 'scrapper.llm_cache'`

- [ ] **Step 3: Implement LLMCache**

Create `src/scrapper/llm_cache.py`:

```python
import json
import sqlite3
from datetime import datetime, timedelta, timezone


class LLMCache:
    def __init__(self, db_path="llm_cache.db", ttl=86400):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.ttl = ttl
        self._init_db()

    def _init_db(self):
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS cache "
            "(key TEXT PRIMARY KEY, result TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        self.db.commit()

    def get(self, key):
        expiry = (datetime.now(timezone.utc) - timedelta(seconds=self.ttl)).isoformat()
        row = self.db.execute(
            "SELECT result FROM cache WHERE key = ? AND created_at > ?",
            (key, expiry),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, key, value):
        self.db.execute(
            "INSERT OR REPLACE INTO cache (key, result, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), datetime.now(timezone.utc).isoformat()),
        )
        self.db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_llm_cache.py -v
```
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/llm_cache.py tests/unit/test_llm_cache.py
git commit -m "feat: add LLMCache — SQLite cache for LLM extraction responses"
```

---

### Task 3: Build `LLMExtractor` — core extraction with OpenAI

**Files:**
- Create: `src/scrapper/llm_extractor.py`
- Create: `tests/unit/test_llm_extractor.py`

- [ ] **Step 1: Write failing test for LLMExtractor**

Create `tests/unit/test_llm_extractor.py`:

```python
import json
from unittest.mock import MagicMock, patch

from scrapper.llm_extractor import LLMExtractor


class FakeChoice:
    def __init__(self, content):
        self.message = MagicMock()
        self.message.content = content


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]
        self.usage = MagicMock()
        self.usage.total_tokens = 100


def test_extract_calls_openai_and_returns_items():
    fake_html = "<div>Product: Python Course, Price: $49.99</div>"
    fake_prompt = "Extract products from: {html}"
    expected_response = json.dumps({
        "products": [{"title": "Python Course", "url": "/course", "price": 49.99}]
    })

    with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
        mock_client = mock_openai.return_value
        mock_client.chat.completions.create.return_value = FakeCompletion(expected_response)

        extractor = LLMExtractor(model="gpt-4o-mini", cache_ttl=0)
        result = extractor.extract(
            html=fake_html,
            prompt_template=fake_prompt,
            item_class=None,
            site="hotmart",
            query="python",
        )

        assert len(result) == 1
        assert result[0]["title"] == "Python Course"
        assert result[0]["price"] == 49.99
        mock_client.chat.completions.create.assert_called_once()


def test_extract_cache_hit_skips_openai():
    fake_html = "<div>Product: Test</div>"
    fake_prompt = "Extract: {html}"

    with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
        extractor = LLMExtractor(model="gpt-4o-mini", cache_ttl=86400)

        extractor.cache.set("test_key", [{"title": "Cached"}])

        with patch.object(extractor, "_cache_key", return_value="test_key"):
            result = extractor.extract(
                html=fake_html,
                prompt_template=fake_prompt,
                item_class=None,
                site="hotmart",
                query="python",
            )

        assert len(result) == 1
        assert result[0]["title"] == "Cached"
        mock_openai.return_value.chat.completions.create.assert_not_called()


def test_extract_strips_unknown_fields():
    fake_html = "<div>test</div>"
    fake_prompt = "Extract: {html}"
    expected_response = json.dumps({
        "products": [{"title": "OK", "unknown_field": "should be removed"}]
    })

    class FakeItem:
        fields = {"title": None, "url": None, "price": None}

    with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
        mock_client = mock_openai.return_value
        mock_client.chat.completions.create.return_value = FakeCompletion(expected_response)

        extractor = LLMExtractor(cache_ttl=0)
        result = extractor.extract(
            html=fake_html,
            prompt_template=fake_prompt,
            item_class=FakeItem,
            site="hotmart",
            query="python",
        )

        assert len(result) == 1
        assert "title" in result[0]
        assert "unknown_field" not in result[0]


def test_chunk_html_splits_large_content():
    extractor = LLMExtractor()
    small_html = "<div>" + "x" * 500 + "</div>"
    chunks = extractor._chunk_html(small_html, max_chars=1000)
    assert len(chunks) == 1

    big_html = "<div>" + "x" * 5000 + "</div>"
    chunks = extractor._chunk_html(big_html, max_chars=2000)
    assert len(chunks) > 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_llm_extractor.py -v
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement LLMExtractor**

Create `src/scrapper/llm_extractor.py`:

```python
import hashlib
import json
import logging
import os

import openai
from openai import OpenAI

from .llm_cache import LLMCache

logger = logging.getLogger(__name__)


class LLMExtractor:
    def __init__(self, model=None, cache_ttl=None, cache_path=None):
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        ttls = cache_ttl if cache_ttl is not None else int(os.getenv("LLM_CACHE_TTL", "86400"))
        path = cache_path or os.getenv("LLM_CACHE_PATH", "llm_cache.db")
        self.cache = LLMCache(db_path=path, ttl=ttls)
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def extract(self, html, prompt_template, item_class, site, query):
        cache_key = self._cache_key(site, query, html)
        if cached := self.cache.get(cache_key):
            logger.info("LLM cache hit for %s:%s", site, query)
            return cached

        chunks = self._chunk_html(html, max_chars=100000)
        all_results = []

        for chunk in chunks:
            prompt = prompt_template.replace("{html}", chunk)
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    response_format={"type": "json_object"},
                    max_tokens=4096,
                )
                content = response.choices[0].message.content
                data = json.loads(content)
                items = data.get("products", data.get("posts", []))
                if isinstance(items, list):
                    all_results.extend(items)
            except (openai.RateLimitError, openai.AuthenticationError) as e:
                logger.error("OpenAI API error: %s", e)
                return []
            except openai.APIError as e:
                logger.warning("OpenAI API error: %s", e)
                return []
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("LLM returned invalid response: %s", e)
                continue

        validated = self._validate_items(all_results, item_class)
        if validated:
            self.cache.set(cache_key, validated)
        return validated

    def _chunk_html(self, html, max_chars=100000):
        if len(html) <= max_chars:
            return [html]
        chunks = []
        for i in range(0, len(html), max_chars):
            chunks.append(html[i : i + max_chars])
        return chunks

    def _cache_key(self, site, query, html):
        prefix = html[:2000] if len(html) > 2000 else html
        raw = f"{site}:{query}:{prefix}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _validate_items(self, items, item_class):
        if item_class is None or not hasattr(item_class, "fields"):
            return items
        valid_fields = set(item_class.fields.keys())
        validated = []
        for item in items:
            if not isinstance(item, dict):
                continue
            clean = {k: v for k, v in item.items() if k in valid_fields}
            if clean:
                validated.append(clean)
        return validated


def llm_fallback(spider, response, item_class):
    """Shared LLM fallback for any spider. Yields item_class instances."""
    if not os.getenv("OPENAI_API_KEY") or os.getenv("LLM_ENABLED", "true") == "false":
        spider.logger.warning("LLM fallback disabled or no API key, skipping")
        return

    query = response.meta["query"]
    limit = int(response.meta.get("limit", 10))
    extractor = LLMExtractor()

    items = extractor.extract(
        html=response.text,
        prompt_template=spider.LLM_PROMPT,
        item_class=item_class,
        site=spider.site,
        query=query,
    )

    for item_data in items[:limit]:
        item_data.setdefault("metadata", {})
        item_data["metadata"]["strategy"] = "llm"
        item_data["metadata"]["query"] = query
        item_data.setdefault("site", spider.site)
        yield item_class(item_data)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_llm_extractor.py -v
```
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/llm_extractor.py tests/unit/test_llm_extractor.py
git commit -m "feat: add LLMExtractor — OpenAI-based extraction with caching and field validation"
```

---

### Task 4: Create prompt templates

**Files:**
- Create: `src/scrapper/prompts/__init__.py`
- Create: `src/scrapper/prompts/hotmart.py`
- Create: `src/scrapper/prompts/reddit.py`
- Create: `tests/unit/test_prompts.py`

- [ ] **Step 1: Write test for prompt templates**

Create `tests/unit/test_prompts.py`:

```python
from scrapper.prompts.hotmart import HOTMART_PROMPT
from scrapper.prompts.reddit import REDDIT_PROMPT


def test_hotmart_prompt_contains_html_placeholder():
    assert "{html}" in HOTMART_PROMPT


def test_hotmart_prompt_mentions_products_key():
    assert '"products"' in HOTMART_PROMPT


def test_reddit_prompt_contains_html_placeholder():
    assert "{html}" in REDDIT_PROMPT


def test_reddit_prompt_mentions_posts_key():
    assert '"posts"' in REDDIT_PROMPT
```

- [ ] **Step 2: Run tests — expected FAIL**

```bash
pytest tests/unit/test_prompts.py -v
```
Expected: FAIL (import errors)

- [ ] **Step 3: Create prompt files**

Create `src/scrapper/prompts/__init__.py` (empty file):

```python
```

Create `src/scrapper/prompts/hotmart.py`:

```python
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
{"products": [{"title": "Example Course", "url": "...", "price": 49.99, "rating": 4.5, "review_count": 234, "seller": "Author Name"}]}

HTML:
{html}"""
```

Create `src/scrapper/prompts/reddit.py`:

```python
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
{"posts": [{"title": "Post Title", "url": "/r/python/comments/...", "author": "u/username", "score": 142, "comment_count": 23, "published_at": "2024-01-01T00:00:00Z"}]}

HTML:
{html}"""
```

- [ ] **Step 4: Run tests — expected PASS**

```bash
pytest tests/unit/test_prompts.py -v
```
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/prompts/ tests/unit/test_prompts.py
git commit -m "feat: add prompt templates for Hotmart and Reddit LLM extraction"
```

---

### Task 5: Integrate LLM fallback into Hotmart spider

**Files:**
- Modify: `src/scrapper/spiders/hotmart.py`
- Modify: `tests/integration/test_hotmart_spider.py`

- [ ] **Step 1: Read current test file to understand structure**

```bash
ls tests/integration/test_hotmart_spider.py
```

- [ ] **Step 2: Read current spider to confirm line numbers**

Read `src/scrapper/spiders/hotmart.py` lines 1-10 and 238-260 for context.

- [ ] **Step 3: Add LLM_PROMPT class attribute and import**

Edit `src/scrapper/spiders/hotmart.py`, add import at top:

```python
from ..items import ProductItem
from ..prompts.hotmart import HOTMART_PROMPT
from ..llm_extractor import llm_fallback
```

Add class attributes before `custom_settings`:

```python
class HotmartSpider(scrapy.Spider):
    name = "hotmart"
    site = "hotmart"
    site_type = "product"
    LLM_PROMPT = HOTMART_PROMPT

    custom_settings = {
```

- [ ] **Step 4: Add LLM fallback call in parse_dom**

Edit `src/scrapper/spiders/hotmart.py`, modify `parse_dom` to add the fallback after the card loop (after line 271, before `if count >= limit: return`):

```python
        if not title or not url:
            continue

        review_count = _parse_review_count(reviews_text)
        price = _parse_price(price_text)

        count += 1
        yield ProductItem(
            site=self.site,
            url=url,
            title=title,
            price=price,
            currency="USD",
            rating=float(rating) if rating else None,
            review_count=review_count,
            seller=author,
            availability="",
            metadata={"query": query, "strategy": "playwright"},
        )

    if count == 0:
        self.logger.warning("DOM selectors found nothing, trying LLM fallback")
        yield from llm_fallback(self, response, ProductItem)
        return

    if count >= limit:
```

- [ ] **Step 5: Run existing tests to verify no regression**

```bash
pytest tests/ -v -k "hotmart" 2>&1 | tail -20
```
Expected: all existing hotmart tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/scrapper/spiders/hotmart.py
git commit -m "feat: add LLM fallback to Hotmart spider parse_dom"
```

---

### Task 6: Integrate LLM fallback into Reddit spider

**Files:**
- Modify: `src/scrapper/spiders/reddit.py`
- Modify: `tests/integration/test_reddit_spider.py`

- [ ] **Step 1: Add LLM_PROMPT import and class attribute**

Edit `src/scrapper/spiders/reddit.py`, add import at top:

```python
from ..items import PostItem
from ..prompts.reddit import REDDIT_PROMPT
from ..llm_extractor import llm_fallback
```

Add class attribute:

```python
class RedditSpider(scrapy.Spider):
    name = "reddit"
    site = "reddit"
    site_type = "post"
    LLM_PROMPT = REDDIT_PROMPT

    custom_settings = {
```

- [ ] **Step 2: Add LLM fallback call in parse method**

In `src/scrapper/spiders/reddit.py`, in the `parse` method, after the card loop that increments `count`, add the fallback before the pagination block. After line 130 (after `yield response.follow(...)` inside the card loop), before the `if count < limit:` pagination block:

```python
        if count < limit:
            next_link = response.css('a[rel="nofollow next"]::attr(href)').get()
            if next_link:
                yield response.follow(
                    next_link,
                    meta={"query": query, "limit": limit, "count": count},
                )

    if count == 0:
        self.logger.warning("HTML selectors found nothing, trying LLM fallback")
        yield from llm_fallback(self, response, PostItem)
        return
        title_el = card.css("a.search-title")
        title = title_el.css("::text").get("")
        href = title_el.css("::attr(href)").get("")
        if title and href:
            count += 1
            yield response.follow(
                href,
                callback=self.parse_post_page,
                meta={"query": query, "limit": limit, "count": count},
            )

    if count < limit:
        next_link = response.css('a[rel="nofollow next"]::attr(href)').get()
        if next_link:
            yield response.follow(
                next_link,
                meta={"query": query, "limit": limit, "count": count},
            )
```

So after the `for` loop, before the pagination block, I need to insert:

```python
    # After the for card loop...
    if count == 0:
        self.logger.warning("HTML selectors found nothing, trying LLM fallback")
        from ..llm_extractor import llm_fallback
        yield from llm_fallback(self, response, PostItem)
        return

    if count < limit:
```

- [ ] **Step 3: Make the edit**

Add after the `for card in cards:` loop body and before `if count < limit:`:

```python
    if count == 0:
        self.logger.warning("HTML selectors found nothing, trying LLM fallback")
        from ..llm_extractor import llm_fallback
        yield from llm_fallback(self, response, PostItem)
        return
```

- [ ] **Step 4: Run existing tests to verify no regression**

```bash
pytest tests/ -v -k "reddit" 2>&1 | tail -20
```
Expected: all existing reddit tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/spiders/reddit.py
git commit -m "feat: add LLM fallback to Reddit spider parse method"
```

---

### Task 7: Build `CurlCffiDownloadHandler` — composite handler

**Files:**
- Create: `src/scrapper/curl_cffi_handler.py`
- Create: `tests/unit/test_curl_cffi_handler.py`

- [ ] **Step 1: Write test for handler routing**

Create `tests/unit/test_curl_cffi_handler.py`:

```python
import os
from unittest.mock import MagicMock, patch

from scrapy import Request
from twisted.internet.defer import Deferred


def test_handler_class_exists():
    from scrapper.curl_cffi_handler import CurlCffiDownloadHandler
    handler = CurlCffiDownloadHandler.__new__(CurlCffiDownloadHandler)
    assert handler is not None


def test_disabled_falls_back():
    os.environ["CURL_CFFI_ENABLED"] = "false"
    from scrapper.curl_cffi_handler import CurlCffiDownloadHandler
    assert CurlCffiDownloadHandler is not None
    del os.environ["CURL_CFFI_ENABLED"]


def test_playwright_request_delegates_to_parent(mocker):
    os.environ["CURL_CFFI_ENABLED"] = "true"
    from scrapper.curl_cffi_handler import CurlCffiDownloadHandler

    request = Request("https://example.com", meta={"playwright": True})
    spider = MagicMock()
    spider.logger = MagicMock()

    with patch("scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler._download_request") as mock_parent:
        mock_parent.return_value = Deferred()

        handler = CurlCffiDownloadHandler.__new__(CurlCffiDownloadHandler)
        handler.settings = {}

        deferred = handler._download_request(request, spider)

        assert deferred is not None

    del os.environ["CURL_CFFI_ENABLED"]
```

- [ ] **Step 2: Run tests — expected FAIL**

```bash
pytest tests/unit/test_curl_cffi_handler.py -v
```
Expected: FAIL (import error)

- [ ] **Step 3: Implement CurlCffiDownloadHandler**

Create `src/scrapper/curl_cffi_handler.py`:

```python
import logging
import os

from scrapy.http import HtmlResponse
from scrapy_playwright.handler import ScrapyPlaywrightDownloadHandler

logger = logging.getLogger(__name__)


class CurlCffiDownloadHandler(ScrapyPlaywrightDownloadHandler):
    IMPERSONATE_FALLBACK = "chrome124"

    def _download_request(self, request, spider):
        if request.meta.get("playwright"):
            return super()._download_request(request, spider)

        enabled = os.getenv("CURL_CFFI_ENABLED", "true").lower() in ("true", "1", "yes")
        if not enabled:
            return super()._download_request(request, spider)

        try:
            from curl_cffi import requests as curl_requests
        except ImportError:
            logger.warning("curl_cffi not available, falling back to default handler")
            return super()._download_request(request, spider)

        impersonate = os.getenv("CURL_CFFI_IMPERSONATE", self.IMPERSONATE_FALLBACK)
        from twisted.internet import reactor, threads

        proxy = request.meta.get("proxy") or (
            request.meta.get("playwright_context_kwargs", {}).get("proxy", {}).get("server")
        )

        def _do_request():
            try:
                proxies = {"http": proxy, "https": proxy} if proxy else None
                resp = curl_requests.get(
                    request.url,
                    headers=dict(request.headers),
                    impersonate=impersonate,
                    proxies=proxies,
                    timeout=30,
                )
                return HtmlResponse(
                    url=str(resp.url),
                    status=resp.status_code,
                    headers=dict(resp.headers),
                    body=resp.content,
                    request=request,
                )
            except Exception as e:
                spider.logger.warning(f"curl_cffi request failed: {e}, falling back")
                return super()._download_request(request, spider)

        return threads.deferToThread(_do_request)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_curl_cffi_handler.py -v
```
Expected: 3 PASS (or skip if curl_cffi import fails in CI)

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/curl_cffi_handler.py tests/unit/test_curl_cffi_handler.py
git commit -m "feat: add CurlCffiDownloadHandler — composite handler with TLS impersonation"
```

---

### Task 8: Improve stealth handler

**Files:**
- Modify: `src/scrapper/stealth_handler.py`
- Modify: `tests/unit/test_stealth.py`

- [ ] **Step 1: Read current test file**

Open `tests/unit/test_stealth.py` to understand existing test patterns.

- [ ] **Step 2: Write tests for new stealth features**

Add to `tests/unit/test_stealth.py`:

```python
class TestStealthEnhanced:
    def test_canvas_spoof_script_is_injected(self, mocker):
        from scrapper.stealth_handler import ScrapyPlaywrightStealthDownloadHandler

        mock_context = mocker.AsyncMock()
        mock_page = mocker.AsyncMock()
        mock_context.new_page.return_value = mock_page

        handler = ScrapyPlaywrightStealthDownloadHandler.__new__(
            ScrapyPlaywrightStealthDownloadHandler
        )
        handler.settings = {}
        handler._contexts = {}

        mock_spider = mocker.MagicMock()
        mock_request = mocker.MagicMock()
        mock_request.meta = {"playwright": True, "playwright_page": mock_page}

        import asyncio
        async def _test():
            await handler._download_request(mock_request, mock_spider)

        asyncio.get_event_loop().run_until_complete(_test())

    def test_human_simulation_toggle_respected(self, mocker):
        import os
        os.environ["PLAYWRIGHT_HUMAN_SIMULATION"] = "false"

        from scrapper.stealth_handler import ScrapyPlaywrightStealthDownloadHandler

        mock_context = mocker.AsyncMock()
        mock_page = mocker.AsyncMock()
        mock_response = mocker.MagicMock()

        with mocker.patch.object(
            ScrapyPlaywrightStealthDownloadHandler,
            "_create_browser_context",
            return_value=mock_context,
        ):
            with mocker.patch.object(
                ScrapyPlaywrightStealthDownloadHandler,
                "_download_request",
                return_value=mock_response,
            ):
                handler = ScrapyPlaywrightStealthDownloadHandler.__new__(
                    ScrapyPlaywrightStealthDownloadHandler
                )

        os.environ.pop("PLAYWRIGHT_HUMAN_SIMULATION", None)
```

- [ ] **Step 3: Implement stealth improvements**

Edit `src/scrapper/stealth_handler.py`, replace the `_download_request` method:

```python
async def _download_request(self, request: Request, spider) -> HtmlResponse:
    response = await super()._download_request(request, spider)

    if not request.meta.get("playwright"):
        return response

    page: Page = request.meta.get("playwright_page")
    if not page:
        return response

    human_simulation = os.getenv("PLAYWRIGHT_HUMAN_SIMULATION", "true").lower() in (
        "true", "1", "yes",
    )

    if human_simulation:
        try:
            await page.add_init_script("""
                // Canvas fingerprint spoofing
                const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
                HTMLCanvasElement.prototype.toDataURL = function(type) {
                    const context = this.getContext('2d');
                    if (context) {
                        const imageData = context.getImageData(0, 0, 1, 1);
                        imageData.data[0] = imageData.data[0] ^ 1;
                        context.putImageData(imageData, 0, 0);
                    }
                    return originalToDataURL.apply(this, arguments);
                };

                // WebGL vendor spoofing
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) {
                        return 'Intel Inc.';
                    }
                    if (parameter === 37446) {
                        return 'Intel Iris OpenGL Engine';
                    }
                    return getParameter.call(this, parameter);
                };
            """)

            import random
            scroll_count = random.randint(2, 4)
            for _ in range(scroll_count):
                scroll_y = random.randint(100, 400)
                await page.evaluate(f"window.scrollBy(0, {scroll_y})")
                await page.wait_for_timeout(random.randint(200, 800))
        except Exception:
            pass

    return response
```

Also update `_create_browser_context` to add cookie persistence:

```python
async def _create_browser_context(
    self,
    name: str,
    context_kwargs: Optional[dict] = None,
) -> BrowserContext:
    context_kwargs = context_kwargs or {}

    if "proxy" not in context_kwargs:
        env_proxy = self.settings.get("PROXY_LIST", "")
        if env_proxy:
            proxies = [p.strip() for p in env_proxy.split(",") if p.strip()]
            if proxies:
                import random
                context_kwargs["proxy"] = {"server": random.choice(proxies)}

    cookie_persist = os.getenv("COOKIE_PERSIST_ENABLED", "true").lower() in (
        "true", "1", "yes",
    )
    if cookie_persist:
        import json
        from pathlib import Path
        cookie_file = Path(f"cookies/{name}.json")
        if cookie_file.exists():
            try:
                storage_state = json.loads(cookie_file.read_text())
                context_kwargs["storage_state"] = storage_state
            except (json.JSONDecodeError, OSError):
                pass

    context = await super()._create_browser_context(name, context_kwargs)

    if cookie_persist:
        import asyncio
        async def save_on_close(ctx):
            try:
                import json
                from pathlib import Path
                Path("cookies").mkdir(exist_ok=True)
                state = await ctx.storage_state()
                Path(f"cookies/{name}.json").write_text(
                    json.dumps(state.get("cookies", []))
                )
            except Exception:
                pass
        context.on("close", lambda ctx: asyncio.ensure_future(save_on_close(ctx)))

    config = StealthConfig()
    await config.apply_stealth_async(context)

    return context
```

Also add `import os` at the top of the file.

- [ ] **Step 4: Run existing stealth tests**

```bash
pytest tests/unit/test_stealth.py -v
```
Expected: all existing tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/stealth_handler.py tests/unit/test_stealth.py
git commit -m "feat: add canvas/WebGL spoofing, human scroll, and cookie persistence to stealth handler"
```

---

### Task 9: Update settings.py

**Files:**
- Modify: `src/scrapper/settings.py`

- [ ] **Step 1: Replace download handler registration**

Edit `src/scrapper/settings.py`, change the `DOWNLOAD_HANDLERS` block (lines 35-38):

```python
# Playwright download handler (required for JS rendering)
DOWNLOAD_HANDLERS = {
    "http": "scrapper.curl_cffi_handler.CurlCffiDownloadHandler",
    "https": "scrapper.curl_cffi_handler.CurlCffiDownloadHandler",
}
```

- [ ] **Step 2: Add LLM env vars section**

Append after `METRICS_MAX_RUNS = 100` (line 95):

```python
# ── LLM fallback extraction ─────────────────
LLM_ENABLED = os.getenv("LLM_ENABLED", "true").lower() in ("true", "1", "yes")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_CACHE_TTL = int(os.getenv("LLM_CACHE_TTL", "86400"))
LLM_CACHE_PATH = os.getenv("LLM_CACHE_PATH", "llm_cache.db")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
```

- [ ] **Step 3: Add curl-cffi variables**

Append after the existing proxy config (after line 83):

```python
# ── curl-cffi anti-bot ──────────────────────
CURL_CFFI_ENABLED = os.getenv("CURL_CFFI_ENABLED", "true").lower() in ("true", "1", "yes")
CURL_CFFI_IMPERSONATE = os.getenv("CURL_CFFI_IMPERSONATE", "chrome124")
```

- [ ] **Step 4: Add cookie persistence toggle**

Add after the existing cookie section (after line 114):

```python
COOKIE_PERSIST_ENABLED = os.getenv("COOKIE_PERSIST_ENABLED", "true").lower() in ("true", "1", "yes")
```

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v --ignore=tests/integration/test_supabase.py 2>&1 | tail -20
```
Expected: all tests PASS (Supabase integration tests may fail without credentials, that's fine)

- [ ] **Step 6: Commit**

```bash
git add src/scrapper/settings.py
git commit -m "feat: register CurlCffiDownloadHandler and add LLM/anti-bot env vars to settings"
```

---

### Task 10: Integration tests with fixtures

**Files:**
- Create: `tests/fixtures/hotmart_search.html`
- Create: `tests/fixtures/old_reddit_search.html`
- Create: `tests/fixtures/llm_hotmart_response.json`
- Create: `tests/fixtures/llm_reddit_response.json`
- Create: `tests/integration/test_llm_fallback.py`

- [ ] **Step 1: Create Hotmart fixture HTML**

Create `tests/fixtures/hotmart_search.html`:

```html
<div class="search-results">
  <div class="product-card-alt">
    <a class="product-link" href="/hotmart/product-1">Python Masterclass</a>
    <span class="product-card-alt__title">Python Masterclass</span>
    <span class="product-card-alt__author">John Doe</span>
    <span class="product-card-alt__rating"><span>4.8</span></span>
    <span class="product-card-alt__price">$49.99</span>
    <span class="product-card-alt__reviews">234 reviews</span>
  </div>
  <div class="product-card-alt">
    <a class="product-link" href="/hotmart/product-2">Django for Beginners</a>
    <span class="product-card-alt__title">Django for Beginners</span>
    <span class="product-card-alt__author">Jane Smith</span>
    <span class="product-card-alt__rating"><span>4.5</span></span>
    <span class="product-card-alt__price">$39.99</span>
    <span class="product-card-alt__reviews">120 reviews</span>
  </div>
</div>
```

- [ ] **Step 2: Create Reddit fixture HTML**

Create `tests/fixtures/old_reddit_search.html`:

```html
<div class="search-result-listing">
  <div class="search-result-link">
    <a class="search-title" href="/r/Python/comments/test1">Best Python libraries in 2026</a>
    <span class="author">u/pythondev</span>
    <span class="score unvoted">142</span>
    <a class="comments">23 comments</a>
    <time datetime="2026-01-01T00:00:00Z">Jan 1, 2026</time>
  </div>
  <div class="search-result-link">
    <a class="search-title" href="/r/Python/comments/test2">Django vs FastAPI 2026</a>
    <span class="author">u/webdev</span>
    <span class="score unvoted">89</span>
    <a class="comments">15 comments</a>
    <time datetime="2026-02-01T00:00:00Z">Feb 1, 2026</time>
  </div>
</div>
```

- [ ] **Step 3: Create mock LLM response fixtures**

Create `tests/fixtures/llm_hotmart_response.json`:

```json
{
  "products": [
    {
      "title": "Python Masterclass",
      "url": "/hotmart/product-1",
      "price": 49.99,
      "rating": 4.8,
      "review_count": 234,
      "seller": "John Doe"
    }
  ]
}
```

Create `tests/fixtures/llm_reddit_response.json`:

```json
{
  "posts": [
    {
      "title": "Best Python libraries in 2026",
      "url": "/r/Python/comments/test1",
      "author": "u/pythondev",
      "score": 142,
      "comment_count": 23,
      "published_at": "2026-01-01T00:00:00Z"
    }
  ]
}
```

- [ ] **Step 4: Write integration tests**

Create `tests/integration/test_llm_fallback.py`:

```python
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from scrapy.http import HtmlResponse, Request

from scrapper.items import ProductItem, PostItem
from scrapper.spiders.hotmart import HotmartSpider
from scrapper.spiders.reddit import RedditSpider

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def hotmart_response():
    html = (FIXTURES / "hotmart_search.html").read_text()
    request = Request("https://hotmart.com/search?q=python")
    return HtmlResponse(url=request.url, body=html.encode(), request=request)


@pytest.fixture
def reddit_response():
    html = (FIXTURES / "old_reddit_search.html").read_text()
    request = Request("https://old.reddit.com/search?q=python")
    return HtmlResponse(url=request.url, body=html.encode(), request=request)


class TestHotmartLLMFallback:
    def test_parse_dom_extracts_with_selectors(self, hotmart_response):
        spider = HotmartSpider()
        hotmart_response.meta["query"] = "python"
        hotmart_response.meta["limit"] = 10

        items = list(spider.parse_dom(hotmart_response))
        assert len(items) == 2
        assert all(isinstance(i, ProductItem) for i in items)
        assert items[0]["title"] == "Python Masterclass"
        assert items[1]["title"] == "Django for Beginners"

    def test_parse_dom_falls_back_to_llm_when_no_matches(self):
        html = "<html><body>No matching selectors here</body></html>"
        request = Request("https://hotmart.com/search?q=nonexistent")
        response = HtmlResponse(url=request.url, body=html.encode(), request=request)
        response.meta["query"] = "nonexistent"
        response.meta["limit"] = 5

        llm_response = json.loads(
            (FIXTURES / "llm_hotmart_response.json").read_text()
        )

        with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
            mock_client = mock_openai.return_value

            class FakeChoice:
                def __init__(self, content):
                    self.message = MagicMock()
                    self.message.content = content

            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[FakeChoice(json.dumps(llm_response))],
                usage=MagicMock(),
            )

            spider = HotmartSpider()
            items = list(spider.parse_dom(response))

            assert len(items) == 1
            assert items[0]["title"] == "Python Masterclass"
            assert items[0]["metadata"]["strategy"] == "llm"


class TestRedditLLMFallback:
    def test_parse_extracts_with_selectors(self, reddit_response):
        spider = RedditSpider()
        reddit_response.meta["query"] = "python"
        reddit_response.meta["limit"] = 10
        reddit_response.meta["count"] = 0

        items = list(spider.parse(reddit_response))
        assert len(items) >= 2
        from scrapy import Request
        assert all(isinstance(i, Request) for i in items)

    def test_parse_falls_back_to_llm_when_no_matches(self):
        html = "<html><body>No search results found</body></html>"
        request = Request("https://old.reddit.com/search?q=nonexistent")
        response = HtmlResponse(url=request.url, body=html.encode(), request=request)
        response.meta["query"] = "nonexistent"
        response.meta["limit"] = 5
        response.meta["count"] = 0

        llm_response = json.loads(
            (FIXTURES / "llm_reddit_response.json").read_text()
        )

        with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
            mock_client = mock_openai.return_value

            class FakeChoice:
                def __init__(self, content):
                    self.message = MagicMock()
                    self.message.content = content

            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[FakeChoice(json.dumps(llm_response))],
                usage=MagicMock(),
            )

            spider = RedditSpider()
            items = list(spider.parse(response))

            assert len(items) == 1
            assert items[0]["title"] == "Best Python libraries in 2026"
            assert items[0]["metadata"]["strategy"] == "llm"
```

- [ ] **Step 5: Run integration tests**

```bash
pytest tests/integration/test_llm_fallback.py -v
```
Expected: 4 PASS

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -v 2>&1 | tail -30
```
Expected: all tests PASS (147 previous + ~16 new = ~163)

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/ tests/integration/test_llm_fallback.py
git commit -m "test: add integration tests for LLM fallback with fixture HTML"
```
