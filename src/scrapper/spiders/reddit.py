import scrapy
from dateutil import parser as date_parser
from supabase import create_client

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cutoff_date = None
        self._load_cutoff_date()

    def _load_cutoff_date(self):
        supabase_url = self.settings.get("SUPABASE_URL")
        supabase_key = self.settings.get("SUPABASE_KEY")
        query = getattr(self, "query", "python")

        if supabase_url and supabase_key:
            try:
                client = create_client(supabase_url, supabase_key)
                result = (
                    client.table("posts")
                    .select("scraped_at")
                    .eq("site", "reddit")
                    .eq("metadata->>'query'", query)
                    .order("scraped_at", desc=True)
                    .limit(1)
                    .execute()
                )
                if result.data:
                    self.cutoff_date = result.data[0].get("scraped_at")
                    self.logger.info(f"Incremental mode: cutoff date = {self.cutoff_date}")
            except Exception as e:
                self.logger.warning(f"Could not load cutoff date: {e}")

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
                    callback=self.parse_post_page,
                    meta={"query": query, "limit": limit, "count": count},
                )

        if count < limit:
            next_link = response.css('a[rel="nofollow next"]::attr(href)').get()
            if next_link:
                yield response.follow(
                    next_link,
                    meta={"query": query, "limit": limit, "count": count},
                )

    def parse_post_page(self, response):
        """Follow post URL to extract full content + top comment."""
        post_time_str = response.css("time::attr(datetime)").get()
        if post_time_str and self.cutoff_date:
            try:
                post_time = date_parser.parse(post_time_str)
                cutoff = date_parser.parse(self.cutoff_date)
                if post_time < cutoff:
                    self.logger.info(
                        f"Stopping: post {post_time} older than cutoff {self.cutoff_date}"
                    )
                    return
            except Exception:
                pass

        content = "".join(response.css("div.md *::text").getall()).strip()

        top_comment = ""
        comments = response.css("div.commentarea div.md")
        if comments:
            first_comment = comments[0]
            top_comment = "".join(first_comment.css("*::text").getall()).strip()

        post_url = response.url
        if not post_url.startswith("http"):
            post_url = f"https://old.reddit.com{post_url}"

        score_text = response.css("span.score::text").get("")
        try:
            score = int(score_text) if score_text else 0
        except (ValueError, TypeError):
            score = 0

        comment_text = response.css("a.comments::text").get("")
        try:
            comment_count = (
                int(comment_text.split()[0]) if comment_text and comment_text.split() else 0
            )
        except (ValueError, IndexError):
            comment_count = 0

        author = response.css("a.author::text").get("")
        title = response.css("a.title::text").get("")

        yield PostItem(
            site=self.site,
            url=post_url,
            title=title.strip() if title else "",
            author=author.strip() if author else "",
            content=content,
            score=score,
            comment_count=comment_count,
            published_at=post_time_str,
            metadata={
                "type": "detail",
                "top_comment": top_comment[:500],
                "query": response.meta.get("query"),
            },
        )
