import scrapy
from ..items import ProductItem


class HotmartSpider(scrapy.Spider):
    name = "hotmart"
    site = "hotmart"
    site_type = "product"

    custom_settings = {
        "CONCURRENT_REQUESTS": 2,
        "DOWNLOAD_DELAY": 3,
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
    }

    def start_requests(self):
        query = getattr(self, "query", "marketing")
        limit = int(getattr(self, "limit", 10))
        url = f"https://hotmart.com/en/marketplace/search?q={query}"
        yield scrapy.Request(
            url,
            meta={"playwright": True, "query": query, "limit": limit},
        )

    def parse(self, response):
        limit = response.meta["limit"]
        query = response.meta["query"]

        cards = response.css("div.product-card-alt")
        count = 0

        for card in cards:
            if count >= limit:
                break

            title_el = card.css(".product-card-alt__title")
            title = title_el.css("::text").get("").strip()

            author_el = card.css(".product-card-alt__author")
            author = author_el.css("::text").get("").strip()

            rating_el = card.css(".product-card-alt__rating span::text")
            rating = rating_el.get("").strip()

            url_el = card.css("a.product-link::attr(href)")
            url = url_el.get("")

            if title and url:
                count += 1
                yield ProductItem(
                    site=self.site,
                    url=url,
                    title=title,
                    price=None,
                    currency="USD",
                    rating=float(rating) if rating else None,
                    review_count=0,
                    seller=author,
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