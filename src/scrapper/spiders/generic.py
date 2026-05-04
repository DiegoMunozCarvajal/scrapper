from urllib.parse import urlparse

import scrapy
from loguru import logger
from scrapy import Request
from scrapy_playwright.page import PageMethod

from ..items import GenericItem
from ..prompts.generic import GENERIC_PROMPT, TYPE_HINTS
from ..llm_extractor import llm_fallback
from ..pagination import PaginationDetector


async def _click_load_more_sp(page):
    """Playwright PageMethod: click load-more buttons repeatedly (max 10)."""
    for _ in range(10):
        found = False
        for sel in PaginationDetector.LOAD_MORE_CSS_SELECTORS:
            btn = page.locator(sel).first
            if await btn.count() > 0:
                try:
                    await btn.click()
                    await page.wait_for_timeout(1500)
                    found = True
                    break
                except Exception as e:
                    logger.warning("Load-more click failed for selector '%s': %s", sel, e)
        if not found:
            break
    return True


async def _scroll_infinite_sp(page):
    """Playwright PageMethod: scroll down until height stops growing (max 10)."""
    try:
        last_height = await page.evaluate("document.body.scrollHeight")
    except Exception as e:
        logger.warning("Failed to get initial scroll height: %s", e)
        return True
    stable_count = 0
    for _ in range(10):
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)
            new_height = await page.evaluate("document.body.scrollHeight")
        except Exception as e:
            logger.warning("Scroll/evaluate failed: %s", e)
            break
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
