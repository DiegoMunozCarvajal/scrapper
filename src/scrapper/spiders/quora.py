import scrapy
from ..items import PostItem


class QuoraSpider(scrapy.Spider):
    name = "quora"
    site = "quora"
    site_type = "post"

    custom_settings = {
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 3,
    }

    def start_requests(self):
        query = getattr(self, "query", "python")
        limit = int(getattr(self, "limit", 10))
        url = f"https://www.quora.com/search?q={query}&type=question"
        yield scrapy.Request(
            url,
            meta={"playwright": True, "query": query, "limit": limit, "count": 0},
        )

    def parse(self, response):
        limit = response.meta["limit"]
        query = response.meta["query"]
        count = response.meta["count"]

        cards = response.css('[class*="qu-bg--white"]')
        for card in cards:
            if count >= limit:
                return

            title_el = card.css("span")
            title = "".join(title_el.css("::text").getall()).strip()

            href = card.css("a::attr(href)").get("")
            url = f"https://www.quora.com{href}" if href else ""

            if title and url:
                count += 1
                yield PostItem(
                    site=self.site,
                    url=url,
                    title=title,
                    author="quora",
                    content="",
                    score=0,
                    comment_count=0,
                    metadata={"query": query},
                )