from playwright.async_api import Page

from ..models import Product, ScrapeResult
from .base import TIMEOUT, BaseScraper


class HotmartScraper(BaseScraper):
    site = "hotmart"

    async def search(self, query: str, limit: int = 10) -> ScrapeResult:
        return await self.run(query, limit)

    async def _do_search(self, page: Page, query: str, limit: int) -> ScrapeResult:
        url = f"https://hotmart.com/en/marketplace/search?q={query}"
        await page.goto(url, timeout=TIMEOUT)
        await page.wait_for_load_state("networkidle")

        products: list[Product] = []
        cards = await page.query_selector_all('[class*="product"]')
        for card in cards:
            if len(products) >= limit:
                break
            try:
                title_el = await card.query_selector("h2, h3, [class*='title']")
                title = await title_el.inner_text() if title_el else ""

                price_el = await card.query_selector("[class*='price'], [class*='Price']")
                price_text = await price_el.inner_text() if price_el else ""

                link_el = await card.query_selector("a")
                url = await link_el.get_attribute("href") if link_el else ""

                if title:
                    products.append(Product(title=title, url=url, price=_parse_price(price_text)))
            except Exception:
                continue

        return ScrapeResult(source=self.site, query=query, products=products[:limit])


def _parse_price(text: str) -> float | None:
    try:
        cleaned = "".join(c for c in text if c.isdigit() or c in ".,")
        cleaned = cleaned.replace(",", ".")
        return float(cleaned)
    except (ValueError, TypeError):
        return None
