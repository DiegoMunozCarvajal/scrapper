# Web Scraping Platform — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-ready multi-site scraping platform using Scrapy + Playwright + Supabase.

**Architecture:** Scrapy crawling engine with scrapy-playwright for JS-heavy sites, Supabase Postgres for storage with auto-REST API. Scrapyd + ScrapydWeb for deployment, scheduling, and UI dashboard.

**Tech Stack:** Python 3.11+, Scrapy 2.11+, scrapy-playwright, supabase-py, playwright, python-dotenv, loguru, Docker.

---

## File Map

```
Files to CREATE:
  scrapy.cfg
  .env.example
  scripts/setup_supabase.sql
  docker-compose.yml
  Dockerfile
  src/scrapper/settings.py
  src/scrapper/items.py
  src/scrapper/pipelines.py
  src/scrapper/middlewares.py
  src/scrapper/extensions.py
  src/scrapper/spiders/__init__.py
  src/scrapper/spiders/reddit.py
  src/scrapper/spiders/amazon.py
  src/scrapper/spiders/mercadolibre.py
  src/scrapper/spiders/hotmart.py
  src/scrapper/spiders/quora.py
  tests/test_items.py
  tests/test_pipelines.py

Files to MODIFY:
  pyproject.toml — add scrapy, scrapy-playwright, supabase, python-dotenv
  src/scrapper/utils.py — add more user agents

Files KEPT as reference (not used by Scrapy runtime but preserved):
  src/scrapper/models.py — dataclasses (useful for tests)
  src/scrapper/main.py — old CLI (kept for reference)
  src/scrapper/scrapers/ — old Playwright scrapers (selector reference for porting)
```

---

## Milestone 1: Foundation — Production-Ready Scrapy Platform

### Task 1: Update Project Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Rewrite pyproject.toml with Scrapy stack dependencies**

Replace the entire file:

```toml
[project]
name = "scrapper"
version = "0.2.0"
description = "Multi-site web scraper — Reddit, Quora, Amazon, MercadoLibre, Hotmart"
requires-python = ">=3.11"
dependencies = [
    "scrapy>=2.11",
    "scrapy-playwright>=0.0.40",
    "playwright>=1.45",
    "supabase>=2.7",
    "beautifulsoup4>=4.12",
    "tenacity>=8.3",
    "loguru>=0.7",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "ruff>=0.4",
]

[tool.ruff]
line-length = 100

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -e ".[dev]"`
Expected: installs scrapy, scrapy-playwright, supabase, etc. without errors.

- [ ] **Step 3: Install Playwright browsers**

Run: `playwright install chromium`
Expected: downloads Chromium for Playwright.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: add scrapy, scrapy-playwright, supabase deps"
```

---

### Task 2: Create Environment & Scrapy Config

**Files:**
- Create: `.env.example`
- Create: `scrapy.cfg`

- [ ] **Step 1: Create .env.example**

```bash
# Supabase — get these from https://supabase.com/dashboard > Project > Settings > API
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_KEY=eyJhbGciOi...your-service-role-key

# Optional: datacenter proxy (http://user:pass@host:port)
PROXY_LIST=
```

- [ ] **Step 2: Create scrapy.cfg**

```ini
[settings]
default = src.scrapper.settings

[deploy]
project = src.scrapper
```

- [ ] **Step 3: Verify Scrapy detects the project**

Run: `scrapy list`
Expected: (empty — no spiders registered yet, but no error about missing project)

- [ ] **Step 4: Commit**

```bash
git add .env.example scrapy.cfg
git commit -m "feat: add Scrapy project config and env template"
```

---

### Task 3: Create Scrapy Items

**Files:**
- Create: `src/scrapper/items.py`

- [ ] **Step 1: Write items.py**

```python
import scrapy


class PostItem(scrapy.Item):
    site = scrapy.Field()
    url = scrapy.Field()
    title = scrapy.Field()
    author = scrapy.Field()
    content = scrapy.Field()
    score = scrapy.Field()
    comment_count = scrapy.Field()
    published_at = scrapy.Field()
    metadata = scrapy.Field()


class ProductItem(scrapy.Item):
    site = scrapy.Field()
    url = scrapy.Field()
    title = scrapy.Field()
    price = scrapy.Field()
    currency = scrapy.Field()
    rating = scrapy.Field()
    review_count = scrapy.Field()
    seller = scrapy.Field()
    availability = scrapy.Field()
    metadata = scrapy.Field()
```

- [ ] **Step 2: Write tests for items**

Create `tests/test_items.py`:

```python
import pytest
from scrapper.items import PostItem, ProductItem


def test_post_item_creation():
    item = PostItem(site="reddit", url="https://reddit.com/r/test/1", title="Test Post")
    assert item["site"] == "reddit"
    assert item["url"] == "https://reddit.com/r/test/1"
    assert item["title"] == "Test Post"
    assert item.get("score", 0) == 0


def test_post_item_defaults():
    item = PostItem(site="reddit", url="http://x.com", title="X")
    assert item["content"] == ""
    assert item["comment_count"] == 0
    assert item.get("published_at") is None


def test_product_item_creation():
    item = ProductItem(
        site="amazon",
        url="https://amazon.com/dp/B0TEST",
        title="Widget",
        price=29.99,
        currency="USD",
        rating=4.5,
        review_count=100,
        seller="Acme Corp",
        availability="In Stock",
        metadata={"asin": "B0TEST"},
    )
    assert item["site"] == "amazon"
    assert item["price"] == 29.99
    assert item["rating"] == 4.5
    assert item["metadata"]["asin"] == "B0TEST"


def test_product_item_defaults():
    item = ProductItem(site="ml", url="http://x.com", title="X")
    assert item.get("price") is None
    assert item.get("currency") == "USD"
    assert item.get("review_count") == 0


def test_post_item_missing_required_does_not_raise():
    item = PostItem()
    assert item.get("url") is None
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_items.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add src/scrapper/items.py tests/test_items.py
git commit -m "feat: add Scrapy PostItem and ProductItem with tests"
```

---

### Task 4: Create Scrapy Settings

**Files:**
- Create: `src/scrapper/settings.py`

- [ ] **Step 1: Write settings.py**

```python
import os
from dotenv import load_dotenv

load_dotenv()

BOT_NAME = "scrapper"

SPIDER_MODULES = ["scrapper.spiders"]
NEWSPIDER_MODULE = "scrapper.spiders"

# ── Politeness & compliance ──────────────────────────────
ROBOTSTXT_OBEY = True
USER_AGENT = "scrapper/0.2 (research crawler; contact@example.com)"

# ── Concurrency & throttling ─────────────────────────────
CONCURRENT_REQUESTS = 2
DOWNLOAD_DELAY = 2
RANDOMIZE_DOWNLOAD_DELAY = True

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

# ── Retries ──────────────────────────────────────────────
RETRY_ENABLED = True
RETRY_TIMES = 4
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

# ── Playwright ───────────────────────────────────────────
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {"headless": True}
PLAYWRIGHT_MAX_PAGES_PER_CONTEXT = 4

# ── Pipelines ────────────────────────────────────────────
ITEM_PIPELINES = {
    "scrapper.pipelines.ValidatePipeline": 100,
    "scrapper.pipelines.DedupInMemoryPipeline": 200,
    "scrapper.pipelines.SupabasePipeline": 300,
}

# ── Middleware ───────────────────────────────────────────
DOWNLOADER_MIDDLEWARES = {
    "scrapper.middlewares.RetryWithBackoffMiddleware": 550,
    "scrapper.middlewares.ProxyRotationMiddleware": 750,
    "scrapper.middlewares.UARotationMiddleware": 850,
}

# ── Extensions ───────────────────────────────────────────
EXTENSIONS = {
    "scrapper.extensions.ErrorAlerter": 500,
}

# ── Supabase ─────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ── Proxy pool (comma-separated proxy URLs) ─────────────
PROXY_LIST = os.getenv("PROXY_LIST", "")

# ── Alert webhook (Discord/Slack) ───────────────────────
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")

# ── Logging ──────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FILE = "scrapy.log"

# ── Timeouts ─────────────────────────────────────────────
DOWNLOAD_TIMEOUT = 30
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 30000
```

- [ ] **Step 2: Verify settings load**

Run: `python -c "from scrapper import settings; print(settings.BOT_NAME)"`
Expected: prints `scrapper` (no errors).

- [ ] **Step 3: Commit**

```bash
git add src/scrapper/settings.py
git commit -m "feat: add Scrapy settings with Playwright, Supabase, and middleware config"
```

---

### Task 5: Create Item Pipelines

**Files:**
- Create: `src/scrapper/pipelines.py`
- Test: `tests/test_pipelines.py`

- [ ] **Step 1: Write pipelines.py**

```python
from scrapy.exceptions import DropItem
from supabase import create_client

from .items import PostItem


class ValidatePipeline:
    """Drop items missing URL or title."""

    def process_item(self, item, spider):
        url = item.get("url")
        if not url:
            raise DropItem(f"Missing URL in item from {spider.name}")
        title = item.get("title")
        if not title:
            raise DropItem(f"Missing title in item from {spider.name}: {url}")
        return item


class DedupInMemoryPipeline:
    """Drop duplicate URLs within the same crawl run."""

    def __init__(self):
        self.seen: set[str] = set()

    def process_item(self, item, spider):
        url = item.get("url", "")
        if url in self.seen:
            raise DropItem(f"Duplicate URL in run: {url}")
        self.seen.add(url)
        return item


class SupabasePipeline:
    """Upsert items into Supabase Postgres tables."""

    def __init__(self, supabase_url: str, supabase_key: str):
        self.client = create_client(supabase_url, supabase_key)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            supabase_url=crawler.settings.get("SUPABASE_URL", ""),
            supabase_key=crawler.settings.get("SUPABASE_KEY", ""),
        )

    def process_item(self, item, spider):
        table = "posts" if isinstance(item, PostItem) else "products"
        data = dict(item)
        try:
            self.client.table(table).upsert(data, on_conflict="site,url").execute()
        except Exception as e:
            spider.logger.error(f"Supabase upsert failed for {item.get('url')}: {e}")
        return item
```

- [ ] **Step 2: Write tests for pipelines**

Create `tests/test_pipelines.py`:

```python
import pytest
from scrapy.exceptions import DropItem
from scrapper.items import PostItem
from scrapper.pipelines import ValidatePipeline, DedupInMemoryPipeline


class FakeSpider:
    name = "test_spider"


def test_validate_drops_missing_url():
    pipe = ValidatePipeline()
    item = PostItem(title="Has title but no URL")
    with pytest.raises(DropItem, match="Missing URL"):
        pipe.process_item(item, FakeSpider())


def test_validate_drops_missing_title():
    pipe = ValidatePipeline()
    item = PostItem(url="http://example.com", title="")
    with pytest.raises(DropItem, match="Missing title"):
        pipe.process_item(item, FakeSpider())


def test_validate_passes_valid_item():
    pipe = ValidatePipeline()
    item = PostItem(site="reddit", url="http://x.com", title="Valid")
    result = pipe.process_item(item, FakeSpider())
    assert result is item


def test_dedup_drops_duplicate():
    pipe = DedupInMemoryPipeline()
    item1 = PostItem(site="reddit", url="http://x.com/1", title="A")
    item2 = PostItem(site="reddit", url="http://x.com/1", title="B")
    pipe.process_item(item1, FakeSpider())
    with pytest.raises(DropItem, match="Duplicate URL"):
        pipe.process_item(item2, FakeSpider())


def test_dedup_allows_unique():
    pipe = DedupInMemoryPipeline()
    item1 = PostItem(site="reddit", url="http://x.com/1", title="A")
    item2 = PostItem(site="reddit", url="http://x.com/2", title="B")
    assert pipe.process_item(item1, FakeSpider()) is item1
    assert pipe.process_item(item2, FakeSpider()) is item2
```

- [ ] **Step 3: Run pipeline tests**

Run: `pytest tests/test_pipelines.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add src/scrapper/pipelines.py tests/test_pipelines.py
git commit -m "feat: add Validate, Dedup, and Supabase item pipelines with tests"
```

---

### Task 6: Create Downloader Middlewares

**Files:**
- Create: `src/scrapper/middlewares.py`

- [ ] **Step 1: Write middlewares.py**

```python
"""Custom Scrapy downloader middlewares for reliability and anti-bot."""

import random
from typing import Optional

from scrapy import signals
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_message
from twisted.internet import defer
from twisted.internet.error import TimeoutError, DNSLookupError, ConnectionRefusedError


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
    """Rotate through proxy list on each request."""

    def __init__(self, proxy_list: str):
        self.proxies = [p.strip() for p in proxy_list.split(",") if p.strip()]

    @classmethod
    def from_crawler(cls, crawler):
        return cls(proxy_list=crawler.settings.get("PROXY_LIST", ""))

    def process_request(self, request, spider):
        if not self.proxies:
            return None
        proxy = random.choice(self.proxies)
        request.meta["proxy"] = proxy
        spider.logger.debug(f"Using proxy: {proxy.split('@')[-1] if '@' in proxy else proxy}")
        return None


class UARotationMiddleware:
    """Rotate user agent on each request (for non-Playwright requests)."""

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:126.0) Gecko/20100101 Firefox/126.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    ]

    def process_request(self, request, spider):
        if request.meta.get("playwright"):
            return None
        ua = random.choice(self.USER_AGENTS)
        request.headers["User-Agent"] = ua
        return None
```

- [ ] **Step 2: Verify middlewares import**

Run: `python -c "from scrapper.middlewares import RetryWithBackoffMiddleware, ProxyRotationMiddleware, UARotationMiddleware; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/scrapper/middlewares.py
git commit -m "feat: add retry-backoff, proxy rotation, and UA rotation middlewares"
```

---

### Task 7: Create Error Alerter Extension

**Files:**
- Create: `src/scrapper/extensions.py`

- [ ] **Step 1: Write extensions.py**

```python
"""Scrapy extensions for monitoring and alerting."""

import json
from urllib.request import Request, urlopen

from scrapy import signals
from loguru import logger


class ErrorAlerter:
    """POST to a webhook URL when a spider encounters critical errors."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.error_count = 0

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls(webhook_url=crawler.settings.get("ALERT_WEBHOOK_URL", ""))
        crawler.signals.connect(ext.spider_error, signal=signals.spider_error)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_error(self, failure, response, spider):
        self.error_count += 1
        if self.error_count <= 5:
            logger.error(
                f"[{spider.name}] Error on {response.url if response else 'unknown'}: "
                f"{failure.getErrorMessage()}"
            )

    def spider_closed(self, spider, reason):
        if self.error_count > 5 and self.webhook_url:
            payload = json.dumps({
                "content": f":warning: **{spider.name}** closed with **{self.error_count} errors**. Reason: `{reason}`"
            }).encode()
            try:
                req = Request(self.webhook_url, data=payload, headers={"Content-Type": "application/json"})
                urlopen(req, timeout=5)
            except Exception as e:
                logger.error(f"Failed to send alert webhook: {e}")
```

- [ ] **Step 2: Verify extension imports**

Run: `python -c "from scrapper.extensions import ErrorAlerter; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/scrapper/extensions.py
git commit -m "feat: add ErrorAlerter extension with webhook notifications"
```

---

### Task 8: Create Reddit Spider

**Files:**
- Create: `src/scrapper/spiders/__init__.py`
- Create: `src/scrapper/spiders/reddit.py`

- [ ] **Step 1: Create spiders __init__.py**

```python
"""Scrapy spiders for multi-site scraping."""
```

- [ ] **Step 2: Write Reddit spider**

```python
# src/scrapper/spiders/reddit.py
import scrapy
from ..items import PostItem


class RedditSpider(scrapy.Spider):
    name = "reddit"
    site = "reddit"
    site_type = "post"

    custom_settings = {
        "DOWNLOAD_HANDLERS": {},                    # No Playwright — old.reddit.com is static HTML
        "CONCURRENT_REQUESTS": 1,                   # Reddit is rate-limit sensitive
        "DOWNLOAD_DELAY": 2,
    }

    def start_requests(self):
        query = getattr(self, "query", "python")
        limit = int(getattr(self, "limit", 10))
        url = f"https://old.reddit.com/search?q={query}&sort=relevance&type=link"
        yield scrapy.Request(url, meta={"query": query, "limit": limit, "count": 0})

    def parse(self, response):
        query = response.meta["query"]
        limit = response.meta["limit"]
        count = response.meta["count"]

        articles = response.css("article")
        for el in articles:
            if count >= limit:
                return

            title_el = el.css('a[slot="title"]')
            title = title_el.css("::text").get("")
            href = title_el.css("::attr(href)").get("")
            url = f"https://old.reddit.com{href}" if href else ""

            author = el.css('a[href*="/user/"]::text').get("")

            score_text = el.css('[data-testid="post-score"]::text').get("0")
            try:
                score = int(score_text)
            except (ValueError, TypeError):
                score = 0

            if title and url:
                count += 1
                yield PostItem(
                    site=self.site,
                    url=url,
                    title=title.strip(),
                    author=author.strip() if author else "",
                    content="",
                    score=score,
                    comment_count=0,
                    metadata={"query": query},
                )

        if count < limit:
            next_link = response.css('a[rel="nofollow next"]::attr(href)').get()
            if next_link:
                yield response.follow(
                    next_link,
                    meta={"query": query, "limit": limit, "count": count},
                )
```

- [ ] **Step 3: Verify spider is recognized**

Run: `scrapy list`
Expected: `reddit`

- [ ] **Step 4: Test the spider (dry run — no requests)**

Run: `scrapy crawl reddit -a query="python" -a limit=3 2>&1 | head -5`
Expected: spider starts without import errors (may fail on network if offline, that's fine).

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/spiders/__init__.py src/scrapper/spiders/reddit.py
git commit -m "feat: add Reddit spider (old.reddit.com, static HTML, no Playwright)"
```

---

### Task 9: Create Amazon Spider

**Files:**
- Create: `src/scrapper/spiders/amazon.py`

- [ ] **Step 1: Write Amazon spider**

```python
# src/scrapper/spiders/amazon.py
import re
import scrapy
from ..items import ProductItem


class AmazonSpider(scrapy.Spider):
    name = "amazon"
    site = "amazon"
    site_type = "product"

    custom_settings = {
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 4,
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
    }

    def start_requests(self):
        query = getattr(self, "query", "laptop")
        limit = int(getattr(self, "limit", 10))
        url = f"https://www.amazon.com/s?k={query}"
        yield scrapy.Request(
            url,
            meta={"playwright": True, "query": query, "limit": limit, "count": 0},
        )

    def parse(self, response):
        limit = response.meta["limit"]
        query = response.meta["query"]
        count = response.meta["count"]

        cards = response.css('[data-component-type="s-search-result"]')
        for card in cards:
            if count >= limit:
                return

            title_el = card.css("h2")
            title = title_el.css("::text").get("")
            href = title_el.css("a::attr(href)").get()
            url = f"https://www.amazon.com{href}" if href else ""

            whole = card.css(".a-price-whole::text").get("0")
            fraction = card.css(".a-price-fraction::text").get("00")
            price = _parse_price(f"{whole}.{fraction}")

            rating_text = card.css(".a-icon-alt::text").get("")
            rating = _parse_rating(rating_text)

            review_text = card.css(".a-size-base.s-underline-text::text").get("0")
            reviews = _parse_int(review_text)

            if title and url:
                count += 1
                yield ProductItem(
                    site=self.site,
                    url=url,
                    title=title.strip(),
                    price=price,
                    currency="USD",
                    rating=rating,
                    review_count=reviews,
                    seller="",
                    availability="",
                    metadata={"query": query},
                )


def _parse_price(text: str) -> float | None:
    cleaned = "".join(c for c in text if c.isdigit() or c == ".")
    return float(cleaned) if cleaned else None


def _parse_rating(text: str) -> float | None:
    match = re.search(r"(\d+\.?\d*)", text)
    return float(match.group(1)) if match else None


def _parse_int(text: str) -> int:
    cleaned = re.sub(r"[^\d]", "", text)
    return int(cleaned) if cleaned else 0
```

- [ ] **Step 2: Verify spider is recognized**

Run: `scrapy list`
Expected: `amazon` `reddit`

- [ ] **Step 3: Commit**

```bash
git add src/scrapper/spiders/amazon.py
git commit -m "feat: add Amazon spider with Playwright for JS rendering"
```

---

### Task 10: Create MercadoLibre Spider

**Files:**
- Create: `src/scrapper/spiders/mercadolibre.py`

- [ ] **Step 1: Write MercadoLibre spider**

```python
# src/scrapper/spiders/mercadolibre.py
import re
import scrapy
from ..items import ProductItem


class MercadoLibreSpider(scrapy.Spider):
    name = "mercadolibre"
    site = "mercadolibre"
    site_type = "product"

    custom_settings = {
        "CONCURRENT_REQUESTS": 2,
        "DOWNLOAD_DELAY": 2,
    }

    def start_requests(self):
        query = getattr(self, "query", "laptop")
        limit = int(getattr(self, "limit", 10))
        url = f"https://listado.mercadolibre.com.co/{query.replace(' ', '-')}"
        yield scrapy.Request(
            url,
            meta={"playwright": True, "query": query, "limit": limit, "count": 0},
        )

    def parse(self, response):
        limit = response.meta["limit"]
        query = response.meta["query"]
        count = response.meta["count"]

        items = response.css("li.ui-search-layout__item")
        for item in items:
            if count >= limit:
                return

            title = item.css("h2::text").get("")

            price_text = item.css(".andes-money-amount__fraction::text").get("")
            price = _parse_price(price_text)

            url = item.css("a.ui-search-link::attr(href)").get("")

            rating_text = item.css(".ui-search-reviews__rating-number::text").get("")
            rating = float(rating_text) if rating_text else None

            if title and url:
                count += 1
                yield ProductItem(
                    site=self.site,
                    url=url,
                    title=title.strip(),
                    price=price,
                    currency="COP",
                    rating=rating,
                    review_count=0,
                    seller="",
                    availability="",
                    metadata={"query": query},
                )


def _parse_price(text: str) -> float | None:
    cleaned = re.sub(r"[^\d]", "", text)
    return float(cleaned) if cleaned else None
```

- [ ] **Step 2: Verify spider is recognized**

Run: `scrapy list`
Expected: `amazon` `mercadolibre` `reddit`

- [ ] **Step 3: Commit**

```bash
git add src/scrapper/spiders/mercadolibre.py
git commit -m "feat: add MercadoLibre spider (.com.co, COP currency)"
```

---

### Task 11: Create Hotmart Spider

**Files:**
- Create: `src/scrapper/spiders/hotmart.py`

- [ ] **Step 1: Write Hotmart spider**

```python
# src/scrapper/spiders/hotmart.py
import re
import scrapy
from ..items import ProductItem


class HotmartSpider(scrapy.Spider):
    name = "hotmart"
    site = "hotmart"
    site_type = "product"

    custom_settings = {
        "CONCURRENT_REQUESTS": 2,
        "DOWNLOAD_DELAY": 3,
    }

    def start_requests(self):
        query = getattr(self, "query", "marketing")
        limit = int(getattr(self, "limit", 10))
        url = f"https://hotmart.com/en/marketplace/search?q={query}"
        yield scrapy.Request(
            url,
            meta={"playwright": True, "query": query, "limit": limit, "count": 0},
        )

    def parse(self, response):
        limit = response.meta["limit"]
        query = response.meta["query"]
        count = response.meta["count"]

        cards = response.css('[class*="product"]')
        for card in cards:
            if count >= limit:
                return

            title_el = card.css("h2, h3, [class*='title']")
            title = title_el.css("::text").get("")

            price_el = card.css("[class*='price'], [class*='Price']")
            price_text = price_el.css("::text").get("")
            price = _parse_price(price_text)

            url = card.css("a::attr(href)").get("")

            if title and url:
                count += 1
                yield ProductItem(
                    site=self.site,
                    url=url,
                    title=title.strip(),
                    price=price,
                    currency="USD",
                    rating=None,
                    review_count=0,
                    seller="",
                    availability="",
                    metadata={"query": query},
                )


def _parse_price(text: str) -> float | None:
    try:
        cleaned = "".join(c for c in text if c.isdigit() or c in ".,")
        cleaned = cleaned.replace(",", ".")
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None
```

- [ ] **Step 2: Verify spider is recognized**

Run: `scrapy list`
Expected: `amazon` `hotmart` `mercadolibre` `reddit`

- [ ] **Step 3: Commit**

```bash
git add src/scrapper/spiders/hotmart.py
git commit -m "feat: add Hotmart spider (marketplace SPA with Playwright)"
```

---

### Task 12: Create Quora Spider

**Files:**
- Create: `src/scrapper/spiders/quora.py`

- [ ] **Step 1: Write Quora spider**

```python
# src/scrapper/spiders/quora.py
import scrapy
from ..items import PostItem


class QuoraSpider(scrapy.Spider):
    name = "quora"
    site = "quora"
    site_type = "post"

    custom_settings = {
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 3,
    }

    def start_requests(self):
        query = getattr(self, "query", "python")
        limit = int(getattr(self, "limit", 10))
        url = f"https://www.quora.com/search?q={query}&type=question"
        yield scrapy.Request(
            url,
            meta={"playwright": True, "query": query, "limit": limit, "count": 0},
        )

    def parse(self, response):
        limit = response.meta["limit"]
        query = response.meta["query"]
        count = response.meta["count"]

        cards = response.css('[class*="qu-bg--white"]')
        for card in cards:
            if count >= limit:
                return

            title_el = card.css("span")
            title = "".join(title_el.css("::text").getall()).strip()

            href = card.css("a::attr(href)").get("")
            url = f"https://www.quora.com{href}" if href else ""

            if title and url:
                count += 1
                yield PostItem(
                    site=self.site,
                    url=url,
                    title=title,
                    author="quora",
                    content="",
                    score=0,
                    comment_count=0,
                    metadata={"query": query},
                )
```

- [ ] **Step 2: Verify all 5 spiders are recognized**

Run: `scrapy list`
Expected: `amazon` `hotmart` `mercadolibre` `quora` `reddit`

- [ ] **Step 3: Commit**

```bash
git add src/scrapper/spiders/quora.py
git commit -m "feat: add Quora spider (search with Playwright)"
```

---

### Task 13: Create Supabase Setup Script

**Files:**
- Create: `scripts/setup_supabase.sql`

- [ ] **Step 1: Write schema SQL**

```sql
-- scripts/setup_supabase.sql
-- Run this in Supabase SQL Editor: https://supabase.com/dashboard > SQL Editor

-- ── Lookup table for known target sites ──────────────
CREATE TABLE IF NOT EXISTS sites (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    type        TEXT NOT NULL CHECK (type IN ('post', 'product')),
    base_url    TEXT NOT NULL,
    active      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO sites (name, type, base_url) VALUES
    ('reddit', 'post', 'https://old.reddit.com'),
    ('quora', 'post', 'https://www.quora.com'),
    ('amazon', 'product', 'https://www.amazon.com'),
    ('mercadolibre', 'product', 'https://listado.mercadolibre.com.co'),
    ('hotmart', 'product', 'https://hotmart.com')
ON CONFLICT (name) DO NOTHING;

-- ── Scrape job tracking ─────────────────────────────
CREATE TABLE IF NOT EXISTS scrape_jobs (
    id            BIGSERIAL PRIMARY KEY,
    site_id       INTEGER REFERENCES sites(id),
    query         TEXT NOT NULL,
    status        TEXT DEFAULT 'pending' CHECK (status IN ('pending','running','done','failed')),
    items_scraped INTEGER DEFAULT 0,
    error_message TEXT,
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ── Social / Q&A posts ──────────────────────────────
CREATE TABLE IF NOT EXISTS posts (
    id            BIGSERIAL PRIMARY KEY,
    site          TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT,
    author        TEXT,
    content       TEXT,
    score         INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    published_at  TIMESTAMPTZ,
    metadata      JSONB DEFAULT '{}',
    scrape_job_id INTEGER REFERENCES scrape_jobs(id),
    scraped_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(site, url)
);

-- ── E-commerce products ─────────────────────────────
CREATE TABLE IF NOT EXISTS products (
    id            BIGSERIAL PRIMARY KEY,
    site          TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT,
    price         DECIMAL(12,2),
    currency      TEXT DEFAULT 'USD',
    rating        DECIMAL(3,2),
    review_count  INTEGER DEFAULT 0,
    seller        TEXT,
    availability  TEXT,
    metadata      JSONB DEFAULT '{}',
    scrape_job_id INTEGER REFERENCES scrape_jobs(id),
    scraped_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(site, url)
);

-- ── Indexes ─────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_posts_site ON posts(site);
CREATE INDEX IF NOT EXISTS idx_posts_scraped_at ON posts(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_products_site ON products(site);
CREATE INDEX IF NOT EXISTS idx_products_price ON products(price);
CREATE INDEX IF NOT EXISTS idx_products_scraped_at ON products(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_scrape_jobs_status ON scrape_jobs(status);
```

- [ ] **Step 2: Commit**

```bash
git add scripts/setup_supabase.sql
git commit -m "feat: add Supabase schema SQL with sites, jobs, posts, products tables"
```

---

### Task 14: Create Docker Support

**Files:**
- Create: `docker-compose.yml`
- Create: `Dockerfile`

- [ ] **Step 1: Write Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir scrapy scrapy-playwright supabase python-dotenv loguru tenacity
RUN playwright install-deps chromium
RUN playwright install chromium

COPY src/ /app/src/
COPY scrapy.cfg /app/

ENV PYTHONPATH=/app/src
CMD ["scrapy"]
```

- [ ] **Step 2: Write docker-compose.yml**

```yaml
version: "3.8"

services:
  scrapyd:
    image: vimagick/scrapyd:latest
    ports:
      - "6800:6800"
    volumes:
      - ./src:/scrapy/src
      - ./scrapy.cfg:/scrapy/scrapy.cfg
      - scrapyd_data:/scrapy/data
    restart: unless-stopped

  scrapydweb:
    image: my8100/scrapydweb:latest
    ports:
      - "5000:5000"
    environment:
      SCRAPYDWEB_USERNAME: admin
      SCRAPYDWEB_PASSWORD: ${ADMIN_PASSWORD:-admin}
      SCRAPYD_SERVERS_0_URL: http://scrapyd:6800
    depends_on:
      - scrapyd
    restart: unless-stopped

volumes:
  scrapyd_data:
```

- [ ] **Step 3: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "feat: add Dockerfile and docker-compose for Scrapyd + ScrapydWeb deployment"
```

---

### Task 15: Add More User Agents to Utils

**Files:**
- Modify: `src/scrapper/utils.py`

- [ ] **Step 1: Extend user agent list**

Replace the USER_AGENTS list in `src/scrapper/utils.py`:

```python
USER_AGENTS = [
    # Chrome 125 — Windows / Mac / Linux
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # Firefox 126
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:126.0) Gecko/20100101 Firefox/126.0",
    # Edge 125
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    # Safari 17
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]
```

- [ ] **Step 2: Commit**

```bash
git add src/scrapper/utils.py
git commit -m "feat: extend user agent pool for UA rotation middleware"
```

---

### Task 16: End-to-End Verification

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: all tests PASS.

- [ ] **Step 2: Verify all spiders are discoverable**

Run: `scrapy list`
Expected:
```
amazon
hotmart
mercadolibre
quora
reddit
```

- [ ] **Step 3: Check Reddit spider (needs network)**

Run: `scrapy crawl reddit -a query="python programming" -a limit=3`
Expected: spider runs, extracts 3 posts with titles and URLs, no crashes. (If no network, skip.)

- [ ] **Step 4: Lint code**

Run: `ruff check src/ tests/`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "milestone: complete Scrapy platform foundation — 5 spiders, 3 pipelines, 3 middlewares, Supabase schema, Docker support"
```

---

## Milestone 2: Reliability Enhancements (next session)

### Task 17: Tune AutoThrottle per Spider
- Reddit: DOWNLOAD_DELAY=2, CONCURRENT_REQUESTS=1
- Amazon: DOWNLOAD_DELAY=5, CONCURRENT_REQUESTS=1
- MercadoLibre: DOWNLOAD_DELAY=2, CONCURRENT_REQUESTS=2
- Hotmart: DOWNLOAD_DELAY=3, CONCURRENT_REQUESTS=2
- Quora: DOWNLOAD_DELAY=3, CONCURRENT_REQUESTS=1

### Task 18: Add Stats Collection
- Log items/minute, error rate, response times per spider

### Task 19: Add Playwright Stealth
- Install `playwright-stealth` pip package
- Apply stealth patches in spider's `start_requests` for anti-bot sites

### Task 20: Add Session/Cookie Persistence
- Save and restore cookies between runs for login-required sites

---

## Milestone 3: More Spiders (Iterate)

### Task 21: Add Reddit detail scraping
- Follow post URLs to extract post content + top comment

### Task 22: Add Amazon detail scraping
- Follow product URLs to extract description, seller info

### Task 23: Test each spider against live sites
- Manual verification of selectors against current site structure
- Fix broken selectors

---

## Milestone 4: Operations

### Task 24: Deploy to VPS via Docker
- `docker compose up -d` on Hetzner VPS
- Configure ScrapydWeb cron jobs

### Task 25: Set up alert webhook
- Create Discord webhook URL
- Set `ALERT_WEBHOOK_URL` in environment

### Task 26: Health check script
- Bash script to poll Scrapyd `/daemonstatus.json`
- Cron job to run health check every 5 min

---

## Milestone 5: Advanced (Week 2+)

### Task 27: Incremental scraping
- Query Supabase for most recent `scraped_at` per site/query
- Stop pagination when items are older than threshold

### Task 28: Future API
- Supabase auto-REST API already available at `https://<project>.supabase.co/rest/v1/posts`
- Add Row Level Security policies for API access control

### Task 29: Instagram spider
- Requires residential proxies and session management
- Assessment needed before implementation

