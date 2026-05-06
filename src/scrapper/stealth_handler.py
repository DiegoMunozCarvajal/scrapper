"""Custom Scrapy download handler using playwright-stealth v2."""

import json
import os
from pathlib import Path
from typing import Optional

from loguru import logger
from playwright.async_api import BrowserContext, Page
from scrapy import Request
from scrapy.http import HtmlResponse
from scrapy_playwright.handler import ScrapyPlaywrightDownloadHandler

_COOKIE_DIR = Path(__file__).parent.parent.parent / "cookies"

# playwright-stealth v2.0.3 ships different APIs per platform wheel.
# Try the new API (StealthConfig + stealth_async) first, fall back
# to the old API (Stealth + apply_stealth_async).
try:
    from playwright_stealth import StealthConfig, stealth_async
    _NEW_STEALTH_API = True
except ImportError:
    from playwright_stealth import Stealth
    StealthConfig = Stealth  # noqa: N811
    _NEW_STEALTH_API = False


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


class ScrapyPlaywrightStealthDownloadHandler(ScrapyPlaywrightDownloadHandler):
    """Playwright download handler with playwright-stealth v2 patches."""

    async def _create_browser_context(
        self,
        name: str,
        context_kwargs: Optional[dict] = None,
        spider=None,
    ) -> BrowserContext:
        context_kwargs = context_kwargs or {}

        cookie_persist = os.getenv("COOKIE_PERSIST_ENABLED", "true").lower() in (
            "true", "1", "yes",
        )
        if cookie_persist:
            cookie_file = _COOKIE_DIR / f"{name}.json"
            if cookie_file.exists():
                storage_state = _load_storage_state(cookie_file)
                if storage_state:
                    context_kwargs["storage_state"] = storage_state

        context = await super()._create_browser_context(name, context_kwargs)

        if cookie_persist:
            import asyncio
            async def save_on_close(ctx):
                try:
                    await _save_storage_state(ctx, _COOKIE_DIR / f"{name}.json")
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

        return context

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

    async def _simulate_human_scroll(self, page: Page, url: str) -> None:
        try:
            import random
            for _ in range(random.randint(2, 4)):
                await page.evaluate(f"window.scrollBy(0, {random.randint(100, 400)})")
                await page.wait_for_timeout(random.randint(200, 800))
        except Exception as e:
            logger.warning(f"Human simulation failed for {url}: {e}")

    async def _download_request(self, request: Request, spider=None) -> HtmlResponse:
        if spider is None:
            spider = self._crawler.spider

        if request.meta.get("playwright"):
            self._ensure_page_init_callback(request)

        response = await super()._download_request(request, spider)

        if request.meta.get("playwright") and request.meta.get("playwright_page"):
            page: Page = request.meta["playwright_page"]
            if os.getenv("PLAYWRIGHT_HUMAN_SIMULATION", "true").lower() in ("true", "1", "yes"):
                await self._simulate_human_scroll(page, request.url)

        return response
