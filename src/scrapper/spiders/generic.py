from urllib.parse import urlparse

import scrapy

from ..items import GenericItem
from ..prompts.generic import GENERIC_PROMPT, TYPE_HINTS
from ..llm_extractor import llm_fallback


class GenericSpider(scrapy.Spider):
    name = "generic"
    site = "generic"
    LLM_PROMPT = GENERIC_PROMPT

    custom_settings = {
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 3,
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
    }

    def start_requests(self):
        task_url = getattr(self, "url", None)
        task_type = getattr(self, "type", None)

        if not task_url:
            self.logger.error("No URL provided. Use: -a url=https://... [-a type=product|article|forum|listing]")
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
            },
        )

    def parse(self, response):
        task_type = response.meta.get("task_type")

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
            else:
                self.logger.warning("No items extracted from %s (Playwright also failed)", response.url)

    def _playwright_request(self, response):
        meta = response.meta.copy()
        meta["_playwright_retry"] = True
        meta["playwright"] = True
        return scrapy.Request(
            url=response.url,
            callback=self.parse,
            errback=self._handle_error,
            meta=meta,
            dont_filter=True,
        )

    def _handle_error(self, failure):
        self.logger.error("Request failed for %s: %s", failure.request.url, failure.value)
