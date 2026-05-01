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

        cards = response.css("div.search-result-link")
        for card in cards:
            if count >= limit:
                return

            title_el = card.css("a.search-title")
            title = title_el.css("::text").get("")
            url = title_el.css("::attr(href)").get("")

            author = card.css("a.author::text").get("")

            score_text = card.css("span.search-score::text").get("0")
            try:
                score = int(score_text.split()[0])
            except (ValueError, TypeError, IndexError):
                score = 0

            comment_text = card.css("a.search-comments::text").get("0 comments")
            try:
                comment_count = int(comment_text.split()[0])
            except (ValueError, TypeError, IndexError):
                comment_count = 0

            content = "".join(card.css("div.md *::text").getall()).strip()

            if title and url:
                count += 1
                yield PostItem(
                    site=self.site,
                    url=url,
                    title=title.strip(),
                    author=author.strip() if author else "",
                    content=content.strip() if content else "",
                    score=score,
                    comment_count=comment_count,
                    metadata={"query": query},
                )

        if count < limit:
            next_link = response.css('a[rel="nofollow next"]::attr(href)').get()
            if next_link:
                yield response.follow(
                    next_link,
                    meta={"query": query, "limit": limit, "count": count},
                )