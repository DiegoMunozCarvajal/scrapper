import re
import scrapy
from ..items import ProductItem


class AmazonSpider(scrapy.Spider):
    name = "amazon"
    site = "amazon"
    site_type = "product"
    DEPRECATED = True

    custom_settings = {
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 10,
        "RETRY_TIMES": 6,
        "RETRY_HTTP_CODES": [500, 502, 503, 504, 408, 429],
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger.warning(
            "Amazon spider is DEPRECATED — requires residential proxies. "
            "Set PROXY_LIST with residential proxies to use this spider."
        )

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

            if title and url:
                count += 1
                yield response.follow(
                    url,
                    callback=self.parse_product,
                    meta={"query": query, "limit": limit, "count": count},
                )


    def parse_product(self, response):
        """Follow product URL to extract description + seller info."""
        description = "".join(
            response.css("#productDescription *::text, #feature-bullets *::text").getall()
        ).strip()[:2000]

        seller = response.css("#sellerName *::text, #bylineInfo *::text").get("").strip()

        availability = response.css("#availability *::text").get("").strip()

        product_url = response.url
        if not product_url.startswith("http"):
            product_url = f"https://www.amazon.com{product_url}"

        yield ProductItem(
            site=self.site,
            url=product_url,
            title=response.css("#title::text, h1::text").get("").strip(),
            price=None,
            currency="USD",
            rating=None,
            review_count=0,
            seller=seller,
            availability=availability,
            metadata={"type": "detail", "description": description[:1000]},
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