import re

from playwright.async_api import Page

from ..models import Product, ScrapeResult
from .base import TIMEOUT, BaseScraper


class MercadoLibreScraper(BaseScraper):
    site = "mercadolibre"

    async def search(self, query: str, limit: int = 10) -> ScrapeResult:
        return await self.run(query, limit)

    async def _do_search(self, page: Page, query: str, limit: int) -> ScrapeResult:
        url = f"https://listado.mercadolibre.com.co/{query.replace(' ', '-')}"
        await page.goto(url, timeout=TIMEOUT)
        await page.wait_for_load_state("networkidle")

        products: list[Product] = []
        items = await page.query_selector_all("li.ui-search-layout__item")
        for item in items:
            if len(products) >= limit:
                break
            try:
                title_el = await item.query_selector("h2")
                title = await title_el.inner_text() if title_el else ""

                price_el = await item.query_selector(".andes-money-amount__fraction")
                price_text = await price_el.inner_text() if price_el else ""

                link_el = await item.query_selector("a.ui-search-link")
                url = await link_el.get_attribute("href") if link_el else ""

                rating_el = await item.query_selector(".ui-search-reviews__rating-number")
                rating_text = await rating_el.inner_text() if rating_el else ""
                rating = float(rating_text) if rating_text else None

                products.append(Product(
                    title=title,
                    url=url,
                    price=_parse_price(price_text),
                    currency="COP",
                    rating=rating,
                ))
            except Exception:
                continue

        return ScrapeResult(source=self.site, query=query, products=products[:limit])


def _parse_price(text: str) -> float | None:
    cleaned = re.sub(r"[^\d]", "", text)
    return float(cleaned) if cleaned else None
