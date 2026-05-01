import scrapy
from ..items import PostItem


class RedditSpider(scrapy.Spider):
    name = "reddit"
    site = "reddit"
    site_type = "post"

    custom_settings = {
        "DOWNLOAD_HANDLERS": {},
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 2,
    }

    def start_requests(self):
        query = getattr(self, "query", "python")
        limit = int(getattr(self, "limit", 10))
        url = f"https://old.reddit.com/search?q={query}&sort=relevance&type=link"
        yield scrapy.Request(url, meta={"query": query, "limit": limit, "count": 0})

    def parse(self, response):
        query = response.meta["query"]
        limit = response.meta["limit"]
        count = response.meta["count"]

        articles = response.css("article")
        for el in articles:
            if count >= limit:
                return

            title_el = el.css('a[slot="title"]')
            title = title_el.css("::text").get("")
            href = title_el.css("::attr(href)").get("")
            url = f"https://old.reddit.com{href}" if href else ""

            author = el.css('a[href*="/user/"]::text').get("")

            score_text = el.css('[data-testid="post-score"]::text').get("0")
            try:
                score = int(score_text)
            except (ValueError, TypeError):
                score = 0

            if title and url:
                count += 1
                yield PostItem(
                    site=self.site,
                    url=url,
                    title=title.strip(),
                    author=author.strip() if author else "",
                    content="",
                    score=score,
                    comment_count=0,
                    metadata={"query": query},
                )

        if count < limit:
            next_link = response.css('a[rel="nofollow next"]::attr(href)').get()
            if next_link:
                yield response.follow(
                    next_link,
                    meta={"query": query, "limit": limit, "count": count},
                )