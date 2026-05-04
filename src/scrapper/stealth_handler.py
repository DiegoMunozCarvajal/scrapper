"""Custom Scrapy download handler using playwright-stealth v2."""

import json
import os
from pathlib import Path
from typing import Optional

from loguru import logger
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

        cookie_persist = os.getenv("COOKIE_PERSIST_ENABLED", "true").lower() in (
            "true", "1", "yes",
        )
        if cookie_persist:
            cookie_file = Path(f"cookies/{name}.json")
            if cookie_file.exists():
                try:
                    storage_state = json.loads(cookie_file.read_text())
                    context_kwargs["storage_state"] = storage_state
                except (json.JSONDecodeError, OSError):
                    pass

        context = await super()._create_browser_context(name, context_kwargs)

        if cookie_persist:
            import asyncio
            async def save_on_close(ctx):
                try:
                    Path("cookies").mkdir(exist_ok=True)
                    state = await ctx.storage_state()
                    Path(f"cookies/{name}.json").write_text(
                        json.dumps(state.get("cookies", []))
                    )
                except Exception as e:
                    logger.warning(f"Failed to save cookies for context '{name}': {e}")

            def _schedule_cookie_save(ctx):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    logger.warning(
                        f"Cannot schedule cookie save for '{name}': no running event loop"
                    )
                    return
                try:
                    task = loop.create_task(save_on_close(ctx))
                except RuntimeError:
                    logger.warning(
                        f"Cannot schedule cookie save for '{name}': event loop closed"
                    )
                    return
                task.add_done_callback(
                    lambda t: logger.warning(
                        f"Cookie save for context '{name}' failed: {t.exception()}"
                    ) if t.exception() else None
                )
            context.on("close", _schedule_cookie_save)

        config = StealthConfig()
        await config.apply_stealth_async(context)

        return context

    async def _download_request(self, request: Request, spider) -> HtmlResponse:
        response = await super()._download_request(request, spider)

        if not request.meta.get("playwright"):
            return response

        page: Page = request.meta.get("playwright_page")
        if not page:
            return response

        human_simulation = os.getenv("PLAYWRIGHT_HUMAN_SIMULATION", "true").lower() in (
            "true", "1", "yes",
        )

        if human_simulation:
            try:
                await page.add_init_script("""
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
                        if (parameter === 37445) {
                            return 'Intel Inc.';
                        }
                        if (parameter === 37446) {
                            return 'Intel Iris OpenGL Engine';
                        }
                        return getParameter.call(this, parameter);
                    };
                """)

                import random
                scroll_count = random.randint(2, 4)
                for _ in range(scroll_count):
                    scroll_y = random.randint(100, 400)
                    await page.evaluate(f"window.scrollBy(0, {scroll_y})")
                    await page.wait_for_timeout(random.randint(200, 800))
            except Exception as e:
                logger.warning(f"Human simulation failed for {request.url}: {e}")

        return response
