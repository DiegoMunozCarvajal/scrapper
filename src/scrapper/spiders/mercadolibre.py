import re
import scrapy
from ..items import ProductItem


class MercadoLibreSpider(scrapy.Spider):
    name = "mercadolibre"
    site = "mercadolibre"
    site_type = "product"

    custom_settings = {
        "CONCURRENT_REQUESTS": 2,
        "DOWNLOAD_DELAY": 2,
    }

    def start_requests(self):
        query = getattr(self, "query", "laptop")
        limit = int(getattr(self, "limit", 10))
        url = f"https://listado.mercadolibre.com.co/{query.replace(' ', '-')}"
        yield scrapy.Request(
            url,
            meta={"playwright": True, "query": query, "limit": limit, "count": 0},
        )

    def parse(self, response):
        limit = response.meta["limit"]
        query = response.meta["query"]
        count = response.meta["count"]

        items = response.css("li.ui-search-layout__item")
        for item in items:
            if count >= limit:
                return

            title = item.css("h2::text").get("")

            price_text = item.css(".andes-money-amount__fraction::text").get("")
            price = _parse_price(price_text)

            url = item.css("a.ui-search-link::attr(href)").get("")

            rating_text = item.css(".ui-search-reviews__rating-number::text").get("")
            rating = float(rating_text) if rating_text else None

            if title and url:
                count += 1
                yield ProductItem(
                    site=self.site,
                    url=url,
                    title=title.strip(),
                    price=price,
                    currency="COP",
                    rating=rating,
                    review_count=0,
                    seller="",
                    availability="",
                    metadata={"query": query},
                )


def _parse_price(text: str) -> float | None:
    cleaned = re.sub(r"[^\d]", "", text)
    return float(cleaned) if cleaned else None