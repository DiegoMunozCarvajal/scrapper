"""Custom Scrapy download handler using playwright-stealth v2."""

from typing import Optional

from playwright.async_api import BrowserContext, Page
from playwright_stealth import StealthConfig
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

        config = StealthConfig()
        await config.apply_stealth_async(context)

        return context

    async def _download_request(self, request: Request, spider) -> HtmlResponse:
        response = await super()._download_request(request, spider)

        if request.meta.get("playwright"):
            page: Page = request.meta.get("playwright_page")
            if page:
                try:
                    import random
                    scroll_y = random.randint(100, 600)
                    await page.evaluate(f"window.scrollBy(0, {scroll_y})")
                except Exception:
                    pass

        return response
