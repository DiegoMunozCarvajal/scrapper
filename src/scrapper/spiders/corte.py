import re
from urllib.parse import quote_plus

import scrapy
from scrapy import Request
from scrapy_playwright.page import PageMethod

from ..items import GenericItem


async def _wait_for_cse(page):
    """PageMethod: wait for Google CSE results to render in DOM."""
    await page.wait_for_selector(".gsc-result", timeout=15000)
    await page.wait_for_timeout(2000)
    return True


class CorteSpider(scrapy.Spider):
    """Spider for Corte Constitucional de Colombia jurisprudence search.

    Uses Playwright (visible browser) to bypass anti-bot detection, then
    extracts Google CSE results from the rendered DOM. Iterates through
    pagination within a single Playwright session.

    Usage:
        scrapy crawl corte -a query="libertad de expresion" -a limit=30
    """

    name = "corte"
    site = "corteconstitucional"

    custom_settings = {
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 3,
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
        "PLAYWRIGHT_LAUNCH_OPTIONS": {
            "headless": False,
            "args": ["--disable-blink-features=AutomationControlled"],
        },
    }

    def start_requests(self):
        query = getattr(self, "query", "libertad de expresion")
        limit = int(getattr(self, "limit", "20"))

        url = f"https://www.corteconstitucional.gov.co/buscador?q={quote_plus(query)}"

        yield Request(
            url=url,
            callback=self.parse,
            meta={
                "playwright": True,
                "playwright_include_page": True,
                "playwright_page_methods": [
                    PageMethod(_wait_for_cse),
                ],
                "query": query,
                "limit": limit,
            },
        )

    async def parse(self, response):
        query = response.meta["query"]
        limit = response.meta["limit"]
        page = response.meta.get("playwright_page")

        if not page:
            self.logger.warning("No Playwright page, stopping")
            return

        seen_urls = set()
        total_yielded = 0
        page_num = 0
        max_cse_pages = 10

        while total_yielded < limit and page_num < max_cse_pages:
            results = await page.evaluate("""() => {
                const items = [];
                document.querySelectorAll('.gsc-result').forEach(el => {
                    const titleEl = el.querySelector('.gs-title a, .gs-title');
                    const snippetEl = el.querySelector('.gs-snippet');
                    items.push({
                        title: titleEl ? titleEl.textContent.trim() : '',
                        url: el.querySelector('.gs-title a') ? el.querySelector('.gs-title a').href : '',
                        snippet: snippetEl ? snippetEl.textContent.trim() : '',
                    });
                });
                return items;
            }""")

            if not results and page_num > 0:
                self.logger.info("No CSE results on page %d, stopping pagination", page_num + 1)
                break

            for r in results:
                if total_yielded >= limit:
                    break

                title = r.get("title", "").strip()
                url = r.get("url", "").strip()
                snippet = r.get("snippet", "").strip()

                if not title or not url:
                    continue

                clean_url = url.split("?")[0] if "?" in url else url
                if clean_url in seen_urls:
                    continue
                seen_urls.add(clean_url)

                total_yielded += 1
                yield GenericItem(
                    site=self.site,
                    url=clean_url,
                    title=title,
                    content=snippet,
                    page_type="jurisprudencia",
                    metadata={
                        "strategy": "cse_dom",
                        "query": query,
                    },
                )

            if total_yielded >= limit:
                self.logger.info("Reached limit of %d items", limit)
                break

            # Click next page number
            next_num = page_num + 2  # page_num is 0-based, CSE pages are 1-based
            next_btn = page.locator(f'.gsc-cursor-page:has-text("{next_num}")').first
            if await next_btn.count() == 0:
                self.logger.info("No more CSE pages (stopped at page %d)", next_num - 1)
                break

            self.logger.info("Clicking CSE page %d", next_num)
            await next_btn.click()
            await page.wait_for_selector(".gsc-result", state="visible", timeout=10000)
            await page.wait_for_timeout(1000)
            page_num += 1

        await page.close()
