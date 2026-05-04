# Generic Spider: Pagination + New Page Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pagination support (traditional links + load more/infinite scroll) and 5 new page types (job, event, recipe, documentation, profile) to the generic spider.

**Architecture:** New `pagination.py` module with CSS→LLM→Playwright cascade. GenericItem gets `image_url` + `category` fields. Prompt extended for 10 page types and pagination detection. Spider gains pagination loop with `_items_yielded` tracking and Playwright load-more click/scroll integration.

**Tech Stack:** Scrapy, scrapy-playwright, curl-cffi, OpenAI (LLM), pytest

---

### Task 1: Add `image_url` and `category` fields to GenericItem

**Files:**
- Modify: `src/scrapper/items.py:62-96`

- [ ] **Step 1: Write tests for new fields**

```python
# Add to tests/unit/test_items.py

def test_generic_item_new_fields():
    item = GenericItem(
        site="example.com",
        url="https://example.com/job/1",
        title="Senior Engineer",
        image_url="https://example.com/img/photo.jpg",
        category="Engineering",
    )
    assert item["image_url"] == "https://example.com/img/photo.jpg"
    assert item["category"] == "Engineering"


def test_generic_item_new_fields_default_to_none():
    item = GenericItem(site="example.com", url="http://x.com", title="X")
    assert item.get("image_url") is None
    assert item.get("category") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_items.py::test_generic_item_new_fields tests/unit/test_items.py::test_generic_item_new_fields_default_to_none -v`
Expected: KeyError on `image_url` and `category`

- [ ] **Step 3: Add the fields to GenericItem**

```python
# In src/scrapper/items.py, inside GenericItem class, add after the `author` field line:
    image_url = scrapy.Field()
    category = scrapy.Field()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_items.py::test_generic_item_new_fields tests/unit/test_items.py::test_generic_item_new_fields_default_to_none -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/unit/ -v`
Expected: All 40+ tests pass (only new fields added, nothing broken)

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_items.py src/scrapper/items.py
git commit -m "feat(generic): add image_url and category fields to GenericItem"
```

---

### Task 2: Create `PaginationDetector` module

**Files:**
- Create: `src/scrapper/pagination.py`
- Create: `tests/unit/test_generic_pagination.py`

- [ ] **Step 1: Write tests for PaginationDetector**

```python
# tests/unit/test_generic_pagination.py

from scrapper.pagination import PaginationDetector


class TestFindNextUrl:
    def test_rel_next_in_link_head(self):
        html = '<html><head><link rel="next" href="https://example.com/?page=2"></head><body></body></html>'
        url = PaginationDetector.find_next_url(html, "https://example.com/")
        assert url == "https://example.com/?page=2"

    def test_a_rel_next_in_body(self):
        html = '<html><body><a rel="next" href="/page/2">Next</a></body></html>'
        url = PaginationDetector.find_next_url(html, "https://example.com/")
        assert url == "https://example.com/page/2"

    def test_pagination_next_class(self):
        html = '<div class="pagination"><a class="next" href="?page=3">Next</a></div>'
        url = PaginationDetector.find_next_url(html, "https://example.com/search")
        assert url == "https://example.com/search?page=3"

    def test_aria_label_next(self):
        html = '<a aria-label="Next" href="/products?offset=20">Next</a>'
        url = PaginationDetector.find_next_url(html, "https://shop.example.com/products")
        assert url == "https://shop.example.com/products?offset=20"

    def test_url_pattern_page_number(self):
        html = '<html><body><a href="?p=2">Page 2</a></body></html>'
        url = PaginationDetector.find_next_url(html, "https://example.com/")
        assert url == "https://example.com/?p=2"

    def test_url_pattern_page_keyword(self):
        html = '<html><body><a href="/blog/page/2/">Next</a></body></html>'
        url = PaginationDetector.find_next_url(html, "https://example.com/blog/")
        assert url == "https://example.com/blog/page/2/"

    def test_no_pagination_returns_none(self):
        html = '<html><body><p>No pagination here</p></body></html>'
        url = PaginationDetector.find_next_url(html, "https://example.com/")
        assert url is None

    def test_relative_url_resolved(self):
        html = '<a rel="next" href="../page/2">Next</a>'
        url = PaginationDetector.find_next_url(html, "https://example.com/catalog/1")
        assert url == "https://example.com/catalog/../page/2"

    def test_empty_html_returns_none(self):
        assert PaginationDetector.find_next_url("", "https://example.com/") is None

    def test_duplicate_next_links_uses_first(self):
        html = (
            '<a rel="next" href="/page/2">Next</a>'
            '<a rel="next" href="/page/3">Also Next</a>'
        )
        url = PaginationDetector.find_next_url(html, "https://example.com/")
        assert url == "https://example.com/page/2"


class TestDetectLoadMore:
    def test_load_more_button_detected(self):
        html = '<button>Load more</button>'
        assert PaginationDetector.detect_pagination_type(html) == "load_more"

    def test_show_more_button_detected(self):
        html = '<button>Show more results</button>'
        assert PaginationDetector.detect_pagination_type(html) == "load_more"

    def test_load_more_class_detected(self):
        html = '<div class="load-more">Click</div>'
        assert PaginationDetector.detect_pagination_type(html) == "load_more"

    def test_infinite_scroll_detected(self):
        html = '<div class="infinite-scroll"></div>'
        assert PaginationDetector.detect_pagination_type(html) == "scroll"

    def test_no_load_more_returns_link_when_next_present(self):
        html = '<a rel="next" href="/page/2">Next</a>'
        result = PaginationDetector.detect_pagination_type(html)
        assert result == "link"

    def test_no_pagination_returns_none(self):
        html = '<html><body><p>Hello</p></body></html>'
        assert PaginationDetector.detect_pagination_type(html) is None

    def test_load_more_overrides_link(self):
        html = '<a rel="next" href="/page/2">Next</a><button class="load-more">Load more</button>'
        assert PaginationDetector.detect_pagination_type(html) == "load_more"

    def test_scroll_overrides_link(self):
        html = '<a rel="next" href="/page/2">Next</a><div class="infinite-scroll"></div>'
        assert PaginationDetector.detect_pagination_type(html) == "scroll"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_generic_pagination.py -v`
Expected: ImportError (module doesn't exist)

- [ ] **Step 3: Write PaginationDetector implementation**

```python
# src/scrapper/pagination.py

from urllib.parse import urljoin

from scrapy import Selector


class PaginationDetector:
    """Detect next page URLs and pagination type from HTML."""

    NEXT_LINK_SELECTORS = [
        'link[rel="next"]::attr(href)',
        'a[rel="next"]::attr(href)',
        '.pagination .next::attr(href)',
        '.pagination a.next::attr(href)',
        'a.pagination-next::attr(href)',
        'a[aria-label="Next"]::attr(href)',
        'a[aria-label="Next page"]::attr(href)',
        'a.next::attr(href)',
        '.pager .next a::attr(href)',
        '.pager .next::attr(href)',
    ]

    LOAD_MORE_SELECTORS = [
        'button:has-text("Load more")',
        'button:has-text("Show more")',
        'a:has-text("Load more")',
        'a:has-text("Show more")',
        '.load-more',
        '.show-more',
        '.load-more-btn',
        '.show-more-btn',
        '[data-action="load-more"]',
    ]

    SCROLL_SELECTORS = [
        '.infinite-scroll',
        '.infinite-scroll-wrapper',
        '[data-infinite-scroll]',
        '.infinite-scroll-container',
    ]

    URL_PAGE_PATTERNS = [
        'a[href*="?page="]',
        'a[href*="&page="]',
        'a[href*="?p="]',
        'a[href*="&p="]',
        'a[href*="/page/"]',
        'a[href*="?offset="]',
        'a[href*="&offset="]',
    ]

    @classmethod
    def find_next_url(cls, html: str, base_url: str) -> str | None:
        if not html.strip():
            return None

        sel = Selector(text=html)

        for css_sel in cls.NEXT_LINK_SELECTORS:
            hrefs = sel.css(css_sel).getall()
            for href in hrefs:
                if href and href.strip() and href.strip() != "#":
                    return urljoin(base_url, href.strip())

        for css_sel in cls.URL_PAGE_PATTERNS:
            links = sel.css(css_sel)
            for link in links:
                href = link.css("::attr(href)").get("")
                text = "".join(link.css("::text").getall()).lower().strip()
                if href and any(w in text for w in ("next", "siguiente", "»", ">", ">")):
                    return urljoin(base_url, href)

        return None

    @classmethod
    def detect_pagination_type(cls, html: str) -> str | None:
        if not html.strip():
            return None

        sel = Selector(text=html)

        for selector in cls.LOAD_MORE_SELECTORS:
            if sel.css(selector).get() is not None:
                return "load_more"

        for selector in cls.SCROLL_SELECTORS:
            if sel.css(selector).get() is not None:
                return "scroll"

        for css_sel in cls.NEXT_LINK_SELECTORS:
            if sel.css(css_sel).get():
                return "link"

        for css_sel in cls.URL_PAGE_PATTERNS:
            links = sel.css(css_sel)
            for link in links:
                text = "".join(link.css("::text").getall()).lower().strip()
                if text and text.isdigit():
                    return "link"

        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_generic_pagination.py -v`
Expected: All 16 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/pagination.py tests/unit/test_generic_pagination.py
git commit -m "feat: add PaginationDetector module (CSS → link/load_more/scroll)"
```

---

### Task 3: Extend LLM prompt with 5 new page types + pagination detection

**Files:**
- Modify: `src/scrapper/prompts/generic.py`
- Extend: `tests/unit/test_generic_prompt.py`

- [ ] **Step 1: Write tests for new type hints and pagination instructions**

```python
# Add to tests/unit/test_generic_prompt.py

def test_new_type_hints_present():
    for page_type in ("job", "event", "recipe", "documentation", "profile"):
        assert page_type in TYPE_HINTS
        assert len(TYPE_HINTS[page_type]) > 0


def test_type_hints_total_count():
    assert len(TYPE_HINTS) == 10


def test_pagination_field_in_prompt():
    assert "pagination" in GENERIC_PROMPT
    assert "next_url" in GENERIC_PROMPT


def test_generic_prompt_mentions_new_types():
    for type_name in ("job", "event", "recipe", "documentation", "profile"):
        assert type_name in GENERIC_PROMPT.lower()


def test_prompt_replace_works_with_new_prompt():
    result = GENERIC_PROMPT.replace("{html}", "TEST_HTML")
    assert "TEST_HTML" in result
    assert '"pagination"' in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_generic_prompt.py::test_new_type_hints_present tests/unit/test_generic_prompt.py::test_type_hints_total_count tests/unit/test_generic_prompt.py::test_pagination_field_in_prompt tests/unit/test_generic_prompt.py::test_generic_prompt_mentions_new_types tests/unit/test_generic_prompt.py::test_prompt_replace_works_with_new_prompt -v`
Expected: AssertionError (TYPE_HINTS missing new keys, GENERIC_PROMPT missing pagination)

- [ ] **Step 3: Add the 5 new type hints to TYPE_HINTS**

```python
# In src/scrapper/prompts/generic.py, after the existing TYPE_HINTS dict close brace:
TYPE_HINTS = {
    "product": "IMPORTANT: This is a product/e-commerce page. Focus on price, rating, review_count, and seller information.",
    "article": "IMPORTANT: This is an article or blog post. Focus on author, published_at date, and the full content text.",
    "forum": "IMPORTANT: This is a discussion thread or forum. Focus on each post's author, score (upvotes), and content.",
    "listing": "IMPORTANT: This is a listing/search results page. Extract ALL items listed on the page, not just the first one.",
    "other": "IMPORTANT: This is a general-purpose page. Extract the main content, title, and any available metadata.",
    "job": "IMPORTANT: This is a job listing. Extract job title, company name as author, salary as price (number, no currency symbol), location, employment_type in metadata. Use category for job category (Engineering, Marketing, etc.).",
    "event": "IMPORTANT: This is an event page. Extract event name as title, date in metadata, location, organizer as author, price as number, venue in metadata. Use category for event type (Conference, Workshop, etc.).",
    "recipe": "IMPORTANT: This is a recipe page. Extract recipe name as title, ingredients as a list in metadata.ingredients, cook_time and prep_time as numbers (minutes) in metadata, servings, cuisine in category. Put full instructions in content.",
    "documentation": "IMPORTANT: This is a documentation or wiki page. Extract page title, full content body, section hierarchy in metadata.section, version/framework info in metadata. Use category for the product/framework name.",
    "profile": "IMPORTANT: This is a profile page. Extract person/org name as title, bio as content, location, website, followers (as integer) in metadata, skills as list in metadata. Use image_url for profile photo. Use category for profile type.",
}
```

- [ ] **Step 4: Extend GENERIC_PROMPT with new types and pagination detection**

Replace the existing `GENERIC_PROMPT` in `src/scrapper/prompts/generic.py` with:

```python
GENERIC_PROMPT = """\
You are a web scraping assistant. Analyze the HTML below and determine what type of page it is, then extract structured data.

## Page type classification

- "product": e-commerce product page (has price, rating, reviews, seller)
- "article": blog post, news article, essay (has author, date, full text body)
- "forum": discussion thread, Q&A, comments (has author, score, replies)
- "listing": search results, category page, directory (list of items)
- "job": job listing or job search results (has company, salary, location)
- "event": event page, conference, meetup (has date, venue, organizer)
- "recipe": cooking recipe (has ingredients, cook time, instructions)
- "documentation": docs, wiki, API reference (has sections, code examples)
- "profile": person or organization profile (has bio, photo, links)
- "other": doesn't match above

## Pagination detection

Examine the HTML for pagination controls and report them:
- Look for "next page" links, page number links, load more buttons, or infinite scroll indicators
- If a next page URL is found, include it in pagination.next_url
- If load more / show more buttons exist, set pagination.type to "load_more"
- If infinite scroll is detected, set pagination.type to "scroll"
- If no pagination is found, omit the pagination key entirely

## Extraction rules

1. For each item found, include all fields listed below. Use null for missing values.
2. For "listing", "forum", "job", "event", or "recipe" pages, extract ALL items visible in the HTML, not just the first one.
3. For "product" or "event" pages, extract price as a number (no currency symbol), rating as 0-5 float.
4. For "article", "documentation", or "profile" pages, extract the full content text into the content field.
5. For "forum" pages, extract score as upvotes/likes count as an integer.
6. For "recipe" pages, put ingredients as a list of strings in metadata.ingredients.
7. Strip HTML tags from text fields. Keep URLs absolute (prepend domain if relative).
8. Ignore navigation menus, ads, sidebar widgets, cookie banners, and footer links.
9. If a field is not found, use "" for strings, 0 for integers, null for floats and dates.

## Output format

Return valid JSON only:
{"page_type": "<type>", "pagination": {"next_url": "<absolute_url_or_null>", "type": "link"|"load_more"|"scroll"}, "items": [{"url": "...", "title": "...", "content": null, "price": null, "currency": "USD", "rating": null, "review_count": null, "score": null, "author": null, "published_at": null, "image_url": null, "category": null, "metadata": {}}]}

The pagination key is optional — omit it if no pagination exists on the page.

## HTML to analyze

{html}

Return JSON:"""
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_generic_prompt.py -v`
Expected: All 10 tests PASS (5 existing + 5 new)

- [ ] **Step 6: Run full unit test suite**

Run: `pytest tests/unit/ -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add src/scrapper/prompts/generic.py tests/unit/test_generic_prompt.py
git commit -m "feat(generic): add 5 page types + pagination detection to LLM prompt"
```

---

### Task 4: Add pagination loop and Playwright load-more to GenericSpider

**Files:**
- Modify: `src/scrapper/spiders/generic.py`
- Extend: `tests/unit/test_generic_spider.py`

- [ ] **Step 1: Write tests for pagination behavior**

```python
# Add to tests/unit/test_generic_spider.py

from scrapper.pagination import PaginationDetector


def test_start_requests_includes_limit_in_meta():
    spider = GenericSpider()
    spider.url = "https://example.com/search"
    spider.limit = "30"

    requests = list(spider.start_requests())
    assert requests[0].meta["limit"] == 30


def test_start_requests_default_limit():
    spider = GenericSpider()
    spider.url = "https://example.com/search"
    # spider.limit not set

    requests = list(spider.start_requests())
    assert requests[0].meta["limit"] == 10


def test_parse_follows_pagination_link():
    html = '<html><body><h1>Results</h1><a rel="next" href="/page/2">Next</a></body></html>'
    request = Request("https://example.com/search")
    response = HtmlResponse(url=request.url, body=html.encode(), request=request)
    response.meta["site"] = "example.com"
    response.meta["task_url"] = request.url
    response.meta["limit"] = 20

    llm_data = {"page_type": "listing", "items": [
        {"title": "Result 1", "url": "https://example.com/1"},
        {"title": "Result 2", "url": "https://example.com/2"},
    ]}

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
            mock_client = mock_openai.return_value

            class FakeChoice:
                def __init__(self, content):
                    self.message = MagicMock()
                    self.message.content = content

            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[FakeChoice(json.dumps(llm_data))],
                usage=MagicMock(),
            )

            spider = GenericSpider()
            results = list(spider.parse(response))

    # 2 items + 1 pagination request = 3 yield results
    items = [r for r in results if not isinstance(r, Request)]
    requests = [r for r in results if isinstance(r, Request)]

    assert len(items) == 2
    assert len(requests) == 1
    assert requests[0].url == "https://example.com/page/2"
    assert requests[0].meta["limit"] == 18  # 20 original - 2 extracted = 18 remaining
    assert requests[0].meta["_page_depth"] == 1


def test_parse_stops_at_limit():
    html = '<html><body><h1>Results</h1><a rel="next" href="/page/2">Next</a></body></html>'
    request = Request("https://example.com/search")
    response = HtmlResponse(url=request.url, body=html.encode(), request=request)
    response.meta["site"] = "example.com"
    response.meta["task_url"] = request.url
    response.meta["limit"] = 1

    llm_data = {"page_type": "listing", "items": [
        {"title": "Result 1", "url": "https://example.com/1"},
        {"title": "Result 2", "url": "https://example.com/2"},
    ]}

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
            mock_client = mock_openai.return_value

            class FakeChoice:
                def __init__(self, content):
                    self.message = MagicMock()
                    self.message.content = content

            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[FakeChoice(json.dumps(llm_data))],
                usage=MagicMock(),
            )

            spider = GenericSpider()
            results = list(spider.parse(response))

    items = [r for r in results if not isinstance(r, Request)]
    requests = [r for r in results if isinstance(r, Request)]

    # limit=1 → only 1 item yielded, no pagination request
    assert len(items) == 1
    assert len(requests) == 0


def test_parse_playwright_for_load_more():
    html = '<html><body><h1>Results</h1><button class="load-more">Load more</button></body></html>'
    request = Request("https://example.com/search")
    response = HtmlResponse(url=request.url, body=html.encode(), request=request)
    response.meta["site"] = "example.com"
    response.meta["task_url"] = request.url
    response.meta["limit"] = 10

    llm_data = {"page_type": "listing", "items": [
        {"title": "Result 1", "url": "https://example.com/1"},
    ]}

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
            mock_client = mock_openai.return_value

            class FakeChoice:
                def __init__(self, content):
                    self.message = MagicMock()
                    self.message.content = content

            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[FakeChoice(json.dumps(llm_data))],
                usage=MagicMock(),
            )

            spider = GenericSpider()
            results = list(spider.parse(response))

    items = [r for r in results if not isinstance(r, Request)]
    requests = [r for r in results if isinstance(r, Request)]

    assert len(items) == 1
    assert len(requests) == 1
    pw_req = requests[0]
    assert pw_req.meta["playwright"] is True
    assert pw_req.meta["_pagination_type"] == "load_more"
    assert pw_req.meta["limit"] == 9  # 10 original - 1 extracted = 9 remaining
    assert "playwright_page_methods" in pw_req.meta


def test_parse_max_pages_depth():
    html = '<html><body><h1>Page 5</h1><a rel="next" href="/page/6">Next</a></body></html>'
    request = Request("https://example.com/search")
    response = HtmlResponse(url=request.url, body=html.encode(), request=request)
    response.meta["site"] = "example.com"
    response.meta["task_url"] = request.url
    response.meta["limit"] = 100
    response.meta["max_pages"] = 5
    response.meta["_page_depth"] = 4  # max_pages - 1

    llm_data = {"page_type": "listing", "items": [
        {"title": "Result", "url": "https://example.com/1"},
    ]}

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
            mock_client = mock_openai.return_value

            class FakeChoice:
                def __init__(self, content):
                    self.message = MagicMock()
                    self.message.content = content

            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[FakeChoice(json.dumps(llm_data))],
                usage=MagicMock(),
            )

            spider = GenericSpider()
            results = list(spider.parse(response))

    requests = [r for r in results if isinstance(r, Request)]
    assert len(requests) == 0  # max depth reached


def test_parse_stops_at_default_max_pages():
    html = '<html><body><h1>Page 11</h1><a rel="next" href="/page/12">Next</a></body></html>'
    request = Request("https://example.com/search")
    response = HtmlResponse(url=request.url, body=html.encode(), request=request)
    response.meta["site"] = "example.com"
    response.meta["task_url"] = request.url
    response.meta["limit"] = 100
    response.meta["max_pages"] = 10
    response.meta["_page_depth"] = 9  # max_pages - 1

    llm_data = {"page_type": "listing", "items": [
        {"title": "Result", "url": "https://example.com/1"},
    ]}

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
            mock_client = mock_openai.return_value

            class FakeChoice:
                def __init__(self, content):
                    self.message = MagicMock()
                    self.message.content = content

            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[FakeChoice(json.dumps(llm_data))],
                usage=MagicMock(),
            )

            spider = GenericSpider()
            results = list(spider.parse(response))

    requests = [r for r in results if isinstance(r, Request)]
    assert len(requests) == 0  # max depth reached
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_generic_spider.py::test_start_requests_includes_limit_in_meta tests/unit/test_generic_spider.py::test_start_requests_default_limit tests/unit/test_generic_spider.py::test_parse_follows_pagination_link tests/unit/test_generic_spider.py::test_parse_stops_at_limit tests/unit/test_generic_spider.py::test_parse_playwright_for_load_more tests/unit/test_generic_spider.py::test_parse_max_pages_depth tests/unit/test_generic_spider.py::test_parse_stops_at_default_max_pages -v`
Expected: AssertionError (limit not in meta, no pagination requests yielded)

- [ ] **Step 3: Rewrite GenericSpider with pagination support**

```python
# src/scrapper/spiders/generic.py

from urllib.parse import urlparse

import scrapy
from scrapy import Request
from scrapy_playwright.page import PageMethod

from ..items import GenericItem
from ..prompts.generic import GENERIC_PROMPT, TYPE_HINTS
from ..llm_extractor import llm_fallback
from ..pagination import PaginationDetector


async def _click_load_more_sp(page):
    """Playwright PageMethod: click load-more buttons repeatedly (max 10)."""
    selectors = [
        "button:has-text('Load more')",
        "button:has-text('Show more')",
        "a:has-text('Load more')",
        "a:has-text('Show more')",
        ".load-more",
        ".show-more",
        ".load-more-btn",
    ]
    for _ in range(10):
        found = False
        for sel in selectors:
            btn = page.locator(sel).first
            if await btn.count() > 0:
                try:
                    await btn.click()
                    await page.wait_for_timeout(1500)
                    found = True
                    break
                except Exception:
                    pass
        if not found:
            break
    return True


async def _scroll_infinite_sp(page):
    """Playwright PageMethod: scroll down until height stops growing (max 10)."""
    last_height = await page.evaluate("document.body.scrollHeight")
    stable_count = 0
    for _ in range(10):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1500)
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == last_height:
            stable_count += 1
            if stable_count >= 3:
                break
        else:
            stable_count = 0
        last_height = new_height
    return True


class GenericSpider(scrapy.Spider):
    name = "generic"
    site = "generic"
    LLM_PROMPT = GENERIC_PROMPT
    MAX_PAGES = 10

    custom_settings = {
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 3,
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
    }

    def start_requests(self):
        task_url = getattr(self, "url", None)
        task_type = getattr(self, "type", None)
        limit = int(getattr(self, "limit", "10"))
        max_pages = int(getattr(self, "max_pages", str(self.MAX_PAGES)))

        if not task_url:
            self.logger.error("No URL provided. Use: -a url=https://... [-a type=product|article|forum|listing|job|event|recipe|documentation|profile] [-a limit=20] [-a max_pages=5]")
            return

        domain = urlparse(task_url).netloc
        yield scrapy.Request(
            url=task_url,
            callback=self.parse,
            errback=self._handle_error,
            meta={
                "task_type": task_type or None,
                "site": domain,
                "task_url": task_url,
                "limit": limit,
                "max_pages": max_pages,
                "_page_depth": 0,
            },
        )

    def parse(self, response):
        task_type = response.meta.get("task_type")
        limit = response.meta.get("limit", 10)
        max_pages = response.meta.get("max_pages", self.MAX_PAGES)

        if task_type and task_type in TYPE_HINTS:
            self.LLM_PROMPT = TYPE_HINTS[task_type] + "\n\n" + GENERIC_PROMPT
        else:
            self.LLM_PROMPT = GENERIC_PROMPT

        count = 0
        for item in llm_fallback(self, response, GenericItem):
            item["site"] = response.meta["site"]
            count += 1
            yield item

        if count == 0:
            if not response.meta.get("_playwright_retry"):
                self.logger.info("No items via curl-cffi, retrying with Playwright for %s", response.url)
                yield self._playwright_request(response)
                return
            else:
                self.logger.warning("No items extracted from %s (Playwright also failed)", response.url)
                return

        remaining = limit - count
        if remaining <= 0:
            return

        page_depth = response.meta.get("_page_depth", 0)
        if page_depth >= max_pages - 1:
            self.logger.info("Max pages (%d) reached for %s", max_pages, response.url)
            return

        pagination_type = PaginationDetector.detect_pagination_type(response.text)
        if pagination_type is None:
            self.logger.info("No pagination detected on %s, stopping", response.url)
            return

        if pagination_type == "link":
            next_url = PaginationDetector.find_next_url(response.text, response.url)
            if not next_url:
                self.logger.info("No next_url found despite pagination 'link' type on %s", response.url)
                return
            self.logger.info("Following pagination link: %s", next_url)
            yield self._next_page_request(response, next_url, page_depth, remaining, max_pages)

        elif pagination_type in ("load_more", "scroll"):
            page_method = _click_load_more_sp if pagination_type == "load_more" else _scroll_infinite_sp
            self.logger.info("Detected %s on %s, switching to Playwright", pagination_type, response.url)
            yield self._playwright_paginated_request(response, page_method, page_depth, remaining, max_pages)

    def _next_page_request(self, response, next_url, page_depth, limit, max_pages):
        meta = response.meta.copy()
        meta["_page_depth"] = page_depth + 1
        meta["limit"] = limit
        meta["max_pages"] = max_pages
        return Request(
            url=next_url,
            callback=self.parse,
            errback=self._handle_error,
            meta=meta,
        )

    def _playwright_paginated_request(self, response, page_method, page_depth, limit, max_pages):
        meta = response.meta.copy()
        meta["playwright"] = True
        meta["playwright_page_methods"] = [
            PageMethod("wait_for_timeout", 1000),
            PageMethod(page_method),
        ]
        meta["_page_depth"] = page_depth + 1
        meta["_pagination_type"] = "load_more"
        meta["limit"] = limit
        meta["max_pages"] = max_pages
        return Request(
            url=response.url,
            callback=self.parse,
            errback=self._handle_error,
            meta=meta,
            dont_filter=True,
        )

    def _playwright_request(self, response):
        meta = response.meta.copy()
        meta["_playwright_retry"] = True
        meta["playwright"] = True
        return Request(
            url=response.url,
            callback=self.parse,
            errback=self._handle_error,
            meta=meta,
            dont_filter=True,
        )

    def _handle_error(self, failure):
        self.logger.error("Request failed for %s: %s", failure.request.url, failure.value)
```

- [ ] **Step 4: Run all generic spider tests to verify they pass**

Run: `pytest tests/unit/test_generic_spider.py -v`
Expected: All 14 tests PASS (7 existing + 7 new)

- [ ] **Step 5: Run full unit test suite**

Run: `pytest tests/unit/ -v`
Expected: All tests pass (70+ tests)

- [ ] **Step 6: Commit**

```bash
git add src/scrapper/spiders/generic.py tests/unit/test_generic_spider.py
git commit -m "feat(generic): add pagination loop with Playwright load-more/scroll support"
```

---

### Task 5: Update AGENTS.md with new features

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Update the generic spider status table and command examples**

```markdown
# Current generic spider entry in the status table:
| Generic | ✅ Works | curl-cffi → Playwright → LLM | Universal spider with type-hinted prompts (listing, article, product, forum) |

# Replace with:
| Generic | ✅ Works | curl-cffi → Playwright → LLM + pagination | 10 page types + pagination (links/load-more/scroll), type-hinted prompts |
```

- [ ] **Step 2: Update the run command to show new parameters**

```bash
# Current line:
scrapy crawl generic -a url="https://books.toscrape.com" -a type="listing" -s ROBOTSTXT_OBEY=False -o results.json

# Replace with:
scrapy crawl generic -a url="https://books.toscrape.com" -a type="listing" -a limit=30 -s ROBOTSTXT_OBEY=False -o results.json
```

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs: update AGENTS.md with generic spider pagination and new page types"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass (195+ tests)

- [ ] **Step 2: Run lint**

Run: `ruff check src/ tests/`
Expected: No errors

- [ ] **Step 3: Run coverage**

Run: `pytest tests/ --cov=src/scrapper --cov-report=term-missing`
Expected: Coverage maintained or improved

- [ ] **Step 4: Commit any remaining changes**

```bash
git status
# Commit if anything left
```
