import asyncio
from abc import ABC, abstractmethod

from playwright.async_api import async_playwright, Browser, Page

from ..models import ScrapeResult
from ..utils import random_user_agent

TIMEOUT = 30000


class BaseScraper(ABC):
    site: str

    def __init__(self, headless: bool = True, proxy: str | None = None):
        self.headless = headless
        self.proxy = proxy

    async def _new_page(self, browser: Browser) -> Page:
        context = await browser.new_context(
            user_agent=random_user_agent(),
            viewport={"width": 1920, "height": 1080},
            proxy={"server": self.proxy} if self.proxy else None,
        )
        page = await context.new_page()
        return page

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> ScrapeResult:
        ...

    async def run(self, query: str, limit: int = 10) -> ScrapeResult:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            page = await self._new_page(browser)
            try:
                result = await self._do_search(page, query, limit)
                return result
            finally:
                await page.context.close()
                await browser.close()

    @abstractmethod
    async def _do_search(self, page: Page, query: str, limit: int) -> ScrapeResult:
        ...

    def run_sync(self, query: str, limit: int = 10) -> ScrapeResult:
        return asyncio.run(self.run(query, limit))
