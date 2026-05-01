# Reddit & Hotmart Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix critical bugs, add dual-strategy extraction (RSS/API + Playwright fallback), upgrade stealth stack, add integration tests, deprecate broken spiders.

**Architecture:** Each spider gets two data strategies — lightweight HTTP/RSS for speed, Playwright rendering as fallback. Stealth layer upgraded from `scrapy-playwright-stealth` to custom handler wrapping `playwright-stealth` v2. Proxy middleware fixed to inject into Playwright contexts.

**Tech Stack:** Scrapy 2.11+, scrapy-playwright, playwright-stealth v2, feedparser, curl-cffi, Supabase.

---

### Task 1: Fix the `parse_post` bug in Reddit spider

**Files:**
- Modify: `src/scrapper/spiders/reddit.py` (entire file rewrite)
- Test: `tests/test_scrapers.py` (existing)

- [ ] **Step 1: Verify current bug — `parse_post` is module-level (line 73+)**

```bash
grep -n "def parse_post" src/scrapper/spiders/reddit.py
```

Expected: Shows line 73 with no indentation — proving it's a module-level function, not a method.

- [ ] **Step 2: Rewrite `reddit.py` with `parse_post` moved into class**

Replace the entire file:

```python
import scrapy
from dateutil import parser as date_parser
from supabase import create_client

from ..items import PostItem


class RedditSpider(scrapy.Spider):
    name = "reddit"
    site = "reddit"
    site_type = "post"

    custom_settings = {
        "DOWNLOAD_HANDLERS": {},
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 2,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cutoff_date = None
        self._load_cutoff_date()

    def _load_cutoff_date(self):
        supabase_url = self.settings.get("SUPABASE_URL")
        supabase_key = self.settings.get("SUPABASE_KEY")
        query = getattr(self, "query", "python")

        if supabase_url and supabase_key:
            try:
                client = create_client(supabase_url, supabase_key)
                result = (
                    client.table("posts")
                    .select("scraped_at")
                    .eq("site", "reddit")
                    .eq("metadata->>'query'", query)
                    .order("scraped_at", desc=True)
                    .limit(1)
                    .execute()
                )
                if result.data:
                    self.cutoff_date = result.data[0].get("scraped_at")
                    self.logger.info(f"Incremental mode: cutoff date = {self.cutoff_date}")
            except Exception as e:
                self.logger.warning(f"Could not load cutoff date: {e}")

    def start_requests(self):
        query = getattr(self, "query", "python")
        limit = int(getattr(self, "limit", 10))
        url = f"https://old.reddit.com/search?q={query}&sort=relevance&type=link"
        yield scrapy.Request(url, meta={"query": query, "limit": limit, "count": 0})

    def parse(self, response):
        query = response.meta["query"]
        limit = response.meta["limit"]
        count = response.meta["count"]

        cards = response.css("div.search-result-link")
        for card in cards:
            if count >= limit:
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

    def parse_post_page(self, response):
        """Follow post URL to extract full content + top comment."""
        post_time_str = response.css("time::attr(datetime)").get()
        if post_time_str and self.cutoff_date:
            try:
                post_time = date_parser.parse(post_time_str)
                cutoff = date_parser.parse(self.cutoff_date)
                if post_time < cutoff:
                    self.logger.info(
                        f"Stopping: post {post_time} older than cutoff {self.cutoff_date}"
                    )
                    return
            except Exception:
                pass

        content = "".join(response.css("div.md *::text").getall()).strip()

        top_comment = ""
        comments = response.css("div.commentarea div.md")
        if comments:
            first_comment = comments[0]
            top_comment = "".join(first_comment.css("*::text").getall()).strip()

        post_url = response.url
        if not post_url.startswith("http"):
            post_url = f"https://old.reddit.com{post_url}"

        score_text = response.css("span.score::text").get("")
        try:
            score = int(score_text) if score_text else 0
        except (ValueError, TypeError):
            score = 0

        comment_text = response.css("a.comments::text").get("")
        try:
            comment_count = (
                int(comment_text.split()[0]) if comment_text and comment_text.split() else 0
            )
        except (ValueError, IndexError):
            comment_count = 0

        author = response.css("a.author::text").get("")
        title = response.css("a.title::text").get("")

        yield PostItem(
            site=self.site,
            url=post_url,
            title=title.strip() if title else "",
            author=author.strip() if author else "",
            content=content,
            score=score,
            comment_count=comment_count,
            published_at=post_time_str,
            metadata={
                "type": "detail",
                "top_comment": top_comment[:500],
                "query": response.meta.get("query"),
            },
        )
```

- [ ] **Step 3: Run existing tests**

```bash
pytest tests/ -v
```

Expected: All 39 tests pass. The `test_scrapers.py` tests pass (Post/Product/ScrapeResult models unchanged).

- [ ] **Step 4: Commit**

```bash
git add src/scrapper/spiders/reddit.py
git commit -m "fix: move parse_post into RedditSpider class to fix NameError on self.cutoff_date"
```

---

### Task 2: Update dependencies in pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update `pyproject.toml`**

```diff
 [project]
 name = "scrapper"
 version = "0.3.0"
 description = "Multi-site web scraper — Reddit, Hotmart (+ deprecated: Amazon, MercadoLibre, Quora)"
 requires-python = ">=3.11"
 dependencies = [
     "scrapy>=2.11",
-    "scrapy-playwright-stealth>=0.1",
+    "scrapy-playwright>=0.1",
+    "playwright-stealth>=2.0",
     "playwright>=1.45",
     "supabase>=2.7",
     "beautifulsoup4>=4.12",
     "tenacity>=8.3",
     "loguru>=0.7",
     "python-dotenv>=1.0",
+    "feedparser>=6.0",
+    "curl-cffi>=0.7",
 ]
```

- [ ] **Step 2: Install new dependencies**

```bash
source .venv/bin/activate && pip install -e ".[dev]"
```

Expected: Installs `playwright-stealth>=2.0`, `feedparser>=6.0`, `curl-cffi>=0.7`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: upgrade stealth deps, add feedparser and curl-cffi"
```

---

### Task 3: Create custom stealth download handler

**Files:**
- Create: `src/scrapper/stealth_handler.py`

- [ ] **Step 1: Write `src/scrapper/stealth_handler.py`**

```python
"""Custom Scrapy download handler using playwright-stealth v2."""

import asyncio
from typing import Optional

from playwright.async_api import BrowserContext, Page
from playwright_stealth import Stealth
from scrapy import Request
from scrapy.http import HtmlResponse
from scrapy_playwright.handler import ScrapyPlaywrightDownloadHandler


class ScrapyPlaywrightStealthDownloadHandler(ScrapyPlaywrightDownloadHandler):
    """Playwright download handler with playwright-stealth v2 patches."""

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

        context = await super()._create_browser_context(name, context_kwargs)

        stealth = Stealth()
        await stealth.apply_stealth_async(context)

        return context

    async def _download_request(self, request: Request, spider) -> HtmlResponse:
        response = await super()._download_request(request, spider)

        if request.meta.get("playwright"):
            page: Page = request.meta.get("playwright_page")
            if page and getattr(self.settings, "getbool", lambda *a: True)(
                "PLAYWRIGHT_HUMAN_SIMULATION", True
            ):
                try:
                    scroll_y = __import__("random").randint(100, 600)
                    await page.evaluate(f"window.scrollBy(0, {scroll_y})")
                except Exception:
                    pass

        return response
```

**Note:** The class is named `ScrapyPlaywrightStealthDownloadHandler` to match the dotted path currently in `settings.py` — no settings change needed for the class name. The implementation changes from using `scrapy-playwright-stealth` package to directly wrapping `playwright-stealth` v2.

- [ ] **Step 2: Verify the import works**

```bash
python -c "from scrapper.stealth_handler import ScrapyPlaywrightStealthDownloadHandler; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/scrapper/stealth_handler.py
git commit -m "feat: custom download handler with playwright-stealth v2"
```

---

### Task 4: Update UA list and fix proxy middleware for Playwright

**Files:**
- Modify: `src/scrapper/utils.py`
- Modify: `src/scrapper/middlewares.py`

- [ ] **Step 1: Update `USER_AGENTS` in `src/scrapper/utils.py`**

Replace the existing `USER_AGENTS` list (lines 4-16):

```python
USER_AGENTS = [
    # Chrome 130 — Windows / Mac / Linux
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Firefox 132
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:132.0) Gecko/20100101 Firefox/132.0",
    # Edge 130
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    # Safari 18
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    # Mobile Chrome 130 (Android)
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    # Mobile Safari 18 (iPhone)
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
]
```

- [ ] **Step 2: Update `src/scrapper/middlewares.py` to use shared UA list and inject proxy for Playwright**

Replace the entire file:

```python
"""Custom Scrapy downloader middlewares for reliability and anti-bot."""

import random

from scrapy.downloadermiddlewares.retry import RetryMiddleware

from .utils import USER_AGENTS


class RetryWithBackoffMiddleware(RetryMiddleware):
    """Retry on errors with exponential backoff: 1s, 2s, 4s, 8s."""

    def _retry(self, request, reason, spider):
        retries = request.meta.get("retry_times", 0) + 1
        delay = min(2 ** (retries - 1), 16)
        request.meta["retry_times"] = retries
        request.meta["download_latency"] = delay
        spider.logger.info(
            f"Retrying {request.url} (attempt {retries}) after {delay}s delay"
        )
        return super()._retry(request, reason, spider)


class ProxyRotationMiddleware:
    """Rotate through proxy list on each request, including Playwright."""

    def __init__(self, proxy_list: str):
        self.proxies = [p.strip() for p in proxy_list.split(",") if p.strip()]

    @classmethod
    def from_crawler(cls, crawler):
        return cls(proxy_list=crawler.settings.get("PROXY_LIST", ""))

    def process_request(self, request, spider):
        if not self.proxies:
            return None
        proxy = random.choice(self.proxies)

        if request.meta.get("playwright"):
            context_kwargs = request.meta.setdefault("playwright_context_kwargs", {})
            context_kwargs["proxy"] = {"server": proxy}
        else:
            request.meta["proxy"] = proxy

        spider.logger.debug(
            f"Using proxy: {proxy.split('@')[-1] if '@' in proxy else proxy}"
        )
        return None


class UARotationMiddleware:
    """Rotate user agent on each request."""

    def process_request(self, request, spider):
        ua = random.choice(USER_AGENTS)
        request.headers["User-Agent"] = ua

        if request.meta.get("playwright"):
            context_kwargs = request.meta.setdefault("playwright_context_kwargs", {})
            context_kwargs["user_agent"] = ua

        return None
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/ -v
```

Expected: All existing tests pass. `test_utils.py::test_user_agents_list_populated` still passes (list is still > 0).

- [ ] **Step 4: Commit**

```bash
git add src/scrapper/utils.py src/scrapper/middlewares.py
git commit -m "feat: update UA list to Chrome 130+, inject proxy and UA into Playwright contexts"
```

---

### Task 5: Update Scrapy settings for new stealth handler and config

**Files:**
- Modify: `src/scrapper/settings.py`

- [ ] **Step 1: Update `settings.py`**

Replace the DOWNLOAD_HANDLERS and PLAYWRIGHT config sections:

```python
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# Python 3.12+ requires an explicit event loop before installing the reactor
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

BOT_NAME = "scrapper"

SPIDER_MODULES = ["scrapper.spiders"]
NEWSPIDER_MODULE = "scrapper.spiders"

ROBOTSTXT_OBEY = True
USER_AGENT = "scrapper/0.3 (research crawler; contact@example.com)"

CONCURRENT_REQUESTS = 2
DOWNLOAD_DELAY = 2
RANDOMIZE_DOWNLOAD_DELAY = True

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

RETRY_ENABLED = True
RETRY_TIMES = 4
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

# Playwright download handler (custom stealth v2 integration)
DOWNLOAD_HANDLERS = {
    "http": "scrapper.stealth_handler.ScrapyPlaywrightStealthDownloadHandler",
    "https": "scrapper.stealth_handler.ScrapyPlaywrightStealthDownloadHandler",
}

# Playwright config
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes"),
    "args": ["--disable-blink-features=AutomationControlled"],
}
PLAYWRIGHT_MAX_PAGES_PER_CONTEXT = 4
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 30000
PLAYWRIGHT_ELEM_WAIT_TIMEOUT = 5000
PLAYWRIGHT_HUMAN_SIMULATION = os.getenv(
    "PLAYWRIGHT_HUMAN_SIMULATION", "true"
).lower() in ("true", "1", "yes")

ITEM_PIPELINES = {
    "scrapper.pipelines.ValidatePipeline": 100,
    "scrapper.pipelines.DedupInMemoryPipeline": 200,
    "scrapper.pipelines.SupabasePipeline": 300,
}

DOWNLOADER_MIDDLEWARES = {
    "scrapper.middlewares.RetryWithBackoffMiddleware": 550,
    "scrapper.middlewares.ProxyRotationMiddleware": 750,
    "scrapper.middlewares.UARotationMiddleware": 850,
}

EXTENSIONS = {
    "scrapper.extensions.StatsLogger": 400,
    "scrapper.extensions.ErrorAlerter": 500,
}

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

PROXY_LIST = os.getenv("PROXY_LIST", "")

ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")

LOG_LEVEL = "INFO"
LOG_FILE = "scrapy.log"

# Cookie persistence (for login sites)
COOKIE_SAVE_ENABLED = True
COOKIE_LOAD_ENABLED = True
COOKIE_DB_PATH = "cookies/".strip("/")

DOWNLOAD_TIMEOUT = 30
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 30000
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/ -v
```

Expected: `test_settings.py` tests pass (they check specific values — PLAYWRIGHT_BROWSER_TYPE still "chromium", CONCURRENT_REQUESTS still 2, etc.)

- [ ] **Step 3: Commit**

```bash
git add src/scrapper/settings.py
git commit -m "feat: switch to custom stealth handler, add headless env var and human simulation config"
```

---

### Task 6: Reddit — add RSS discovery strategy

**Files:**
- Modify: `src/scrapper/spiders/reddit.py`
- Create: `tests/fixtures/reddit_rss.xml`

- [ ] **Step 1: Write RSS fixture file `tests/fixtures/reddit_rss.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Python 3.13 released</title>
    <link href="https://old.reddit.com/r/Python/comments/abc123/python_313_released/"/>
    <author><name>u_python_dev</name></author>
    <updated>2026-04-15T10:30:00Z</updated>
  </entry>
  <entry>
    <title>Best practices for async Python</title>
    <link href="https://old.reddit.com/r/Python/comments/def456/best_practices_async_python/"/>
    <author><name>u_async_fan</name></author>
    <updated>2026-04-14T08:00:00Z</updated>
  </entry>
</feed>
```

- [ ] **Step 2: Rewrite `src/scrapper/spiders/reddit.py` with RSS strategy**

```python
import scrapy
from dateutil import parser as date_parser
from supabase import create_client

from ..items import PostItem


class RedditSpider(scrapy.Spider):
    name = "reddit"
    site = "reddit"
    site_type = "post"

    custom_settings = {
        "DOWNLOAD_HANDLERS": {},
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 2,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cutoff_date = None
        self._load_cutoff_date()

    def _load_cutoff_date(self):
        supabase_url = self.settings.get("SUPABASE_URL")
        supabase_key = self.settings.get("SUPABASE_KEY")
        query = getattr(self, "query", "python")

        if supabase_url and supabase_key:
            try:
                client = create_client(supabase_url, supabase_key)
                result = (
                    client.table("posts")
                    .select("scraped_at")
                    .eq("site", "reddit")
                    .eq("metadata->>'query'", query)
                    .order("scraped_at", desc=True)
                    .limit(1)
                    .execute()
                )
                if result.data:
                    self.cutoff_date = result.data[0].get("scraped_at")
                    self.logger.info(f"Incremental mode: cutoff date = {self.cutoff_date}")
            except Exception as e:
                self.logger.warning(f"Could not load cutoff date: {e}")

    def start_requests(self):
        query = getattr(self, "query", "python")
        limit = int(getattr(self, "limit", 10))
        rss_url = f"https://www.reddit.com/search.rss?q={query}&sort=relevance&limit={limit}"
        yield scrapy.Request(
            rss_url,
            callback=self.parse_rss,
            meta={"query": query, "limit": limit},
            errback=self._fallback_to_search,
        )

    def _fallback_to_search(self, failure):
        query = failure.request.meta["query"]
        limit = failure.request.meta["limit"]
        url = f"https://old.reddit.com/search?q={query}&sort=relevance&type=link"
        yield scrapy.Request(url, meta={"query": query, "limit": limit, "count": 0})

    def parse_rss(self, response):
        query = response.meta["query"]
        limit = response.meta["limit"]

        import feedparser
        feed = feedparser.parse(response.text)

        count = 0
        for entry in feed.entries:
            if count >= limit:
                return

            title = entry.get("title", "")
            url = entry.get("link", "")
            author = entry.get("author", "")
            published = entry.get("updated", "") or entry.get("published", "")

            if not title or not url:
                continue

            count += 1

            if published and self.cutoff_date:
                try:
                    post_time = date_parser.parse(published)
                    cutoff = date_parser.parse(self.cutoff_date)
                    if post_time < cutoff:
                        self.logger.info(
                            f"Skipping RSS post older than cutoff: {title}"
                        )
                        continue
                except Exception:
                    pass

            yield response.follow(
                url,
                callback=self.parse_post_page,
                meta={"query": query, "limit": limit, "count": count},
            )

        if count == 0:
            self.logger.info("RSS returned no entries, falling back to HTML search")
            yield from self._fallback_to_search(FakeFailure(response))

    def parse(self, response):
        """Fallback: old.reddit.com search results (Strategy 2)."""
        query = response.meta["query"]
        limit = response.meta["limit"]
        count = response.meta["count"]

        cards = response.css("div.search-result-link")
        for card in cards:
            if count >= limit:
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

    def parse_post_page(self, response):
        """Extract full post content from detail page."""
        post_time_str = response.css("time::attr(datetime)").get()
        if post_time_str and self.cutoff_date:
            try:
                post_time = date_parser.parse(post_time_str)
                cutoff = date_parser.parse(self.cutoff_date)
                if post_time < cutoff:
                    self.logger.info(
                        f"Stopping: post {post_time} older than cutoff {self.cutoff_date}"
                    )
                    return
            except Exception:
                pass

        content = "".join(response.css("div.md *::text").getall()).strip()

        top_comment = ""
        comments = response.css("div.commentarea div.md")
        if comments:
            first_comment = comments[0]
            top_comment = "".join(first_comment.css("*::text").getall()).strip()

        post_url = response.url
        if not post_url.startswith("http"):
            post_url = f"https://old.reddit.com{post_url}"

        score_text = response.css("span.score::text").get("")
        try:
            score = int(score_text) if score_text else 0
        except (ValueError, TypeError):
            score = 0

        comment_text = response.css("a.comments::text").get("")
        try:
            comment_count = (
                int(comment_text.split()[0]) if comment_text and comment_text.split() else 0
            )
        except (ValueError, IndexError):
            comment_count = 0

        author = response.css("a.author::text").get("")
        title = response.css("a.title::text").get("")

        if not post_url:
            self.logger.warning("Skipping post with no URL")
            return

        yield PostItem(
            site=self.site,
            url=post_url,
            title=title.strip() if title else "",
            author=author.strip() if author else "",
            content=content,
            score=score,
            comment_count=comment_count,
            published_at=post_time_str,
            metadata={
                "type": "detail",
                "top_comment": top_comment[:500],
                "query": response.meta.get("query"),
            },
        )


class FakeFailure:
    """Minimal failure-like object for fallback dispatch."""

    def __init__(self, response):
        self.request = response.request
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/ -v
```

Expected: All existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/scrapper/spiders/reddit.py tests/fixtures/reddit_rss.xml
git commit -m "feat: add RSS discovery strategy for Reddit with HTML fallback"
```

---

### Task 7: Hotmart — add API interception, pagination, and price extraction

**Files:**
- Modify: `src/scrapper/spiders/hotmart.py`
- Create: `tests/fixtures/hotmart_api_response.json`
- Create: `tests/fixtures/hotmart_search.html`

- [ ] **Step 1: Write API fixture `tests/fixtures/hotmart_api_response.json`**

```json
{
  "data": {
    "search": {
      "products": [
        {
          "id": "prod_001",
          "name": "Digital Marketing Masterclass",
          "url": "https://hotmart.com/en/marketplace/products/digital-marketing-masterclass/prod_001",
          "author": {
            "name": "John Smith"
          },
          "price": {
            "value": 49.99,
            "currency": "USD"
          },
          "rating": 4.7,
          "reviewCount": 234,
          "publishedAt": "2025-11-15T00:00:00Z"
        },
        {
          "id": "prod_002",
          "name": "Python for Data Science",
          "url": "https://hotmart.com/en/marketplace/products/python-data-science/prod_002",
          "author": {
            "name": "Jane Doe"
          },
          "price": {
            "value": 79.0,
            "currency": "USD"
          },
          "rating": 4.3,
          "reviewCount": 89,
          "publishedAt": "2026-01-20T00:00:00Z"
        }
      ],
      "pagination": {
        "page": 1,
        "totalPages": 5,
        "totalItems": 50
      }
    }
  }
}
```

- [ ] **Step 2: Write HTML fixture `tests/fixtures/hotmart_search.html`**

```html
<html>
<body>
  <div class="product-card-alt">
    <a class="product-link" href="/en/marketplace/products/digital-marketing/prod_001">Digital Marketing Masterclass</a>
    <span class="product-card-alt__title">Digital Marketing Masterclass</span>
    <span class="product-card-alt__author">John Smith</span>
    <span class="product-card-alt__rating"><span>4.7</span></span>
    <span class="product-card-alt__price">$49.99</span>
    <span class="product-card-alt__reviews">234 reviews</span>
  </div>
  <div class="product-card-alt">
    <a class="product-link" href="/en/marketplace/products/python-data-science/prod_002">Python for Data Science</a>
    <span class="product-card-alt__title">Python for Data Science</span>
    <span class="product-card-alt__author">Jane Doe</span>
    <span class="product-card-alt__rating"><span>4.3</span></span>
    <span class="product-card-alt__price">$79.00</span>
    <span class="product-card-alt__reviews">89 reviews</span>
  </div>
  <button class="load-more-btn">Load more</button>
</body>
</html>
```

- [ ] **Step 3: Rewrite `src/scrapper/spiders/hotmart.py`**

```python
import json
import re

import scrapy
from scrapy import Request

from ..items import ProductItem


class HotmartSpider(scrapy.Spider):
    name = "hotmart"
    site = "hotmart"
    site_type = "product"

    custom_settings = {
        "CONCURRENT_REQUESTS": 2,
        "DOWNLOAD_DELAY": 3,
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._api_endpoint_cache = None
        self._api_headers_cache = None

    def start_requests(self):
        query = getattr(self, "query", "marketing")
        limit = int(getattr(self, "limit", 10))
        url = f"https://hotmart.com/en/marketplace/search?q={query}"

        if self._api_endpoint_cache:
            page = 1
            api_url = self._api_endpoint_cache + f"?q={query}&page={page}&size={limit}"
            yield Request(
                api_url,
                callback=self.parse_api,
                meta={"query": query, "limit": limit, "page": page, "strategy": "api"},
                headers=self._api_headers_cache or {},
                errback=lambda f: self._fallback_to_playwright(f, query, limit),
            )
        else:
            yield Request(
                url,
                callback=self.discover_api,
                meta={
                    "playwright": True,
                    "query": query,
                    "limit": limit,
                },
            )

    def discover_api(self, response):
        """Warm-up: use Playwright to find internal API endpoint."""
        query = response.meta["query"]
        limit = response.meta["limit"]

        intercepted = []

        async def capture_route(route):
            url = route.request.url
            if any(kw in url.lower() for kw in ["search", "product", "graphql", "/api/"]):
                intercepted.append({
                    "url": url,
                    "method": route.request.method,
                    "headers": dict(route.request.headers),
                    "post_data": route.request.post_data,
                })
            await route.continue_()

        page = response.meta.get("playwright_page")
        if page:
            try:
                import asyncio

                async def _intercept():
                    await page.route("**/*", capture_route)
                    await asyncio.sleep(5)

                asyncio.get_event_loop().run_until_complete(_intercept())
            except Exception as e:
                self.logger.warning(f"API interception failed: {e}")

        if intercepted:
            self.logger.info(f"Intercepted {len(intercepted)} API calls")

            best = None
            for call in intercepted:
                url = call["url"]
                if "search" in url.lower():
                    base = re.sub(r"[?&]q=[^&]*", "", url)
                    base = re.sub(r"[?&]page=\d+", "", base)
                    base = re.sub(r"[?&]size=\d+", "", base)
                    best = base
                    self._api_headers_cache = call.get("headers", {})
                    break

            if best:
                self._api_endpoint_cache = best
                self.logger.info(f"Cached API endpoint: {best}")
                page_num = 1
                api_url = f"{best}?q={query}&page={page_num}&size={limit}"
                yield Request(
                    api_url,
                    callback=self.parse_api,
                    meta={
                        "query": query,
                        "limit": limit,
                        "page": page_num,
                        "strategy": "api",
                    },
                    headers=self._api_headers_cache,
                )
                return

        self.logger.info("No API endpoint found, falling back to DOM scraping")
        yield from self._parse_dom(response)

    def parse_api(self, response):
        """Strategy 1: Parse JSON from internal API."""
        query = response.meta["query"]
        limit = response.meta["limit"]
        page = response.meta["page"]

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            self.logger.warning("API response not valid JSON, falling back to DOM")
            yield from self._fallback_to_playwright(
                FakeFailure(response), query, limit
            )
            return

        products = self._extract_products_from_json(data)
        count = 0

        for product in products:
            if count >= limit:
                return
            count += 1
            product["metadata"]["query"] = query
            yield ProductItem(product)

        if count < limit:
            pagination = data.get("data", {}).get("search", {}).get("pagination", {})
            total_pages = pagination.get("totalPages", 1)
            if page < total_pages:
                next_page = page + 1
                api_url = (
                    self._api_endpoint_cache
                    + f"?q={query}&page={next_page}&size={limit}"
                )
                yield Request(
                    api_url,
                    callback=self.parse_api,
                    meta={
                        "query": query,
                        "limit": limit,
                        "page": next_page,
                        "strategy": "api",
                    },
                    headers=self._api_headers_cache or {},
                )

    def _extract_products_from_json(self, data):
        """Extract product dicts from JSON structure (tries multiple paths)."""
        products = []

        def _search(obj, depth=0):
            if depth > 10:
                return
            if isinstance(obj, dict):
                if "name" in obj and "url" in obj:
                    price = None
                    price_obj = obj.get("price")
                    if isinstance(price_obj, dict):
                        price = price_obj.get("value")
                    elif isinstance(price_obj, (int, float)):
                        price = float(price_obj)

                    author = obj.get("author", {})
                    if isinstance(author, dict):
                        author = author.get("name", "")
                    elif not isinstance(author, str):
                        author = ""

                    review_count = obj.get("reviewCount", 0) or obj.get(
                        "review_count", 0
                    )

                    products.append({
                        "site": self.site,
                        "url": obj["url"],
                        "title": obj["name"],
                        "price": price,
                        "currency": (
                            obj.get("price", {}).get("currency", "USD")
                            if isinstance(obj.get("price"), dict)
                            else "USD"
                        ),
                        "rating": float(obj.get("rating", 0) or 0) or None,
                        "review_count": int(review_count),
                        "seller": author,
                        "availability": "",
                        "metadata": {},
                    })
                if not products:
                    for v in obj.values():
                        _search(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    _search(item, depth + 1)

        _search(data)
        return products

    def _fallback_to_playwright(self, failure, query, limit):
        """Fallback: use Playwright DOM scraping."""
        url = f"https://hotmart.com/en/marketplace/search?q={query}"
        yield Request(
            url,
            callback=self._parse_dom,
            meta={
                "playwright": True,
                "query": query,
                "limit": limit,
                "strategy": "playwright",
                "page": 1,
            },
        )

    def parse(self, response):
        """Alias for DOM parsing (Strategy 2 fallback)."""
        return self._parse_dom(response)

    def _parse_dom(self, response):
        limit = response.meta["limit"]
        query = response.meta["query"]
        page = response.meta.get("page", 1)
        strategy = response.meta.get("strategy", "playwright")

        cards = response.css("div.product-card-alt")
        count = 0

        for card in cards:
            if count >= limit:
                break

            title_el = card.css(".product-card-alt__title")
            title = title_el.css("::text").get("")

            author_el = card.css(".product-card-alt__author")
            author = author_el.css("::text").get("")

            rating_el = card.css(".product-card-alt__rating span::text")
            rating = rating_el.get("")

            price_el = card.css(".product-card-alt__price::text")
            price_text = price_el.get("")

            reviews_el = card.css(".product-card-alt__reviews::text")
            reviews_text = reviews_el.get("")

            url_el = card.css("a.product-link::attr(href)")
            url = url_el.get("")

            title = title.strip() if title else ""
            author = author.strip() if author else ""

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
                metadata={"query": query, "strategy": strategy},
            )

        if count >= limit:
            return

        if strategy == "playwright":
            page_obj = response.meta.get("playwright_page")
            if page_obj:
                try:
                    import asyncio

                    async def _click_load_more():
                        button = page_obj.locator("button.load-more-btn")
                        if await button.count() > 0:
                            await button.click()
                            await page_obj.wait_for_timeout(2000)
                            return True
                        return False

                    clicked = asyncio.get_event_loop().run_until_complete(
                        _click_load_more()
                    )
                    if clicked:
                        next_page = page + 1
                        yield Request(
                            response.url,
                            callback=self._parse_dom,
                            meta={
                                "playwright": True,
                                "query": query,
                                "limit": limit,
                                "page": next_page,
                                "strategy": "playwright",
                            },
                            dont_filter=True,
                        )
                except Exception as e:
                    self.logger.warning(f"Load more failed: {e}")


def _parse_price(text):
    """Extract float price from text like '$49.99' or 'R$ 79,90'."""
    if not text:
        return None
    try:
        cleaned = "".join(c for c in text if c.isdigit() or c in ".,")
        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


def _parse_review_count(text):
    """Extract integer review count from text like '234 reviews'."""
    if not text:
        return 0
    try:
        numbers = re.findall(r"\d+", text)
        return int(numbers[0]) if numbers else 0
    except (ValueError, IndexError):
        return 0


class FakeFailure:
    """Minimal failure-like object for errback dispatch."""

    def __init__(self, response):
        self.request = response.request
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/ -v
```

Expected: All existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/spiders/hotmart.py tests/fixtures/hotmart_api_response.json tests/fixtures/hotmart_search.html
git commit -m "feat: add API interception, pagination, and price extraction for Hotmart"
```

---

### Task 8: Deprecate broken spiders

**Files:**
- Modify: `src/scrapper/spiders/amazon.py`
- Modify: `src/scrapper/spiders/mercadolibre.py`
- Modify: `src/scrapper/spiders/quora.py`

- [ ] **Step 1: Deprecate amazon.py**

Add `DEPRECATED = True` after `site_type` and add `__init__` with warning. In `amazon.py`, after line 9 (`site_type = "product"`):

```python
DEPRECATED = True
```

Read the file to find an existing `__init__` — amazon.py uses `def __init__(self, *args, **kwargs)` with custom settings. Wrap it to add the warning at the start:

```bash
grep -n "__init__" src/scrapper/spiders/amazon.py
```

If `__init__` exists, add at the top of it:
```python
self.logger.warning(
    "Amazon spider is DEPRECATED — requires residential proxies. "
    "Set PROXY_LIST with residential proxies to use this spider."
)
```

If not, add:
```python
def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.logger.warning(
        "Amazon spider is DEPRECATED — requires residential proxies. "
        "Set PROXY_LIST with residential proxies to use this spider."
    )
```

- [ ] **Step 2: Deprecate mercadolibre.py**

After `site_type = "product"` on line 9, add:
```python
DEPRECATED = True
```

Check for existing `__init__`:
```bash
grep -n "__init__" src/scrapper/spiders/mercadolibre.py
```

If `__init__` exists, prepend the warning. If not, add:
```python
def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.logger.warning(
        "MercadoLibre spider is DEPRECATED — requires residential proxies. "
        "Set PROXY_LIST with residential proxies to use this spider."
    )
```

- [ ] **Step 3: Deprecate quora.py**

After `site_type = "post"` on line 8, add:
```python
DEPRECATED = True
```

Check for existing `__init__`:
```bash
grep -n "__init__" src/scrapper/spiders/quora.py
```

If `__init__` exists, prepend the warning. If not, add:
```python
def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.logger.warning(
        "Quora spider is DEPRECATED — requires Cloudflare bypass (login + residential proxies). "
        "Set PROXY_LIST with residential proxies to use this spider."
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/ -v
```

Expected: All existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/spiders/amazon.py src/scrapper/spiders/mercadolibre.py src/scrapper/spiders/quora.py
git commit -m "feat: deprecate Amazon, MercadoLibre, Quora spiders (need proxies)"
```

---

### Task 9: Reorganize test directory structure

**Files:**
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Move: `tests/test_items.py` → `tests/unit/test_items.py`
- Move: `tests/test_pipelines.py` → `tests/unit/test_pipelines.py`
- Move: `tests/test_extensions.py` → `tests/unit/test_extensions.py`
- Move: `tests/test_scrapers.py` → `tests/unit/test_scrapers.py`
- Move: `tests/test_settings.py` → `tests/unit/test_settings.py`
- Move: `tests/test_utils.py` → `tests/unit/test_utils.py`

- [ ] **Step 1: Create directories and move files**

```bash
mkdir -p tests/unit tests/integration tests/fixtures
touch tests/unit/__init__.py tests/integration/__init__.py

mv tests/test_items.py tests/unit/test_items.py
mv tests/test_pipelines.py tests/unit/test_pipelines.py
mv tests/test_extensions.py tests/unit/test_extensions.py
mv tests/test_scrapers.py tests/unit/test_scrapers.py
mv tests/test_settings.py tests/unit/test_settings.py
mv tests/test_utils.py tests/unit/test_utils.py
```

- [ ] **Step 2: Run tests to verify everything still works**

```bash
pytest tests/ -v
```

Expected: All 39 tests pass (pytest discovers them in `tests/unit/`).

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "refactor: reorganize tests into unit/ and integration/ dirs"
```

---

### Task 10: Write middleware tests

**Files:**
- Create: `tests/unit/test_middlewares.py`

- [ ] **Step 1: Write `tests/unit/test_middlewares.py`**

```python
from scrapper.middlewares import (
    ProxyRotationMiddleware,
    UARotationMiddleware,
    USER_AGENTS,
)


class FakeSpider:
    name = "test_spider"


class FakeRequest:
    def __init__(self, meta=None, headers=None):
        self.meta = meta if meta is not None else {}
        self.headers = headers if headers is not None else {}


class TestProxyRotationMiddleware:
    def test_no_proxies_does_nothing(self):
        mw = ProxyRotationMiddleware(proxy_list="")
        request = FakeRequest()
        result = mw.process_request(request, FakeSpider())
        assert result is None
        assert "proxy" not in request.meta

    def test_sets_proxy_for_regular_request(self):
        mw = ProxyRotationMiddleware(proxy_list="http://proxy1:8080,http://proxy2:8080")
        request = FakeRequest()
        result = mw.process_request(request, FakeSpider())
        assert result is None
        assert "proxy" in request.meta
        assert request.meta["proxy"] in (
            "http://proxy1:8080",
            "http://proxy2:8080",
        )

    def test_sets_proxy_for_playwright_request(self):
        mw = ProxyRotationMiddleware(proxy_list="http://proxy1:8080")
        request = FakeRequest(meta={"playwright": True})
        result = mw.process_request(request, FakeSpider())
        assert result is None
        assert "playwright_context_kwargs" in request.meta
        assert request.meta["playwright_context_kwargs"]["proxy"] == {
            "server": "http://proxy1:8080"
        }


class TestUARotationMiddleware:
    def test_sets_ua_header(self):
        mw = UARotationMiddleware()
        request = FakeRequest()
        mw.process_request(request, FakeSpider())
        assert "User-Agent" in request.headers
        ua = request.headers["User-Agent"]
        assert isinstance(ua, str)
        assert len(ua) > 10

    def test_sets_ua_for_playwright_context(self):
        mw = UARotationMiddleware()
        request = FakeRequest(meta={"playwright": True})
        mw.process_request(request, FakeSpider())
        assert "playwright_context_kwargs" in request.meta
        assert "user_agent" in request.meta["playwright_context_kwargs"]
        assert isinstance(
            request.meta["playwright_context_kwargs"]["user_agent"], str
        )

    def test_ua_is_from_list(self):
        mw = UARotationMiddleware()
        request = FakeRequest()
        mw.process_request(request, FakeSpider())
        assert request.headers["User-Agent"] in USER_AGENTS
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/unit/test_middlewares.py -v
```

Expected: All 5 new tests pass.

- [ ] **Step 3: Run all tests**

```bash
pytest tests/ -v
```

Expected: 44 tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_middlewares.py
git commit -m "test: add middleware tests for proxy rotation and UA rotation"
```

---

### Task 11: Write Reddit spider integration tests

**Files:**
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_reddit_spider.py`

- [ ] **Step 1: Write `tests/integration/conftest.py`**

```python
"""Shared fixtures for integration tests."""

import os
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def reddit_rss():
    path = FIXTURES_DIR / "reddit_rss.xml"
    return path.read_text()


@pytest.fixture
def reddit_search_html():
    path = FIXTURES_DIR / "reddit_search.html"
    if path.exists():
        return path.read_text()
    return ""


@pytest.fixture
def hotmart_api_json():
    path = FIXTURES_DIR / "hotmart_api_response.json"
    return path.read_text()


@pytest.fixture
def hotmart_search_html():
    path = FIXTURES_DIR / "hotmart_search.html"
    return path.read_text()
```

- [ ] **Step 2: Write `tests/integration/test_reddit_spider.py`**

```python
import json

import feedparser
import pytest

from scrapper.items import PostItem


class TestRedditRSSParsing:
    def test_feedparser_parses_fixture(self, reddit_rss):
        feed = feedparser.parse(reddit_rss)
        assert len(feed.entries) == 2
        assert feed.entries[0]["title"] == "Python 3.13 released"
        assert "abc123" in feed.entries[0]["link"]

    def test_entries_have_required_fields(self, reddit_rss):
        feed = feedparser.parse(reddit_rss)
        for entry in feed.entries:
            assert entry.get("title"), f"Missing title in {entry}"
            assert entry.get("link"), f"Missing link in {entry}"
            assert entry.get("author"), f"Missing author in {entry}"


class TestRedditPostItemFromRSS:
    def test_build_post_item_from_rss_entry(self, reddit_rss):
        feed = feedparser.parse(reddit_rss)
        entry = feed.entries[0]

        item = PostItem(
            site="reddit",
            url=entry.get("link", ""),
            title=entry.get("title", ""),
            author=entry.get("author", ""),
            content="",
            score=0,
            comment_count=0,
            published_at=entry.get("updated", ""),
            metadata={"query": "python", "source": "rss"},
        )

        assert item["site"] == "reddit"
        assert item["url"] == entry["link"]
        assert item["title"] == "Python 3.13 released"
        assert item["author"] == "u_python_dev"
        assert item["published_at"] == "2026-04-15T10:30:00Z"


class TestPostItemFields:
    def test_score_is_integer_default(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test")
        assert item["score"] == 0
        assert isinstance(item["score"], int)

    def test_comment_count_is_integer_default(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test")
        assert item["comment_count"] == 0
        assert isinstance(item["comment_count"], int)

    def test_published_at_optional(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test")
        assert item.get("published_at") is None

    def test_published_at_when_set(self):
        item = PostItem(
            site="reddit",
            url="http://x.com/1",
            title="Test",
            published_at="2026-04-15T10:30:00Z",
        )
        assert item["published_at"] == "2026-04-15T10:30:00Z"

    def test_metadata_stores_query(self):
        item = PostItem(
            site="reddit",
            url="http://x.com/1",
            title="Test",
            metadata={"query": "python"},
        )
        assert item["metadata"]["query"] == "python"
```

- [ ] **Step 3: Run the new tests**

```bash
pytest tests/integration/test_reddit_spider.py -v
```

Expected: All new tests pass.

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v
```

Expected: 51 tests pass (44 previous + 7 new).

- [ ] **Step 5: Commit**

```bash
git add tests/integration/
git commit -m "test: add Reddit spider integration tests (RSS parsing, PostItem fields)"
```

---

### Task 12: Write Hotmart spider integration tests

**Files:**
- Create: `tests/integration/test_hotmart_spider.py`

- [ ] **Step 1: Write `tests/integration/test_hotmart_spider.py`**

```python
import json

import pytest

from scrapper.items import ProductItem
from scrapper.spiders.hotmart import _parse_price, _parse_review_count


class TestParsePrice:
    def test_dollar_price(self):
        assert _parse_price("$49.99") == 49.99

    def test_dollar_price_integer(self):
        assert _parse_price("$50") == 50.0

    def test_brazilian_real(self):
        assert _parse_price("R$ 79,90") == 79.90
        assert _parse_price("R$ 1.299,90") == 1299.90

    def test_empty_returns_none(self):
        assert _parse_price("") is None

    def test_none_returns_none(self):
        assert _parse_price(None) is None

    def test_non_numeric_returns_none(self):
        assert _parse_price("Free") is None


class TestParseReviewCount:
    def test_extracts_number(self):
        assert _parse_review_count("234 reviews") == 234

    def test_no_reviews(self):
        assert _parse_review_count("") == 0

    def test_none_returns_zero(self):
        assert _parse_review_count(None) == 0

    def test_no_number_found(self):
        assert _parse_review_count("No reviews") == 0


class TestHotmartAPIResponseParsing:
    def test_extract_products_from_fixture(self, hotmart_api_json):
        data = json.loads(hotmart_api_json)

        products = data["data"]["search"]["products"]
        assert len(products) == 2

        prod1 = products[0]
        assert prod1["name"] == "Digital Marketing Masterclass"
        assert prod1["price"]["value"] == 49.99
        assert prod1["rating"] == 4.7
        assert prod1["reviewCount"] == 234
        assert prod1["author"]["name"] == "John Smith"

    def test_build_product_item_from_api(self, hotmart_api_json):
        data = json.loads(hotmart_api_json)
        prod = data["data"]["search"]["products"][0]

        item = ProductItem(
            site="hotmart",
            url=prod["url"],
            title=prod["name"],
            price=prod["price"]["value"],
            currency=prod["price"]["currency"],
            rating=prod["rating"],
            review_count=prod["reviewCount"],
            seller=prod["author"]["name"],
            availability="",
            metadata={"query": "python"},
        )

        assert item["title"] == "Digital Marketing Masterclass"
        assert item["price"] == 49.99
        assert item["seller"] == "John Smith"
        assert item["review_count"] == 234


class TestProductItemDefaults:
    def test_price_none_by_default(self):
        item = ProductItem(site="hotmart", url="http://x.com", title="X")
        assert item.get("price") is None

    def test_review_count_zero_by_default(self):
        item = ProductItem(site="hotmart", url="http://x.com", title="X")
        assert item["review_count"] == 0
```

- [ ] **Step 2: Run the new tests**

```bash
pytest tests/integration/test_hotmart_spider.py -v
```

Expected: All new tests pass.

- [ ] **Step 3: Run all tests**

```bash
pytest tests/ -v
```

Expected: 63 tests pass (51 previous + 12 new).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_hotmart_spider.py
git commit -m "test: add Hotmart spider integration tests (price parsing, API response, ProductItem)"
```

---

### Task 13: Write stealth handler tests

**Files:**
- Create: `tests/integration/test_stealth.py`

- [ ] **Step 1: Write `tests/integration/test_stealth.py`**

```python
import os
import sys

import pytest


class TestStealthHandlerConfig:
    def test_handler_is_importable(self):
        from scrapper.stealth_handler import (
            ScrapyPlaywrightStealthDownloadHandler,
        )
        assert ScrapyPlaywrightStealthDownloadHandler is not None

    def test_settings_reference_correct_handler(self):
        from scrapper import settings

        handler = settings.DOWNLOAD_HANDLERS.get("https", "")
        assert "stealth_handler" in handler
        assert "ScrapyPlaywrightStealthDownloadHandler" in handler

    def test_headless_env_var_defaults_to_true(self):
        from scrapper import settings

        headless_val = settings.PLAYWRIGHT_LAUNCH_OPTIONS.get("headless", None)
        assert headless_val is True

    def test_blink_features_disabled(self):
        from scrapper import settings

        args = settings.PLAYWRIGHT_LAUNCH_OPTIONS.get("args", [])
        assert "--disable-blink-features=AutomationControlled" in args

    def test_human_simulation_defaults_to_true(self):
        from scrapper import settings

        assert settings.PLAYWRIGHT_HUMAN_SIMULATION is True
```

- [ ] **Step 2: Run the new tests**

```bash
pytest tests/integration/test_stealth.py -v
```

Expected: All 5 new tests pass.

- [ ] **Step 3: Run all tests**

```bash
pytest tests/ -v
```

Expected: 68 tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_stealth.py
git commit -m "test: add stealth handler config tests"
```

---

### Task 14: Final verification and coverage

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: All 68 tests pass with zero failures.

- [ ] **Step 2: Run lint**

```bash
ruff check src/ tests/
```

Expected: Zero lint errors.

- [ ] **Step 3: Check coverage**

```bash
pip install pytest-cov && pytest tests/ --cov=src/scrapper --cov-report=term-missing
```

Expected: Coverage > 55% (up from 40%). The remaining gap is Playwright browser integration (requires actual browser), which is expected.

- [ ] **Step 4: Verify scrapy list shows all spiders**

```bash
scrapy list
```

Expected: Output includes `reddit`, `hotmart`, `amazon`, `mercadolibre`, `quora`.

- [ ] **Step 5: Final commit (if any lint fixes needed)**

```bash
git status
```
