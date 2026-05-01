import re
import scrapy
from ..items import ProductItem


class AmazonSpider(scrapy.Spider):
    name = "amazon"
    site = "amazon"
    site_type = "product"

    custom_settings = {
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 5,
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
    }

    def start_requests(self):
        query = getattr(self, "query", "laptop")
        limit = int(getattr(self, "limit", 10))
        url = f"https://www.amazon.com/s?k={query}"
        yield scrapy.Request(
            url,
            meta={"playwright": True, "query": query, "limit": limit, "count": 0},
        )

    def parse(self, response):
        limit = response.meta["limit"]
        query = response.meta["query"]
        count = response.meta["count"]

        cards = response.css('[data-component-type="s-search-result"]')
        for card in cards:
            if count >= limit:
                return

            title_el = card.css("h2")
            title = title_el.css("::text").get("")
            href = title_el.css("a::attr(href)").get()
            url = f"https://www.amazon.com{href}" if href else ""

            whole = card.css(".a-price-whole::text").get("0")
            fraction = card.css(".a-price-fraction::text").get("00")
            price = _parse_price(f"{whole}.{fraction}")

            rating_text = card.css(".a-icon-alt::text").get("")
            rating = _parse_rating(rating_text)

            review_text = card.css(".a-size-base.s-underline-text::text").get("0")
            reviews = _parse_int(review_text)

            if title and url:
                count += 1
                yield ProductItem(
                    site=self.site,
                    url=url,
                    title=title.strip(),
                    price=price,
                    currency="USD",
                    rating=rating,
                    review_count=reviews,
                    seller="",
                    availability="",
                    metadata={"query": query},
                )


def _parse_price(text: str) -> float | None:
    cleaned = "".join(c for c in text if c.isdigit() or c == ".")
    return float(cleaned) if cleaned else None


def _parse_rating(text: str) -> float | None:
    match = re.search(r"(\d+\.?\d*)", text)
    return float(match.group(1)) if match else None


def _parse_int(text: str) -> int:
    cleaned = re.sub(r"[^\d]", "", text)
    return int(cleaned) if cleaned else 0