import re
import scrapy
from ..items import ProductItem


class HotmartSpider(scrapy.Spider):
    name = "hotmart"
    site = "hotmart"
    site_type = "product"

    custom_settings = {
        "CONCURRENT_REQUESTS": 2,
        "DOWNLOAD_DELAY": 3,
    }

    def start_requests(self):
        query = getattr(self, "query", "marketing")
        limit = int(getattr(self, "limit", 10))
        url = f"https://hotmart.com/en/marketplace/search?q={query}"
        yield scrapy.Request(
            url,
            meta={"playwright": True, "query": query, "limit": limit, "count": 0},
        )

    def parse(self, response):
        limit = response.meta["limit"]
        query = response.meta["query"]
        count = response.meta["count"]

        cards = response.css('[class*="product"]')
        for card in cards:
            if count >= limit:
                return

            title_el = card.css("h2, h3, [class*='title']")
            title = title_el.css("::text").get("")

            price_el = card.css("[class*='price'], [class*='Price']")
            price_text = price_el.css("::text").get("")
            price = _parse_price(price_text)

            url = card.css("a::attr(href)").get("")

            if title and url:
                count += 1
                yield ProductItem(
                    site=self.site,
                    url=url,
                    title=title.strip(),
                    price=price,
                    currency="USD",
                    rating=None,
                    review_count=0,
                    seller="",
                    availability="",
                    metadata={"query": query},
                )


def _parse_price(text: str) -> float | None:
    try:
        cleaned = "".join(c for c in text if c.isdigit() or c in ".,")
        cleaned = cleaned.replace(",", ".")
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None