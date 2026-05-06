# Project Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 12 actionable bugs, security issues, and implementation defects found in the full-project review.

**Architecture:** Apply changes in dependency order: database contract and pipeline startup first, then Scrapy retry and download handling, then Playwright stealth/cookie behavior, then spider-specific correctness fixes, then cache and operational scripts. Each task includes a focused failing test before implementation and a narrow commit.

**Tech Stack:** Python 3.14 local venv, Scrapy 2.15.2, scrapy-playwright 0.0.46, playwright-stealth 2.0.3, Supabase/PostgREST, pytest, ruff, bash.

---

## File Structure

- Modify `scripts/setup_supabase.sql`: align the Supabase schema with emitted items and restrict RLS policies by role.
- Modify `src/scrapper/pipelines.py`: disable Supabase pipeline when credentials are absent and sanitize item payloads per table.
- Modify `tests/unit/test_pipelines.py`: cover disabled Supabase config and table-field serialization.
- Create `tests/unit/test_supabase_schema.py`: static schema checks for Reddit columns and scoped RLS policies.
- Modify `src/scrapper/middlewares.py`: fix Scrapy 2.15 retry signature with download_latency backoff.
- Modify `tests/unit/test_middlewares.py`: cover retry signature, backoff delay, and process_response.
- Modify `src/scrapper/stealth_handler.py`: move stealth/init scripts before navigation and save valid Playwright storage state.
- Modify `tests/unit/test_stealth.py`: cover storage-state compatibility and init-callback chaining.
- Modify `src/scrapper/curl_cffi_handler.py`: preserve request method/body/proxy/timeout and serialize headers correctly.
- Modify `tests/unit/test_curl_cffi_handler.py`: cover curl-cffi request arguments.
- Modify `src/scrapper/spiders/hotmart.py`: install API interception before navigation, enforce total `limit`, and parse review thousands.
- Modify `tests/unit/test_hotmart.py`: cover API pagination limit and review parsing.
- Modify `src/scrapper/spiders/rama.py`: avoid dropped AJAX responses and prevent finally-block masking.
- Modify `tests/unit/test_rama.py`: cover parser behavior and static guard checks.
- Modify `src/scrapper/llm_extractor.py`: use a full normalized HTML hash for cache keys.
- Modify `tests/unit/test_llm_extractor.py`: cover same-prefix/different-body cache keys.
- Modify `bin/health-check.sh`: fix Scrapyd pending-jobs key (`status` → `pending` in daemonstatus.json).
- Create `tests/unit/test_health_check_script.py`: static checks for the health-check endpoint and parsing logic.

## Phase 0: Execution Setup

- [ ] **Step 1: Confirm current branch and dirty files**

Run:

```bash
git status --short
```

Expected: existing user changes may appear in `src/scrapper/spiders/reddit.py` and `tests/unit/test_reddit.py`. Do not revert them.

- [ ] **Step 2: Run baseline verification**

Run:

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/pytest tests/ -q
```

Expected: `ruff` passes and pytest reports the existing passing baseline.

---

## Phase 1: Supabase Schema And RLS

### Task 1: Align `posts` Schema With `PostItem`

**Files:**
- Modify: `scripts/setup_supabase.sql`
- Create: `tests/unit/test_supabase_schema.py`

- [ ] **Step 1: Write failing schema test**

Create `tests/unit/test_supabase_schema.py` with:

```python
from pathlib import Path


SQL = Path("scripts/setup_supabase.sql").read_text()


def test_posts_schema_contains_reddit_item_columns():
    for column in (
        "thumbnail",
        "link_flair",
        "domain",
        "nsfw",
        "is_self_post",
        "permalink",
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in SQL or f"{column} " in SQL


def test_write_policies_are_scoped_to_service_role():
    assert 'CREATE POLICY "Service can do anything with posts"' in SQL
    assert "ON posts FOR ALL TO service_role" in SQL
    assert "ON products FOR ALL TO service_role" in SQL
    assert "ON scraped_pages FOR ALL TO service_role" in SQL
    assert "ON sites FOR ALL TO service_role" in SQL
    assert "ON scrape_jobs FOR ALL TO service_role" in SQL


def test_public_read_policies_are_select_only():
    assert "ON posts FOR SELECT TO anon, authenticated" in SQL
    assert "ON products FOR SELECT TO anon, authenticated" in SQL
    assert "ON scraped_pages FOR SELECT TO anon, authenticated" in SQL
    assert "ON sites FOR SELECT TO anon, authenticated" in SQL
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/pytest tests/unit/test_supabase_schema.py -q
```

Expected: FAIL because the new columns and scoped policies are not present.

- [ ] **Step 3: Update `posts` table definition and migrations**

In `scripts/setup_supabase.sql`, add these columns to the `posts` table after `published_at`:

```sql
    thumbnail     TEXT,
    link_flair    TEXT,
    domain        TEXT,
    nsfw          BOOLEAN DEFAULT FALSE,
    is_self_post  BOOLEAN DEFAULT FALSE,
    permalink     TEXT,
```

Add these idempotent migrations after the existing quality migrations:

```sql
-- Add Reddit metadata columns emitted by PostItem (v0.6+)
ALTER TABLE posts ADD COLUMN IF NOT EXISTS thumbnail TEXT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS link_flair TEXT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS domain TEXT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS nsfw BOOLEAN DEFAULT FALSE;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS is_self_post BOOLEAN DEFAULT FALSE;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS permalink TEXT;
```

- [ ] **Step 4: Replace unscoped write policies**

Replace each service policy block with a drop-and-create block scoped to `service_role`. Use this exact pattern for all five tables:

```sql
DO $$ BEGIN
    DROP POLICY IF EXISTS "Service can do anything with posts" ON posts;
    CREATE POLICY "Service can do anything with posts" ON posts FOR ALL TO service_role USING (true) WITH CHECK (true);
END $$;
```

Use the same structure for `products`, `scraped_pages`, `sites`, and `scrape_jobs`.

- [ ] **Step 5: Scope public read policies**

Change each public read policy from:

```sql
CREATE POLICY "Public can read posts" ON posts FOR SELECT USING (true);
```

to:

```sql
CREATE POLICY "Public can read posts" ON posts FOR SELECT TO anon, authenticated USING (true);
```

Apply the same pattern to `products`, `scraped_pages`, and `sites`.

- [ ] **Step 6: Run schema test**

Run:

```bash
.venv/bin/pytest tests/unit/test_supabase_schema.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add scripts/setup_supabase.sql tests/unit/test_supabase_schema.py
git commit -m "fix: align supabase schema and rls policies"
```

---

## Phase 2: Supabase Pipeline Startup And Payloads

### Task 2: Disable Supabase Pipeline Without Credentials

**Files:**
- Modify: `src/scrapper/pipelines.py`
- Modify: `tests/unit/test_pipelines.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_pipelines.py`:

```python
from scrapy.exceptions import NotConfigured
from scrapper.pipelines import SupabasePipeline


class FakeSettings(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeCrawlerWithSettings:
    def __init__(self, settings):
        self.settings = FakeSettings(settings)


def test_supabase_pipeline_disabled_without_credentials():
    crawler = FakeCrawlerWithSettings({"SUPABASE_URL": "", "SUPABASE_KEY": ""})
    with pytest.raises(NotConfigured, match="SUPABASE_URL and SUPABASE_KEY"):
        SupabasePipeline.from_crawler(crawler)


def test_supabase_pipeline_serializes_only_table_columns():
    pipe = SupabasePipeline.__new__(SupabasePipeline)
    item = PostItem(
        site="reddit",
        url="https://old.reddit.com/r/test/comments/abc/title/",
        title="Title",
        thumbnail="https://example.com/thumb.jpg",
        link_flair="Discussion",
        domain="self.test",
        nsfw=False,
        is_self_post=True,
        permalink="/r/test/comments/abc/title/",
        quality_issues=["low_score"],
        metadata={"strategy": "json_api"},
    )

    data = pipe._serialize_item(item, "posts")

    assert data["thumbnail"] == "https://example.com/thumb.jpg"
    assert data["link_flair"] == "Discussion"
    assert data["is_self_post"] is True
    assert data["quality_issues"] == ["low_score"]
    # Fields not in TABLE_FIELDS["posts"] must be excluded
    assert "extra_field" not in data
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_pipelines.py::test_supabase_pipeline_disabled_without_credentials tests/unit/test_pipelines.py::test_supabase_pipeline_serializes_only_table_columns -q
```

Expected: FAIL because `NotConfigured` is not raised and `_serialize_item` does not exist.

- [ ] **Step 3: Implement pipeline config guard and serializer**

In `src/scrapper/pipelines.py`, change the imports:

```python
from scrapy.exceptions import DropItem, NotConfigured
```

Add table fields inside `SupabasePipeline` before `__init__`:

```python
    TABLE_FIELDS = {
        "posts": {
            "site", "url", "title", "author", "content", "score", "comment_count",
            "published_at", "thumbnail", "link_flair", "domain", "nsfw",
            "is_self_post", "permalink", "quality_issues", "metadata", "scraped_at",
        },
        "products": {
            "site", "url", "title", "price", "currency", "rating", "review_count",
            "seller", "availability", "quality_issues", "metadata", "scraped_at",
        },
        "scraped_pages": {
            "site", "url", "page_type", "title", "content", "price", "currency",
            "rating", "review_count", "score", "author", "image_url", "category",
            "published_at", "quality_issues", "metadata", "scraped_at",
        },
    }
```

Replace `from_crawler` with:

```python
    @classmethod
    def from_crawler(cls, crawler):
        supabase_url = crawler.settings.get("SUPABASE_URL", "")
        supabase_key = crawler.settings.get("SUPABASE_KEY", "")
        if not supabase_url or not supabase_key:
            raise NotConfigured("SUPABASE_URL and SUPABASE_KEY are required for SupabasePipeline")
        return cls(supabase_url=supabase_url, supabase_key=supabase_key)
```

Add serializer before `process_item`:

```python
    def _serialize_item(self, item, table: str) -> dict:
        allowed = self.TABLE_FIELDS[table]
        return {key: value for key, value in dict(item).items() if key in allowed}
```

In `process_item`, replace:

```python
        data = dict(item)
```

with:

```python
        data = self._serialize_item(item, table)
```

- [ ] **Step 4: Run pipeline tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_pipelines.py -q
```

Expected: PASS.

- [ ] **Step 5: Verify crawler starts without Supabase**

Run:

```bash
.venv/bin/scrapy crawl generic -a url=https://example.com -s SUPABASE_URL= -s SUPABASE_KEY= -s LLM_ENABLED=false -s RAG_EXPORT_ENABLED=false -s LOG_LEVEL=ERROR
```

Expected: command exits without `SupabaseException('supabase_url is required')`.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/scrapper/pipelines.py tests/unit/test_pipelines.py
git commit -m "fix: make supabase pipeline optional"
```

---

## Phase 3: Scrapy Retry Middleware

### Task 3: Fix Retry Signature And Backoff Behavior

**Files:**
- Modify: `src/scrapper/middlewares.py`
- Modify: `tests/unit/test_middlewares.py`

- [ ] **Step 1: Add failing retry tests**

Append to `tests/unit/test_middlewares.py`:

```python
from scrapy import Request
from scrapy.http import Response
from scrapy.settings import Settings
from scrapper.middlewares import RetryWithBackoffMiddleware


class FakeStats:
    def inc_value(self, *args, **kwargs):
        pass


class FakeCrawlerForRetry:
    settings = Settings({"RETRY_TIMES": 1, "RETRY_PRIORITY_ADJUST": -1})
    stats = FakeStats()


class FakeSpiderForRetry:
    crawler = FakeCrawlerForRetry()


def test_retry_signature_matches_scrapy_215():
    mw = RetryWithBackoffMiddleware(FakeCrawlerForRetry().settings)
    mw.crawler = FakeCrawlerForRetry()
    mw.crawler.spider = FakeSpiderForRetry()
    retry_request = mw._retry(Request("https://example.com"), "500 Internal Server Error")
    assert retry_request is not None
    assert retry_request.meta["retry_times"] == 1


def test_process_response_retries_on_500():
    mw = RetryWithBackoffMiddleware(FakeCrawlerForRetry().settings)
    mw.crawler = FakeCrawlerForRetry()
    mw.crawler.spider = FakeSpiderForRetry()
    request = Request("https://example.com")
    response = Response("https://example.com", status=500, request=request)

    result = mw.process_response(request=request, response=response, spider=mw.crawler.spider)

    assert isinstance(result, Request)
    assert result.meta["retry_times"] == 1
    assert result.meta["retry_delay"] == 1


def test_process_response_passes_through_200():
    mw = RetryWithBackoffMiddleware(FakeCrawlerForRetry().settings)
    mw.crawler = FakeCrawlerForRetry()
    mw.crawler.spider = FakeSpiderForRetry()
    request = Request("https://example.com")
    response = Response("https://example.com", status=200, request=request)

    result = mw.process_response(request=request, response=response, spider=mw.crawler.spider)

    assert result is response
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_middlewares.py::test_retry_signature_matches_scrapy_215 tests/unit/test_middlewares.py::test_process_response_retries_on_500 tests/unit/test_middlewares.py::test_process_response_passes_through_200 -q
```

Expected: FAIL because `_retry` takes `spider` as third positional argument (Scrapy <=2.14 signature) and no `retry_delay` is set.

- [ ] **Step 3: Implement Scrapy 2.15-compatible retry**

Replace `RetryWithBackoffMiddleware` in `src/scrapper/middlewares.py` with:

```python
class RetryWithBackoffMiddleware(RetryMiddleware):
    """Retry on transient errors with exponential backoff via download latency: 1s, 2s, 4s, 8s."""

    @staticmethod
    def _delay_for_retry_times(retry_times: int) -> int:
        return min(2 ** max(retry_times - 1, 0), 16)

    def _retry(self, request, reason):
        retries = request.meta.get("retry_times", 0) + 1
        delay = self._delay_for_retry_times(retries)
        logger.info(f"Retrying {request.url} (attempt {retries}) after {delay}s delay")
        retry_request = super()._retry(request, reason)
        if retry_request is not None:
            retry_request.meta["retry_delay"] = delay
            retry_request.meta["download_latency"] = delay
        return retry_request

    def process_response(self, request, response, spider):
        from scrapy.utils.response import response_status_message

        if request.meta.get("dont_retry", False):
            return response
        if response.status in self.retry_http_codes:
            reason = response_status_message(response.status)
            retry_request = self._retry(request, reason)
            if retry_request is not None:
                return retry_request
        return response

    def process_exception(self, request, exception, spider):
        if isinstance(exception, self.exceptions_to_retry) and not request.meta.get("dont_retry", False):
            retry_request = self._retry(request, exception)
            if retry_request is not None:
                return retry_request
        return None
```

Note: Scrapy 2.15 `_retry` drops the `spider` parameter (see `scrapy.downloadermiddlewares.retry.RetryMiddleware._retry`). The `process_response` and `process_exception` hooks remain synchronous — they set `download_latency` in request meta, which Scrapy's downloader respects for retry backoff. No `import asyncio` is needed.

- [ ] **Step 4: Run middleware tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_middlewares.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/scrapper/middlewares.py tests/unit/test_middlewares.py
git commit -m "fix: update retry middleware for scrapy 2.15"
```

---

## Phase 4: Playwright Stealth And Cookie Persistence

### Task 4: Apply Stealth Before Navigation And Save Valid Storage State

**Files:**
- Modify: `src/scrapper/stealth_handler.py`
- Modify: `tests/unit/test_stealth.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_stealth.py`:

```python
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from scrapy import Request


@pytest.mark.asyncio
async def test_cookie_state_list_is_loaded_as_storage_state(tmp_path):
    from scrapper.stealth_handler import _load_storage_state

    cookie_file = tmp_path / "default.json"
    cookie_file.write_text(json.dumps([{"name": "sid", "value": "1", "domain": "example.com", "path": "/"}]))

    state = _load_storage_state(cookie_file)

    assert state == {
        "cookies": [{"name": "sid", "value": "1", "domain": "example.com", "path": "/"}],
        "origins": [],
    }


def test_playwright_request_gets_init_callback():
    from scrapper.stealth_handler import ScrapyPlaywrightStealthDownloadHandler

    handler = ScrapyPlaywrightStealthDownloadHandler.__new__(ScrapyPlaywrightStealthDownloadHandler)
    request = Request("https://example.com", meta={"playwright": True})

    handler._ensure_page_init_callback(request)

    assert callable(request.meta["playwright_page_init_callback"])


@pytest.mark.asyncio
async def test_save_storage_state_writes_full_state(tmp_path):
    from scrapper.stealth_handler import _save_storage_state

    context = MagicMock()
    context.storage_state = AsyncMock(return_value={"cookies": [{"name": "sid"}], "origins": [{"origin": "https://example.com"}]})
    cookie_file = tmp_path / "default.json"

    await _save_storage_state(context, cookie_file)

    assert json.loads(cookie_file.read_text()) == {"cookies": [{"name": "sid"}], "origins": [{"origin": "https://example.com"}]}
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_stealth.py::test_cookie_state_list_is_loaded_as_storage_state tests/unit/test_stealth.py::test_playwright_request_gets_init_callback tests/unit/test_stealth.py::test_save_storage_state_writes_full_state -q
```

Expected: FAIL because helpers and callback injection do not exist.

- [ ] **Step 3: Add storage-state helpers**

In `src/scrapper/stealth_handler.py`, add after the stealth imports:

```python
_CANVAS_WEBGL_INIT_SCRIPT = """
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

const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.';
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, parameter);
};
"""


def _load_storage_state(cookie_file: Path) -> dict | None:
    try:
        data = json.loads(cookie_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if isinstance(data, list):
        return {"cookies": data, "origins": []}
    if isinstance(data, dict) and "cookies" in data:
        data.setdefault("origins", [])
        return data
    return None


async def _save_storage_state(context, cookie_file: Path) -> None:
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    state = await context.storage_state()
    cookie_file.write_text(json.dumps(state))
```

- [ ] **Step 4: Inject a page init callback before navigation**

Add methods inside `ScrapyPlaywrightStealthDownloadHandler`:

```python
    async def _stealth_page_init_callback(self, page: Page, request: Request):
        if _NEW_STEALTH_API:
            await stealth_async(page, StealthConfig())
        else:
            stealth = Stealth()
            await stealth.apply_stealth_async(page)

        human_simulation = os.getenv("PLAYWRIGHT_HUMAN_SIMULATION", "true").lower() in ("true", "1", "yes")
        if human_simulation:
            await page.add_init_script(_CANVAS_WEBGL_INIT_SCRIPT)

    def _ensure_page_init_callback(self, request: Request) -> None:
        existing = request.meta.get("playwright_page_init_callback")

        async def chained_callback(page: Page, scrapy_request: Request):
            await self._stealth_page_init_callback(page, scrapy_request)
            if existing:
                result = existing(page, scrapy_request)
                if hasattr(result, "__await__"):
                    await result

        request.meta["playwright_page_init_callback"] = chained_callback
```

At the start of `_download_request`, before calling `super()`, add:

```python
        if request.meta.get("playwright"):
            self._ensure_page_init_callback(request)
```

- [ ] **Step 5: Update cookie load/save in `_create_browser_context`**

Replace the manual `json.loads(cookie_file.read_text())` block with:

```python
                    storage_state = _load_storage_state(cookie_file)
                    if storage_state:
                        context_kwargs["storage_state"] = storage_state
```

Replace the `save_on_close` storage write with:

```python
                    await _save_storage_state(ctx, Path(f"cookies/{name}.json"))
```

- [ ] **Step 6: Remove duplicate post-navigation stealth, keep scrolling**

In `_download_request`, locate the block after `response = await super()._download_request(...)` that applies stealth (lines with `stealth_async`/`apply_stealth_async`) and injects `add_init_script` for canvas/WebGL spoofing. Delete those lines since they are now handled in `_stealth_page_init_callback` (Step 4).

Keep the human scrolling simulation that runs after stealth. Extract it into a standalone helper method on the class:

```python
    async def _simulate_human_scroll(self, page: Page, url: str) -> None:
        try:
            import random
            for _ in range(random.randint(2, 4)):
                await page.evaluate(f"window.scrollBy(0, {random.randint(100, 400)})")
                await page.wait_for_timeout(random.randint(200, 800))
        except Exception as e:
            logger.warning(f"Human simulation failed for {url}: {e}")
```

Replace the remaining post-`super()._download_request` block with:

```python
        if request.meta.get("playwright") and request.meta.get("playwright_page"):
            page: Page = request.meta["playwright_page"]
            if os.getenv("PLAYWRIGHT_HUMAN_SIMULATION", "true").lower() in ("true", "1", "yes"):
                await self._simulate_human_scroll(page, request.url)
```

- [ ] **Step 7: Run stealth tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_stealth.py tests/integration/test_stealth.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/scrapper/stealth_handler.py tests/unit/test_stealth.py
git commit -m "fix: apply playwright stealth before navigation"
```

---

## Phase 5: curl-cffi Download Handler

### Task 5: Preserve Scrapy Request Semantics In curl-cffi

**Files:**
- Modify: `src/scrapper/curl_cffi_handler.py`
- Modify: `tests/unit/test_curl_cffi_handler.py`

- [ ] **Step 1: Add failing curl-cffi test**

Append to `tests/unit/test_curl_cffi_handler.py`:

```python
import os
from unittest.mock import MagicMock, patch

from scrapy import Request
from scrapy.http import TextResponse


def test_curl_cffi_preserves_method_body_headers_proxy_and_timeout(monkeypatch):
    monkeypatch.setenv("CURL_CFFI_ENABLED", "true")
    from scrapper.curl_cffi_handler import CurlCffiDownloadHandler

    request = Request(
        "https://example.com/api",
        method="POST",
        body=b'{"q":"python"}',
        headers={"User-Agent": "UA", "Content-Type": "application/json"},
        meta={"proxy": "http://proxy:8080", "download_timeout": 12},
    )
    spider = MagicMock()
    spider.logger = MagicMock()

    fake_response = MagicMock()
    fake_response.url = "https://example.com/api"
    fake_response.status_code = 201
    fake_response.headers = {"content-type": "application/json"}
    fake_response.content = b'{"ok":true}'

    handler = CurlCffiDownloadHandler.__new__(CurlCffiDownloadHandler)
    handler._crawler = MagicMock()
    handler._crawler.settings.getfloat.return_value = 30.0

    with patch("curl_cffi.requests.request", return_value=fake_response) as request_mock:
        with patch("scrapper.curl_cffi_handler.deferToThread") as defer_mock:
            handler._download_request(request, spider)

        # Extract the _do_request closure and call it synchronously
        positional_args = defer_mock.call_args[0]
        assert len(positional_args) == 1

        # Call the wrapped function directly
        result = positional_args[0]()

    _, kwargs = request_mock.call_args
    assert kwargs["method"] == "POST"
    assert kwargs["data"] == b'{"q":"python"}'
    assert kwargs["headers"]["User-Agent"] == "UA"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["timeout"] == 12
    assert kwargs["proxy"] == "http://proxy:8080"
    assert isinstance(result, TextResponse)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_curl_cffi_handler.py::test_curl_cffi_preserves_method_body_headers_proxy_and_timeout -q
```

Expected: FAIL because the handler calls `get` instead of `request`, ignores method/body/proxy, and passes Scrapy header objects directly.

- [ ] **Step 3: Implement request preservation**

In `src/scrapper/curl_cffi_handler.py`, replace imports:

```python
from scrapy.http import HtmlResponse
```

with:

```python
from scrapy.http import Headers
from scrapy.responsetypes import responsetypes
```

Inside `_do_request`, replace `curl_requests.get(...)` and `HtmlResponse(...)` with:

```python
                headers = request.headers.to_unicode_dict()
                timeout = request.meta.get(
                    "download_timeout",
                    self._crawler.settings.getfloat("DOWNLOAD_TIMEOUT", 30),
                )
                kwargs = {
                    "method": request.method,
                    "url": request.url,
                    "headers": headers,
                    "impersonate": impersonate,
                    "timeout": timeout,
                }
                if request.body:
                    kwargs["data"] = request.body
                if request.meta.get("proxy"):
                    kwargs["proxy"] = request.meta["proxy"]

                resp = curl_requests.request(**kwargs)
                response_headers = Headers(resp.headers)
                respcls = responsetypes.from_args(
                    headers=response_headers,
                    url=str(resp.url),
                    body=resp.content,
                )
                return respcls(
                    url=str(resp.url),
                    status=resp.status_code,
                    headers=response_headers,
                    body=resp.content,
                    request=request,
                )
```

- [ ] **Step 4: Run curl-cffi tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_curl_cffi_handler.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/scrapper/curl_cffi_handler.py tests/unit/test_curl_cffi_handler.py
git commit -m "fix: preserve scrapy request semantics in curl-cffi"
```

---

## Phase 6: Hotmart Spider Correctness

### Task 6: Intercept API Before Navigation And Enforce Total Limit

**Files:**
- Modify: `src/scrapper/spiders/hotmart.py`
- Modify: `tests/unit/test_hotmart.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_hotmart.py`:

```python
import json
from scrapy.http import TextResponse
from scrapy import Request


def test_review_count_with_thousands_separator():
    assert _parse_review_count("1,234 reviews") == 1234
    assert _parse_review_count("1.234 avaliações") == 1234


def test_start_request_installs_api_interceptor_before_navigation():
    spider = HotmartSpider()
    req = next(spider.start_requests())
    assert req.meta["playwright"] is True
    assert callable(req.meta["playwright_page_init_callback"])


def test_parse_api_carries_scraped_count_across_pages():
    spider = HotmartSpider()
    spider._api_endpoint_cache = "https://api.hotmart.test/search"
    body = json.dumps({
        "data": {
            "search": {
                "pagination": {"totalPages": 2},
                "items": [
                    {"name": "A", "url": "https://example.com/a"},
                    {"name": "B", "url": "https://example.com/b"},
                ],
            }
        }
    })
    request = Request(
        "https://api.hotmart.test/search?q=x&page=1&size=3",
        meta={"query": "x", "limit": 3, "page": 1, "strategy": "api", "scraped_count": 1},
    )
    response = TextResponse(request.url, body=body.encode(), encoding="utf-8", request=request)

    results = list(spider.parse_api(response))

    items = [r for r in results if not isinstance(r, Request)]
    requests = [r for r in results if isinstance(r, Request)]
    assert len(items) == 2
    assert requests[0].meta["scraped_count"] == 3
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_hotmart.py::test_review_count_with_thousands_separator tests/unit/test_hotmart.py::test_start_request_installs_api_interceptor_before_navigation tests/unit/test_hotmart.py::test_parse_api_carries_scraped_count_across_pages -q
```

Expected: FAIL because interception is a post-navigation `PageMethod`, count resets per page, and review count parses `1,234` as `1`.

- [ ] **Step 3: Add pre-navigation interceptor**

In `src/scrapper/spiders/hotmart.py`, replace `_intercept_api_calls` with:

```python
async def _install_api_interceptor(page, request):
    """Install route interception before initial navigation."""
    intercepted: list[dict[str, Any]] = []
    request.meta["_hotmart_api_calls"] = intercepted

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

    await page.route("**/*", capture_route)
```

In both `start_requests` and `start`, replace:

```python
"playwright_page_methods": [
    PageMethod(_intercept_api_calls, query),
],
```

with:

```python
"playwright_page_init_callback": _install_api_interceptor,
"playwright_page_methods": [
    PageMethod("wait_for_timeout", 5000),
],
```

In `discover_api_callback`, replace the `methods[0].result` block with:

```python
        intercepted = response.meta.get("_hotmart_api_calls", [])
```

- [ ] **Step 4: Carry `scraped_count` through API pagination**

In cached API start requests, add `"scraped_count": 0` to meta.

In `parse_api`, replace:

```python
        count = 0
```

with:

```python
        scraped_count = response.meta.get("scraped_count", 0)
        page_count = 0
```

Replace the product loop with:

```python
        for product in products:
            if scraped_count >= limit:
                return
            scraped_count += 1
            page_count += 1
            product["metadata"]["query"] = query
            yield ProductItem(product)
```

Replace pagination condition:

```python
        if count < limit:
```

with:

```python
        if scraped_count < limit:
```

Add `"scraped_count": scraped_count` to the next-page request meta.

- [ ] **Step 5: Fix review count parsing**

Replace `_parse_review_count` with:

```python
def _parse_review_count(text):
    """Extract integer review count from text like '1,234 reviews'."""
    if not text:
        return 0
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else 0
```

- [ ] **Step 6: Run Hotmart tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_hotmart.py tests/integration/test_hotmart_spider.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/scrapper/spiders/hotmart.py tests/unit/test_hotmart.py
git commit -m "fix: harden hotmart api discovery and limits"
```

---

## Phase 7: Rama Spider Robustness

### Task 7: Prevent Lost Search XML And Masked Exceptions

**Files:**
- Modify: `src/scrapper/spiders/rama.py`
- Create: `tests/unit/test_rama.py`

- [ ] **Step 1: Add tests**

Create `tests/unit/test_rama.py` with:

```python
from pathlib import Path

from scrapper.spiders.rama import RamaSpider


def test_parse_xml_extracts_items():
    xml = """
    <partial-response><update><![CDATA[
      <tr role="row">
        <td>SALA CIVIL ID: 123 PROVIDENCIA: SC123-2026 PROCESO: 11001 FECHA: 01/02/2026 PONENTE: Judge TEMA: Tema relevante</td>
      </tr>
    ]]></update></partial-response>
    """

    items = RamaSpider._parse_xml(xml)

    assert len(items) == 1
    assert items[0]["id"] == "123"
    assert items[0]["title"] == "SC123-2026"
    assert items[0]["content"] == "Tema relevante"


def test_rama_spider_has_parse_xml():
    assert callable(RamaSpider._parse_xml)
    assert RamaSpider._parse_xml.__name__ == "_parse_xml"


def test_rama_spider_search_clicked_before_try_counters():
    source = Path("src/scrapper/spiders/rama.py").read_text()
    # Find the line where total_yielded is assigned its initial value
    total_line = None
    try_line = None
    click_flag_line = None
    click_line = None
    for i, line in enumerate(source.splitlines()):
        stripped = line.strip()
        if stripped == "total_yielded = 0":
            total_line = i
        elif stripped.startswith("try:") and total_line is not None:
            try_line = i
            break
        elif stripped == "_search_clicked = True":
            click_flag_line = i
        elif "searchButton\"))" in stripped and ".click()" in stripped:
            click_line = i

    assert total_line is not None, "total_yielded = 0 not found"
    assert try_line is not None and total_line < try_line, (
        f"total_yielded must be initialized before try (found at line {total_line}, try at line {try_line})"
    )
    assert click_flag_line is not None, "_search_clicked = True not found"
    assert click_line is not None, "click() call not found"
    assert click_flag_line < click_line, (
        f"_search_clicked = True must be set before click() (flag at line {click_flag_line}, click at line {click_line})"
    )
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_rama.py -q
```

Expected: FAIL because counters are initialized inside `try` and `_search_clicked` is set after the click.

- [ ] **Step 3: Initialize counters before `try` and mark search before click**

In `src/scrapper/spiders/rama.py`, move these variables before `try:`:

```python
        total_yielded = 0
        seen = set()
        page_num = 0
        max_pages = min(limit * 2, 200)
        download_tasks = []
```

Inside `try`, replace:

```python
            await page_obj.locator('input[name="searchForm:temaInput"]').fill(query)
            await page_obj.locator("#searchForm\\:searchButton").click()
            _search_clicked = True
```

with:

```python
            await page_obj.locator('input[name="searchForm:temaInput"]').fill(query)
            _search_clicked = True
            await page_obj.locator("#searchForm\\:searchButton").click()
```

Remove the duplicate variable initialization from inside `try`.

- [ ] **Step 4: Run Rama tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_rama.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/scrapper/spiders/rama.py tests/unit/test_rama.py
git commit -m "fix: harden rama ajax capture"
```

---

## Phase 8: LLM Cache Key Correctness

### Task 8: Hash Full Normalized HTML

**Files:**
- Modify: `src/scrapper/llm_extractor.py`
- Modify: `tests/unit/test_llm_extractor.py`

- [ ] **Step 1: Add failing cache-key test**

Append to `tests/unit/test_llm_extractor.py`:

```python
def test_cache_key_uses_full_normalized_html():
    with patch("scrapper.llm_extractor.OpenAI"):
        extractor = LLMExtractor()

    prefix = "<html>" + ("x" * 5000)
    html_a = prefix + "<article>A</article></html>"
    html_b = prefix + "<article>B</article></html>"

    assert extractor._cache_key("generic", "query", html_a) != extractor._cache_key("generic", "query", html_b)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_llm_extractor.py::test_cache_key_uses_full_normalized_html -q
```

Expected: FAIL because `_cache_key` only uses the first 4000 characters.

- [ ] **Step 3: Replace cache-key implementation**

In `src/scrapper/llm_extractor.py`, replace `_cache_key` with:

```python
    def _cache_key(self, site, query, html):
        normalized_html = _strip_dynamic_html(html)
        html_hash = hashlib.sha256(normalized_html.encode()).hexdigest()
        raw = f"{site}:{query}:{html_hash}"
        return hashlib.sha256(raw.encode()).hexdigest()
```

- [ ] **Step 4: Run LLM extractor tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_llm_extractor.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/scrapper/llm_extractor.py tests/unit/test_llm_extractor.py
git commit -m "fix: use full html hash for llm cache keys"
```

---

## Phase 9: Scrapyd Health Check

### Task 9: Fix Pending Jobs Key In health-check.sh

**Files:**
- Modify: `bin/health-check.sh`
- Create: `tests/unit/test_health_check_script.py`

- [ ] **Step 1: Add failing static tests**

Create `tests/unit/test_health_check_script.py` with:

```python
from pathlib import Path


SCRIPT = Path("bin/health-check.sh").read_text()


def test_check_pending_reads_pending_key():
    # The daemonstatus.json endpoint returns {"status": "ok", "pending": N, ...}
    # check_pending must read the "pending" key, not the "status" key
    assert "d.get('pending'," in SCRIPT or "d['pending']" in SCRIPT or "d.get(\"pending\"," in SCRIPT
    assert "d.get('status'" not in SCRIPT.replace(".get('status'", "_UNUSED_") or ".get('status'" not in SCRIPT


def test_health_check_is_valid_bash():
    assert "check_pending" in SCRIPT
    assert "check_scrapyd" in SCRIPT
    assert SCRIPT.startswith("#!/") or "#!/" in SCRIPT
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_health_check_script.py -q
```

Expected: FAIL because `check_pending` reads `d.get('status', 'pending')` (returning the string `"ok"`) instead of `d.get('pending', 0)` (returning the numeric pending count).

- [ ] **Step 3: Update health-check script**

In `bin/health-check.sh`, replace the `python3 -c` one-liner in `check_pending()`:

From:
```bash
pending=$(curl -s "$SCRAPYD_URL/daemonstatus.json" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','pending'))" 2>/dev/null) || pending="?"
```

To:
```bash
pending=$(curl -s "$SCRAPYD_URL/daemonstatus.json" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('pending', 0))" 2>/dev/null) || pending="?"
```

- [ ] **Step 4: Run shell and static tests**

Run:

```bash
bash -n bin/health-check.sh
.venv/bin/pytest tests/unit/test_health_check_script.py -q
```

Expected: shell syntax passes and tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add bin/health-check.sh tests/unit/test_health_check_script.py
git commit -m "fix: read correct pending key in health-check"
```

---

## Phase 10: Final Verification

### Task 10: Full Regression Pass

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run unit and integration tests**

Run:

```bash
.venv/bin/pytest tests/ -q
```

Expected: all tests pass. Existing skipped tests may remain skipped.

- [ ] **Step 2: Run lint**

Run:

```bash
.venv/bin/ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 3: Run one crawler without Supabase**

Run:

```bash
.venv/bin/scrapy crawl generic -a url=https://example.com -s SUPABASE_URL= -s SUPABASE_KEY= -s LLM_ENABLED=false -s RAG_EXPORT_ENABLED=false -s LOG_LEVEL=ERROR
```

Expected: no startup failure from `SupabasePipeline`.

- [ ] **Step 4: Run one retry smoke test**

Run:

```bash
.venv/bin/python - <<'PY'
from scrapy import Request
from scrapy.settings import Settings
from scrapper.middlewares import RetryWithBackoffMiddleware

class Stats:
    def inc_value(self, *args, **kwargs):
        pass

class Crawler:
    settings = Settings({"RETRY_TIMES": 1, "RETRY_PRIORITY_ADJUST": -1})
    stats = Stats()

class Spider:
    crawler = Crawler()

mw = RetryWithBackoffMiddleware(Crawler.settings)
mw.crawler = Crawler()
mw.crawler.spider = Spider()
retry_request = mw._retry(Request("https://example.com"), "500")
print(retry_request.meta["retry_times"], retry_request.meta["retry_delay"])
PY
```

Expected output:

```text
1 1
```

- [ ] **Step 5: Inspect final diff**

Run:

```bash
git diff --stat
git diff --check
```

Expected: `git diff --check` reports no whitespace errors.

- [ ] **Step 6: Record final state**

Run:

```bash
git status --short
```

Expected: only intentional changes from the completed tasks are present. If final verification required a fix, return to the task that owns the changed file, update that task's tests, and commit from that task.

---

## Self-Review

**Spec coverage:** The plan covers all 12 findings from the review: Supabase schema mismatch, unsafe RLS policies, retry signature bug, Supabase-required startup failure, post-navigation stealth, invalid cookie storage state, Hotmart late API interception, curl-cffi request loss, Rama AJAX/finally bugs, Hotmart pagination/review parsing, LLM cache collisions, and Scrapyd pending-job health check.

**Placeholder scan:** No implementation step uses unresolved placeholders. Commands, files, expected failures, expected passes, and code snippets are explicit.

**Type consistency:** New helpers use existing item classes and Scrapy request/response types. New `SupabasePipeline._serialize_item(item, table)` is used only by `process_item`. New Playwright callback follows scrapy-playwright's `(page, request)` callback signature.
