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
            href = title_el.css("::attr(href)").get("")

            if title and href:
                count += 1
                yield response.follow(
                    href,
                    callback=self.parse_post,
                    meta={"query": query, "limit": limit, "count": count},
                )

        if count < limit:
            next_link = response.css('a[rel="nofollow next"]::attr(href)').get()
            if next_link:
                yield response.follow(
                    next_link,
                    meta={"query": query, "limit": limit, "count": count},
                )

    def parse_post(self, response):
        """Follow post URL to extract full content + top comment."""
        content = "".join(response.css("div.md *::text").getall()).strip()

        top_comment = ""
        comments = response.css("div.commentarea div.md")
        if comments:
            first_comment = comments[0]
            top_comment = "".join(first_comment.css("*::text").getall()).strip()

        post_url = response.url
        if not post_url.startswith("http"):
            post_url = f"https://old.reddit.com{post_url}"

        yield PostItem(
            site=self.site,
            url=post_url,
            title=response.css("a.title::text").get("").strip(),
            author=response.css("a.author::text").get("").strip(),
            content=content,
            score=0,
            comment_count=0,
            metadata={"type": "detail", "top_comment": top_comment[:500]},
        )