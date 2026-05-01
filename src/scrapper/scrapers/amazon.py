import re

from playwright.async_api import Page

from ..models import Product, ScrapeResult
from .base import TIMEOUT, BaseScraper


class AmazonScraper(BaseScraper):
    site = "amazon"

    async def search(self, query: str, limit: int = 10) -> ScrapeResult:
        return await self.run(query, limit)

    async def _do_search(self, page: Page, query: str, limit: int) -> ScrapeResult:
        url = f"https://www.amazon.com/s?k={query}"
        await page.goto(url, timeout=TIMEOUT)
        await page.wait_for_load_state("networkidle")

        products: list[Product] = []
        cards = await page.query_selector_all('[data-component-type="s-search-result"]')
        for card in cards:
            if len(products) >= limit:
                break
            try:
                title_el = await card.query_selector("h2")
                title = await title_el.inner_text() if title_el else ""

                link_el = await card.query_selector("h2 a")
                href = await link_el.get_attribute("href") if link_el else ""
                url = f"https://www.amazon.com{href}" if href else ""

                price_whole = await card.query_selector(".a-price-whole")
                price_fraction = await card.query_selector(".a-price-fraction")
                whole = await price_whole.inner_text() if price_whole else "0"
                fraction = await price_fraction.inner_text() if price_fraction else "00"
                price = _parse_price(f"{whole}.{fraction}")

                rating_el = await card.query_selector(".a-icon-alt")
                rating_text = await rating_el.inner_text() if rating_el else ""

                review_el = await card.query_selector(".a-size-base.s-underline-text")
                review_text = await review_el.inner_text() if review_el else "0"

                products.append(Product(
                    title=title,
                    url=url,
                    price=price,
                    currency="USD",
                    rating=_parse_rating(rating_text),
                    review_count=_parse_review_count(review_text),
                ))
            except Exception:
                continue

        return ScrapeResult(source=self.site, query=query, products=products[:limit])


def _parse_price(text: str) -> float | None:
    cleaned = "".join(c for c in text if c.isdigit() or c == ".")
    return float(cleaned) if cleaned else None


def _parse_rating(text: str) -> float | None:
    match = re.search(r"(\d+\.?\d*)", text)
    return float(match.group(1)) if match else None


def _parse_review_count(text: str) -> int:
    cleaned = re.sub(r"[^\d]", "", text)
    return int(cleaned) if cleaned else 0
