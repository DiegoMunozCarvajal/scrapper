import re
from urllib.parse import quote_plus

import scrapy
from ..items import ProductItem


class MercadoLibreSpider(scrapy.Spider):
    name = "mercadolibre"
    site = "mercadolibre"
    site_type = "product"
    DEPRECATED = True

    custom_settings = {
        "CONCURRENT_REQUESTS": 2,
        "DOWNLOAD_DELAY": 1,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger.warning(
            "MercadoLibre spider is DEPRECATED — requires residential proxies. "
            "Set PROXY_LIST with residential proxies to use this spider."
        )

    def start_requests(self):
        query = getattr(self, "query", "laptop")
        limit = int(getattr(self, "limit", 10))
        url = f"https://api.mercadolibre.com/sites/MCO/search?q={quote_plus(query)}&limit={limit}"
        yield scrapy.Request(url, meta={"query": query, "limit": limit})

    def parse(self, response):
        import json
        data = json.loads(response.text)
        limit = response.meta["limit"]

        for item in data.get("results", [])[:limit]:
            yield ProductItem(
                site=self.site,
                url=item.get("permalink", ""),
                title=item.get("title", ""),
                price=item.get("price"),
                currency=item.get("currency_id", "COP"),
                rating=None,
                review_count=item.get("reviews", {}).get("total", 0),
                seller=item.get("seller", {}).get("nickname", ""),
                availability="available" if item.get("available", True) else "unavailable",
                metadata={
                    "query": response.meta["query"],
                    "condition": item.get("condition", ""),
                },
            )


def _parse_price(text: str) -> float | None:
    cleaned = re.sub(r"[^\d]", "", text)
    return float(cleaned) if cleaned else None