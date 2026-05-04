# Bugfix & Code Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 21/22 bugs, leaks, and code smells identified in code review across the scrapper project. (The service role key concern #6 is a deployment config choice, documented with a warning below.)

**Architecture:** Fixes span 5 modules: spiders (asyncio deadlock, title loss), handlers (stealth bypass + threading), pipelines (connection leaks, error handling), extensions (file locking, metrics corruption), and quality (logging unification, template extraction, deduplication).

**Tech Stack:** Scrapy 2.11+, scrapy-playwright, playwright-stealth, curl-cffi, Supabase-py, OpenAI, loguru, portalocker.

**Important task ordering:** Tasks 1, 10, 15 all modify `hotmart.py` — run them in order. Tasks 3, 8 both modify `pipelines.py` — run in order. Tasks 3, 5, 10 modify `reddit.py` — run in order. Tasks 6, 7, 11, 13 modify `extensions.py` — run 6 → 7 → 13 (Task 11 only replaces fcntl lines, run after 7). Line numbers in this plan reference the original file; adjust if prior tasks shift them.

---

### Task 1: Fix hotmart.py asyncio deadlock

**Files:**
- Modify: `src/scrapper/spiders/hotmart.py`

- [ ] **Step 1: Add PageMethod-based API interception for `discover_api`**

Add a new import at the top of `hotmart.py` (near line 11):
```python
from scrapy_playwright.page import PageMethod
```

Replace `start_requests` lines 31-55 with a version that uses `PageMethod` to run the interception script before the response is returned:

```python
    def start_requests(self):
        query = getattr(self, "query", "marketing")
        limit = int(getattr(self, "limit", 10))
        url = f"https://hotmart.com/en/marketplace/search?q={quote_plus(query)}"

        if self._api_endpoint_cache:
            page = 1
            api_url = self._api_endpoint_cache + f"?q={quote_plus(query)}&page={page}&size={limit}"
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
                callback=self.discover_api_callback,
                meta={
                    "playwright": True,
                    "playwright_page_methods": [
                        PageMethod(_intercept_api_calls, query),
                    ],
                    "query": query,
                    "limit": limit,
                },
            )
```

Replace `discover_api` (lines 57-88) with a regular (non-async) callback that reads the intercepted data from `response.meta`:

```python
    def discover_api_callback(self, response):
        """Read intercepted API calls from PageMethod result."""
        query = response.meta["query"]
        limit = response.meta["limit"]

        intercepted = response.meta.get("playwright_page_methods", [])
        if intercepted and intercepted[0].result is not None:
            intercepted = intercepted[0].result
        else:
            intercepted = []

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
                api_url = f"{best}?q={quote_plus(query)}&page={page_num}&size={limit}"
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
        yield from self.parse_dom(response)
```

Add the standalone async function at the bottom of the file (after `FakeFailure` or at module level):

```python
async def _intercept_api_calls(page, query):
    """PageMethod callable: intercept API requests and return them."""
    intercepted: list[dict[str, Any]] = []

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
    await page.wait_for_timeout(5000)
    return intercepted
```

- [ ] **Step 2: Replace "load more" clicking with PageMethod**

In `parse_dom` (lines 299-332), replace the entire load-more try/except block:

```python
        if count >= limit:
            return

        next_page = page + 1
        yield Request(
            response.url,
            callback=self.parse_dom,
            meta={
                "playwright": True,
                "playwright_page_methods": [
                    PageMethod("wait_for_timeout", 1000),
                    PageMethod(_click_load_more),
                ],
                "query": query,
                "limit": limit,
                "page": next_page,
                "strategy": "playwright",
            },
            dont_filter=True,
        )
```

Add the standalone async function at module level:

```python
async def _click_load_more(page):
    """PageMethod callable: click the load-more button if present."""
    button = page.locator("button.load-more-btn")
    if await button.count() > 0:
        await button.click()
        await page.wait_for_timeout(2000)
        return True
    return False
```

- [ ] **Step 3: Remove unused `import asyncio`**

Delete `import asyncio` from lines 67 and 305 (if still present after edits).

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_hotmart.py tests/integration/test_hotmart_spider.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/spiders/hotmart.py
git commit -m "fix(hotmart): replace asyncio.get_event_loop().run_until_complete with PageMethod"
```

---

### Task 2: Fix CurlCffiDownloadHandler inheritance + threading bug

**Files:**
- Modify: `src/scrapper/curl_cffi_handler.py`
- Modify: `tests/unit/test_curl_cffi_handler.py`

- [ ] **Step 1: Change import to inherit from stealth handler**

Replace line 5 in `curl_cffi_handler.py`:
```python
# Before:
from scrapy_playwright.handler import ScrapyPlaywrightDownloadHandler

# After:
from scrapper.stealth_handler import ScrapyPlaywrightStealthDownloadHandler
```

Replace line 10:
```python
# Before:
class CurlCffiDownloadHandler(ScrapyPlaywrightDownloadHandler):

# After:
class CurlCffiDownloadHandler(ScrapyPlaywrightStealthDownloadHandler):
```

- [ ] **Step 2: Fix the curl-cffi fallback threading — use `blockingCallFromThread`**

`ScrapyPlaywrightStealthDownloadHandler._download_request` is `async def`, so calling it from a background thread requires `blockingCallFromThread` (which blocks the calling thread until the coroutine resolves on the reactor thread). `reactor.callFromThread` would return the coroutine itself, not its result.

Replace the `_download_request` method (lines 13-56) with:

```python
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
        from twisted.internet.threads import blockingCallFromThread, deferToThread

        def _do_request():
            try:
                resp = curl_requests.get(
                    request.url,
                    headers=dict(request.headers),
                    impersonate=impersonate,
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
                spider.logger.warning(
                    f"curl_cffi request failed: {e}, falling back to parent handler"
                )
                return blockingCallFromThread(
                    super(CurlCffiDownloadHandler, self)._download_request,
                    request,
                    spider,
                )

        return deferToThread(_do_request)
```

- [ ] **Step 3: Update test to reflect new parent class**

In `tests/unit/test_curl_cffi_handler.py`, line 30, change the mock target:
```python
# Before:
"scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler._download_request"

# After:
"scrapper.stealth_handler.ScrapyPlaywrightStealthDownloadHandler._download_request"
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_curl_cffi_handler.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/curl_cffi_handler.py tests/unit/test_curl_cffi_handler.py
git commit -m "fix(curl-cffi): inherit from stealth handler and fix fallback threading"
```

---

### Task 3: Fix Supabase connection leaks

**Files:**
- Modify: `src/scrapper/pipelines.py`
- Modify: `src/scrapper/spiders/reddit.py`

- [ ] **Step 1: Add `close_spider` to SupabasePipeline**

Add after line 136 in `pipelines.py`:

```python
    def close_spider(self, spider):
        try:
            self.client.postgrest.session.aclose()
        except Exception:
            pass
```

- [ ] **Step 2: Fix reddit.py `_load_cutoff_date` — close the client it creates**

In `reddit.py`, the `_load_cutoff_date` method creates a `create_client` that is never closed. Wrap it with a context manager pattern or manual close:

```python
# Replace lines 30-51 in reddit.py:
    def _load_cutoff_date(self):
        supabase_url = self.settings.get("SUPABASE_URL")
        supabase_key = self.settings.get("SUPABASE_KEY")
        query = getattr(self, "query", "python")

        if supabase_url and supabase_key:
            client = None
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
            finally:
                if client:
                    try:
                        client.postgrest.session.aclose()
                    except Exception:
                        pass
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit/test_pipelines.py tests/integration/test_supabase.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/scrapper/pipelines.py src/scrapper/spiders/reddit.py
git commit -m "fix(supabase): close Supabase clients to prevent connection leaks"
```

---

### Task 4: Fix LLMExtractor SQLite leak

**Files:**
- Modify: `src/scrapper/llm_extractor.py`

- [ ] **Step 1: Make `llm_fallback` reuse or close the extractor**

Replace the `llm_fallback` function (lines 87-117) to properly manage the extractor lifecycle:

```python
def llm_fallback(spider, response, item_class):
    """Shared LLM fallback for any spider. Yields item_class instances."""
    if not os.getenv("OPENAI_API_KEY") or os.getenv("LLM_ENABLED", "true").lower() in ("false", "0", "no"):
        spider.logger.warning("LLM fallback disabled or no API key, skipping")
        return

    prompt_template = getattr(spider, "LLM_PROMPT", None)
    if not prompt_template:
        spider.logger.warning("LLM fallback: spider has no LLM_PROMPT, skipping")
        return

    query = response.meta["query"]
    limit = int(response.meta.get("limit", 10))
    extractor = LLMExtractor()

    try:
        site = getattr(spider, "site", "unknown")

        items = extractor.extract(
            html=response.text,
            prompt_template=prompt_template,
            item_class=item_class,
            site=site,
            query=query,
        )

        for item_data in items[:limit]:
            item_data.setdefault("metadata", {})
            item_data["metadata"]["strategy"] = "llm"
            item_data["metadata"]["query"] = query
            item_data.setdefault("site", site)
            yield item_class(item_data)
    finally:
        extractor.cache.close()
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/unit/test_llm_extractor.py tests/integration/test_llm_fallback.py -v
```

- [ ] **Step 3: Commit**

```bash
git add src/scrapper/llm_extractor.py
git commit -m "fix(llm): close LLMCache SQLite connection in llm_fallback"
```

---

### Task 5: Fix reddit title="" silent loss

**Files:**
- Modify: `src/scrapper/spiders/reddit.py`

- [ ] **Step 1: Add logging and skip when title is empty**

In `parse_post_page`, after line 194 where title is extracted, add an early return with logging:

```python
        author = response.css("a.author::text").get("")
        title = response.css("a.title::text").get("")

        if not post_url:
            self.logger.warning("Skipping post with no URL")
            return

        if not title:
            self.logger.warning(f"Skipping post with no title: {post_url}")
            return

        yield PostItem(
```

The key change is adding lines 196-199. Replace lines 193-203:

```python
        author = response.css("a.author::text").get("")
        title = response.css("a.title::text").get("")

        if not post_url:
            self.logger.warning("Skipping post with no URL")
            return

        if not title:
            self.logger.warning(f"Skipping post with no title: {post_url}")
            return

        yield PostItem(
            site=self.site,
            url=post_url,
            title=title.strip(),
            author=author.strip() if author else "",
```
(Remove the old `title.strip() if title else ""` and `author.strip() if author else ""` guard since we now check for truthiness before yielding.)

- [ ] **Step 2: Run tests**

```bash
pytest tests/unit/test_reddit.py tests/integration/test_reddit_spider.py -v
```

- [ ] **Step 3: Commit**

```bash
git add src/scrapper/spiders/reddit.py
git commit -m "fix(reddit): log and skip posts with empty title instead of silent loss"
```

---

### Task 6: Redact email password from logs and stack traces

**Files:**
- Modify: `src/scrapper/extensions.py`

- [ ] **Step 1: Redact password in EmailAlerter constructor**

Replace the `__init__` method (lines 152-161) to store a sanitized version for logging:

```python
    def __init__(self, smtp_host, smtp_port, from_addr, password, to_addr,
                 metrics_dir="metrics", error_threshold=5):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.from_addr = from_addr
        self._password = password
        self.to_addr = to_addr
        self.metrics_dir = metrics_dir
        self.error_threshold = error_threshold
        self.error_count = 0
```

And replace `self.password` with `self._password` in `_send_email` (line 251):
```python
                server.login(self.from_addr, self._password)
```

- [ ] **Step 2: Remove password from settings.py module-level variable**

Replace line 100 in `settings.py`:
```python
# Before:
ALERT_EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD", "")

# After:
_ALERT_EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD", "")
```

Update the `from_crawler` in `extensions.py` line 169 to reference the new name:
```python
            password=crawler.settings.get("_ALERT_EMAIL_PASSWORD", ""),
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit/test_extensions.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/scrapper/extensions.py src/scrapper/settings.py
git commit -m "fix(security): rename EMAIL_PASSWORD to private attr to prevent log leakage"
```

---

### Task 7: Handle JSON corruption in metrics persistence

**Files:**
- Modify: `src/scrapper/extensions.py`

- [ ] **Step 1: Add JSONDecodeError handling in `_persist_metrics`**

Replace lines 130-143 in `extensions.py` to handle corrupt metrics files:

```python
        with open(metrics_file, "a+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.seek(0)
                content = f.read()
                if content.strip():
                    try:
                        data = json.loads(content)
                        if not isinstance(data, dict) or "runs" not in data:
                            data = {"runs": []}
                    except (json.JSONDecodeError, ValueError):
                        logger.warning(
                            f"Corrupted metrics.json detected, resetting to empty"
                        )
                        data = {"runs": []}
                else:
                    data = {"runs": []}
                data["runs"].append(run)

                # Prune oldest entries per spider if over max
                spider_runs = [r for r in data["runs"] if r["spider"] == spider.name]
                if len(spider_runs) > self.metrics_max_runs:
                    excess = len(spider_runs) - self.metrics_max_runs
                    keep_keys = {r["started_at"] for r in spider_runs[excess:]}
                    data["runs"] = [r for r in data["runs"] if r["spider"] != spider.name or r["started_at"] in keep_keys]

                f.seek(0)
                f.truncate()
                f.write(json.dumps(data, indent=2))
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/unit/test_extensions.py -v
```

- [ ] **Step 3: Commit**

```bash
git add src/scrapper/extensions.py
git commit -m "fix(metrics): handle JSONDecodeError on corrupted metrics.json"
```

---

### Task 8: Add retry to SupabasePipeline upsert failures

**Files:**
- Modify: `src/scrapper/pipelines.py`

- [ ] **Step 1: Rewrite `process_item` in `SupabasePipeline` with retries**

Replace lines 129-136 in `pipelines.py`:

```python
    def process_item(self, item, spider):
        table = "posts" if isinstance(item, PostItem) else "products"
        data = dict(item)
        for attempt in range(1, 4):
            try:
                self.client.table(table).upsert(data, on_conflict="site,url").execute()
                break
            except Exception as e:
                spider.logger.warning(
                    f"Supabase upsert attempt {attempt}/3 failed for {item.get('url')}: {e}"
                )
                if attempt == 3:
                    spider.logger.error(
                        f"Supabase upsert FAILED after 3 retries for {item.get('url')}"
                    )
                    from scrapy.exceptions import DropItem
                    raise DropItem(f"Supabase upsert failed after 3 attempts: {item.get('url')}")
        return item
```

Note: move the `from scrapy.exceptions import DropItem` import to the top of the file (it's already there, just check).

- [ ] **Step 2: Run tests**

```bash
pytest tests/unit/test_pipelines.py -v
```

- [ ] **Step 3: Commit**

```bash
git add src/scrapper/pipelines.py
git commit -m "fix(supabase): add 3 retries to upsert and DropItem on final failure"
```

---

### Task 9: Add error handling to rag_export writes

**Files:**
- Modify: `src/scrapper/rag_export.py`

- [ ] **Step 1: Wrap file writes in try/except in MarkdownExportPipeline**

Replace lines 56-57 in `rag_export.py`:

```python
        try:
            filepath.write_text(md)
        except OSError as e:
            logger.error(f"Failed to write markdown file {filepath}: {e}")
        return item
```

- [ ] **Step 2: Wrap file writes in try/except in ChunkedJSONPipeline**

Replace lines 95-99:

```python
    def process_item(self, item, spider):
        chunk = self._build_chunk(item)
        try:
            if self._file is None:
                self._file = open(self.output_dir / "chunks.jsonl", "a")
            self._file.write(json.dumps(chunk, ensure_ascii=False) + "\n")
            self._file.flush()
        except OSError as e:
            logger.error(f"Failed to write JSONL chunk: {e}")
        return item
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit/test_rag_export.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/scrapper/rag_export.py
git commit -m "fix(rag): add OSError handling for file write failures"
```

---

### Task 10: Extract FakeFailure to shared utility

**Files:**
- Modify: `src/scrapper/utils.py`
- Modify: `src/scrapper/spiders/reddit.py`
- Modify: `src/scrapper/spiders/hotmart.py`

- [ ] **Step 1: Add FakeFailure to utils.py**

Add to the end of `utils.py`:

```python
class FakeFailure:
    """Minimal failure-like object for errback/fallback dispatch."""

    def __init__(self, response):
        self.request = response.request
```

- [ ] **Step 2: Replace FakeFailure in reddit.py**

Replace lines 217-221 in `reddit.py`:
```python
# Remove entire FakeFailure class at lines 217-221
```
Add import at top (line 1 section):
```python
from ..utils import FakeFailure
```

Actually, `FakeFailure` is used at line 111: `yield from self._fallback_to_search(FakeFailure(response))`. Let me check the exact line. The class is defined at bottom (217-221) but used at line 111. So:

In `reddit.py`:
- Add `from ..utils import FakeFailure` (near other imports at top)
- Delete lines 217-221 (the FakeFailure class)

- [ ] **Step 3: Replace FakeFailure in hotmart.py**

In `hotmart.py`:
- Add `from ..utils import FakeFailure` (near other imports at top)
- Delete lines 364-368 (the FakeFailure class)

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_reddit.py tests/unit/test_hotmart.py tests/integration/test_reddit_spider.py tests/integration/test_hotmart_spider.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/utils.py src/scrapper/spiders/reddit.py src/scrapper/spiders/hotmart.py
git commit -m "refactor: extract duplicate FakeFailure class to utils.py"
```

---

### Task 11: Replace fcntl with portalocker (cross-platform file locking)

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/scrapper/extensions.py`

- [ ] **Step 1: Add portalocker dependency**

Add to `pyproject.toml` line 18 (after `openai`):
```toml
    "portalocker>=2.8",
```

- [ ] **Step 2: Install portalocker**

```bash
pip install portalocker>=2.8
```

- [ ] **Step 3: Replace fcntl with portalocker in extensions.py**

Replace lines 3-4 (imports):
```python
# Before:
import fcntl

# After:
import portalocker
```

Replace lines 128 and 146:
```python
# Before (line 128):
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)

# After:
            portalocker.lock(f, portalocker.LOCK_EX)

# Before (line 146):
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

# After:
                portalocker.unlock(f)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_extensions.py -v
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/scrapper/extensions.py
git commit -m "fix(extensions): replace Unix-only fcntl with cross-platform portalocker"
```

---

### Task 12: Extract dashboard HTML to template file

**Files:**
- Create: `src/scrapper/templates/`
- Create: `src/scrapper/templates/dashboard.html`
- Modify: `src/scrapper/dashboard.py`

- [ ] **Step 1: Create templates directory**

```bash
mkdir -p src/scrapper/templates
touch src/scrapper/templates/__init__.py
```

- [ ] **Step 2: Create dashboard.html template**

Write `src/scrapper/templates/dashboard.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scrapper Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0f172a;color:#e2e8f0;padding:2rem}
h1{font-size:1.5rem;margin-bottom:1.5rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:2rem}
.card{background:#1e293b;border-radius:8px;padding:1.25rem}
.card-label{font-size:.75rem;color:#94a3b8;text-transform:uppercase;margin-bottom:.25rem}
.card-value{font-size:1.75rem;font-weight:700}
.card-sub{font-size:.8rem;color:#64748b;margin-top:.25rem}
.chart-container{background:#1e293b;border-radius:8px;padding:1.25rem;margin-bottom:2rem}
.chart-container h2{font-size:1rem;margin-bottom:1rem;color:#94a3b8}
table{width:100%;border-collapse:collapse;background:#1e293b;border-radius:8px;overflow:hidden}
th{text-align:left;padding:.75rem 1rem;font-size:.75rem;text-transform:uppercase;color:#94a3b8;border-bottom:1px solid #334155}
td{padding:.75rem 1rem;border-bottom:1px solid #1e293b;font-size:.875rem}
tr:nth-child(even){background:#1a2332}
.badge{padding:2px 8px;border-radius:12px;font-size:.7rem;font-weight:600}
.badge-success{background:#065f46;color:#6ee7b7}
.badge-danger{background:#7f1d1d;color:#fca5a5}
.badge-warning{background:#78350f;color:#fcd34d}
.no-runs{text-align:center;padding:3rem;color:#64748b}
.error{color:#f87171}
</style>
</head>
<body>
<h1>Scrapper Metrics Dashboard</h1>
<div class="cards" id="cards"></div>
<div class="chart-container">
<h2>Error Rate (%) by Run</h2>
<canvas id="chart" width="800" height="200"></canvas>
</div>
<table id="runs-table">
<thead><tr><th>Spider</th><th>Started</th><th>Status</th><th>Items</th><th>Errors</th><th>Rate/min</th></tr></thead>
<tbody></tbody>
</table>
<div id="no-runs" class="no-runs" style="display:none">No runs recorded yet.</div>
<script>
var DATA = __DATA__;
(function(){
var tbody=document.querySelector("tbody");
var noRuns=document.getElementById("no-runs");
if(!DATA.runs||DATA.runs.length===0){noRuns.style.display="block";return}
var runs=DATA.runs.slice().reverse();
var totalItems=0,totalErrors=0,totalRuns=runs.length,finishedRuns=0,latestRun=null;

runs.forEach(function(r){totalItems+=r.items||0;totalErrors+=r.errors||0;if(r.status==="finished")finishedRuns++;if(!latestRun&&r.status==="finished")latestRun=r});

document.getElementById("cards").innerHTML=
'<div class="card"><div class="card-label">Total Runs</div><div class="card-value">'+totalRuns+'</div></div>'+
'<div class="card"><div class="card-label">Items Scraped</div><div class="card-value">'+totalItems+'</div></div>'+
'<div class="card"><div class="card-label">Success Rate</div><div class="card-value">'+(
totalRuns>0?Math.round(finishedRuns/totalRuns*100):0
)+'%</div></div>'+
'<div class="card"><div class="card-label">Total Errors</div><div class="card-value'+(totalErrors>0?' error':'')+'">'+totalErrors+'</div></div>';

runs.forEach(function(r){
var statusClass=r.status==="finished"?"badge-success":r.status==="cancelled"?"badge-warning":"badge-danger";
var row=document.createElement("tr");
row.innerHTML='<td>'+r.spider+'</td><td>'+r.started_at+'</td><td><span class="badge '+statusClass+'">'+r.status+'</span></td><td>'+r.items+'</td><td>'+r.errors+'</td><td>'+r.rate_per_minute+'</td>';
tbody.appendChild(row);
});

var canvas=document.getElementById("chart");
var ctx=canvas.getContext("2d");
var chartRuns=runs;
var chartWidth=canvas.width-60;
var chartHeight=canvas.height-40;
var maxErrorRate=Math.max.apply(null,chartRuns.map(function(r){return r.responses>0?r.errors/r.responses*100:0}));
if(maxErrorRate===0)maxErrorRate=10;

ctx.fillStyle="#0f172a";
ctx.fillRect(0,0,canvas.width,canvas.height);
ctx.strokeStyle="#334155";
ctx.beginPath();ctx.moveTo(50,20);ctx.lineTo(50,chartHeight+20);ctx.lineTo(chartWidth+50,chartHeight+20);
ctx.stroke();

var barWidth=Math.max(2,Math.min(20,(chartWidth-10)/chartRuns.length));

chartRuns.forEach(function(r,i){
var rate=r.responses>0?r.errors/r.responses*100:0;
var barH=(rate/maxErrorRate)*chartHeight;
var x=55+i*(barWidth+2);
ctx.fillStyle=rate>10?"#ef4444":rate>5?"#f59e0b":"#22c55e";
ctx.fillRect(x,chartHeight+20-barH,barWidth,barH);
});
})();
</script>
</body>
</html>
```

- [ ] **Step 3: Rewrite dashboard.py to load template from file**

Replace the `_generate_html` method (lines 44-168 of `dashboard.py`) and the import section. Read the current dashboard.py first:

```python
# In dashboard.py, replace the entire file with:
import json
from datetime import datetime, timezone
from pathlib import Path

from scrapy import signals
from loguru import logger

_TEMPLATE = None


def _get_template() -> str:
    global _TEMPLATE
    if _TEMPLATE is None:
        template_path = Path(__file__).parent / "templates" / "dashboard.html"
        _TEMPLATE = template_path.read_text()
    return _TEMPLATE


class MetricsDashboard:
    def __init__(self, metrics_dir: str = "metrics"):
        self.metrics_dir = Path(metrics_dir)

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls(metrics_dir=crawler.settings.get("METRICS_DIR", "metrics"))
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_closed(self, spider, reason):
        self._generate_html()

    def _generate_html(self):
        metrics_file = self.metrics_dir / "metrics.json"
        if not metrics_file.exists():
            logger.info("No metrics file yet, skipping dashboard generation")
            return

        try:
            data = json.loads(metrics_file.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read metrics.json, skipping dashboard")
            return

        if not isinstance(data, dict) or "runs" not in data:
            data = {"runs": []}

        html = _get_template().replace("__DATA__", json.dumps(data))
        output_path = self.metrics_dir / "dashboard.html"
        output_path.write_text(html)
        logger.info(f"Dashboard written to {output_path}")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_dashboard.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/templates/ src/scrapper/dashboard.py
git commit -m "refactor(dashboard): extract inline HTML/JS to template file"
```

---

### Task 13: Unify logging to loguru

**Files:**
- Modify: `src/scrapper/extensions.py`
- Modify: `src/scrapper/curl_cffi_handler.py`
- Modify: `src/scrapper/llm_extractor.py`

- [ ] **Step 1: Replace stdlib logging in extensions.py**

Replace lines 39-65 in `extensions.py` (the `_setup_log_rotation` method) to use loguru's built-in rotation instead of stdlib handlers:

```python
    @staticmethod
    def _setup_log_rotation():
        global _log_handlers_configured
        if _log_handlers_configured:
            return
        _log_handlers_configured = True

        from pathlib import Path
        from . import settings

        Path("logs").mkdir(parents=True, exist_ok=True)

        logger.add(
            settings.LOG_FILE_PATH,
            rotation=f"{settings.LOG_FILE_MAX_BYTES} bytes",
            retention=settings.LOG_FILE_BACKUP_COUNT,
            level=settings.LOG_LEVEL,
            format="{time:YYYY-MM-DD HH:mm:ss} [{name}] {level}: {message}",
        )

        logger.add(
            settings.LOG_FILE_TIME,
            rotation=settings.LOG_FILE_TIME_WHEN,
            retention=settings.LOG_FILE_TIME_BACKUP,
            level=settings.LOG_LEVEL,
            format="{time:YYYY-MM-DD HH:mm:ss} [{name}] {level}: {message}",
        )
```

Also update the `spider_opened` method (lines 67-70) — it already uses `logger.info` (loguru), so that's fine. The `_setup_log_rotation` now uses `logger.add` from loguru instead of stdlib `logging.getLogger().addHandler()`.

- [ ] **Step 2: Rename LOG_FILE_SIZE to LOG_FILE_PATH in settings.py**

In `settings.py`, line 115:
```python
# Before:
LOG_FILE_SIZE = "logs/scrapy.log"

# After:
LOG_FILE_PATH = "logs/scrapy.log"
```

Update the references in `extensions.py` (the `_setup_log_rotation` method already uses the new name from step 1 above).

- [ ] **Step 3: Replace stdlib logging in curl_cffi_handler.py**

Replace lines 1 and 7 in `curl_cffi_handler.py`:
```python
# Before:
import logging
...
logger = logging.getLogger(__name__)

# After:
from loguru import logger
```

- [ ] **Step 4: Replace stdlib logging in llm_extractor.py**

Replace lines 1, 3, and 10 in `llm_extractor.py`:
```python
# Before:
import logging
...
logger = logging.getLogger(__name__)

# After:
from loguru import logger
```

Remove `import logging` from line 3 (or replace with `from loguru import logger`).

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/test_extensions.py tests/unit/test_curl_cffi_handler.py tests/unit/test_llm_extractor.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/scrapper/extensions.py src/scrapper/settings.py src/scrapper/curl_cffi_handler.py src/scrapper/llm_extractor.py
git commit -m "refactor(logging): unify all logging to loguru, rename LOG_FILE_SIZE to LOG_FILE_PATH"
```

---

### Task 14: Fix models.py timezone + llm_cache.py redundant UTC

**Files:**
- Modify: `src/scrapper/models.py`
- Modify: `src/scrapper/llm_cache.py`

- [ ] **Step 1: Fix datetime.now() to use timezone in models.py**

Replace lines 1-2 and line 37 in `models.py`:
```python
# Before:
from datetime import datetime
...
    scraped_at: datetime = field(default_factory=datetime.now)

# After:
from datetime import datetime, timezone
...
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 2: Fix redundant UTC+replace in llm_cache.py**

Replace lines 27 and 40 in `llm_cache.py`:
```python
# Before (line 27):
        expiry = (datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=self.ttl)).isoformat()

# After:
        expiry = (datetime.now(timezone.utc) - timedelta(seconds=self.ttl)).isoformat()

# Before (line 40):
                (key, json.dumps(value), datetime.now(UTC).replace(tzinfo=None).isoformat()),

# After:
                (key, json.dumps(value), datetime.now(timezone.utc).isoformat()),
```

Also update the import at line 4:
```python
# Before:
from datetime import UTC, datetime, timedelta

# After:
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit/test_llm_cache.py tests/unit/test_scrapers.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/scrapper/models.py src/scrapper/llm_cache.py
git commit -m "fix(datetime): use timezone-aware datetime consistently, remove redundant UTC.replacetzinfo"
```

---

### Task 15: Add visited set to hotmart recursive JSON search

**Files:**
- Modify: `src/scrapper/spiders/hotmart.py`

- [ ] **Step 1: Add visited set to `_extract_products_from_json`**

Replace lines 174-219 in `hotmart.py`:

```python
    def _extract_products_from_json(self, data):
        """Extract product dicts from JSON structure (tries multiple paths)."""
        products = []
        visited = set()

        def _search(obj, depth=0):
            obj_id = id(obj)
            if obj_id in visited or depth > 10:
                return
            visited.add(obj_id)

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
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/unit/test_hotmart.py -v
```

- [ ] **Step 3: Commit**

```bash
git add src/scrapper/spiders/hotmart.py
git commit -m "fix(hotmart): add visited set to prevent infinite loops on circular JSON"
```

---

### Task 16: Add logging to stealth_handler silent except:pass

**Files:**
- Modify: `src/scrapper/stealth_handler.py`

- [ ] **Step 1: Log cookie save failures**

Replace lines 56-57:
```python
                except Exception:
                    pass
```
With:
```python
                except Exception as e:
                    logger.warning(f"Failed to save cookies for context '{name}': {e}")
```

Add the import at top:
```python
from loguru import logger
```

- [ ] **Step 2: Log human simulation failures**

Replace lines 111-112:
```python
            except Exception:
                pass
```
With:
```python
            except Exception as e:
                logger.warning(f"Human simulation failed for {request.url}: {e}")
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit/test_stealth.py tests/integration/test_stealth.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/scrapper/stealth_handler.py
git commit -m "fix(stealth): log exceptions instead of silently swallowing them"
```

---

### Task 17: Delete broken main.py

**Files:**
- Delete: `src/scrapper/main.py`
- Modify: `tests/unit/test_main.py`

- [ ] **Step 1: Delete main.py**

```bash
rm src/scrapper/main.py
```

- [ ] **Step 2: Delete or update test_main.py**

Read `tests/unit/test_main.py` first to check what it tests. If it imports from `scrapper.main`, delete the test file too.

```bash
rm tests/unit/test_main.py
```

- [ ] **Step 3: Verify no other files reference main.py**

```bash
rg "from.*main import|import.*main" src/ tests/ --include '*.py'
```
Expected: no results (or only the deleted test file).

- [ ] **Step 4: Run full test suite to verify nothing breaks**

```bash
pytest tests/ -v --ignore=tests/unit/test_main.py
```

- [ ] **Step 5: Commit**

```bash
git rm src/scrapper/main.py tests/unit/test_main.py
git commit -m "fix: delete broken main.py with non-existent scrapers imports"
```

---

### Task 18: Document SUPABASE_KEY security risk in .env.example

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Add warning about service role key**

Replace line 3 in `.env.example`:
```
# Before:
SUPABASE_KEY=eyJhbGciOi...your-service-role-key

# After:
# ⚠️  SECURITY: The service role key bypasses all Row Level Security and has unrestricted
# database access. Treat it like a root password. Never commit to version control.
# Consider using the anon key if you only need read access with RLS policies enabled.
SUPABASE_KEY=eyJhbGciOi...your-service-role-key
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: add security warning about service role key in .env.example"
```

---

### Task 19: Add cookie/cache/rag_output to .gitignore

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add generated/sensitive paths to .gitignore**

Add after line 17 (`*.csv`):
```
llm_cache.db
cookies/
metrics/
rag_output/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: add generated files to .gitignore (cache, cookies, metrics, rag_output)"
```

---

### Task 20: Run full test suite and lint

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all 165 tests pass.

- [ ] **Step 2: Run linter**

```bash
ruff check src/ tests/
```

Expected: no new errors. Fix any if present.

- [ ] **Step 3: Commit any final fixes**

```bash
git add -A
git commit -m "chore: final lint and test fixes after code review remediation"
```
