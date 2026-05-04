from urllib.parse import quote_plus

import scrapy
from dateutil import parser as date_parser
from supabase import create_client

from ..items import PostItem
from ..prompts.reddit import REDDIT_PROMPT
from ..llm_extractor import llm_fallback
from ..utils import FakeFailure


class RedditSpider(scrapy.Spider):
    name = "reddit"
    site = "reddit"
    site_type = "post"

    LLM_PROMPT = REDDIT_PROMPT

    custom_settings = {
        "DOWNLOAD_HANDLERS": {},
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 2,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cutoff_date = None

    def _load_cutoff_date(self):
        supabase_url = self.settings.get("SUPABASE_URL")
        supabase_key = self.settings.get("SUPABASE_KEY")
        query = getattr(self, "query", "python")

        if supabase_url and supabase_key:
            client = None
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
            finally:
                if client:
                    try:
                        client.postgrest.session.aclose()
                    except Exception:
                        pass

    def start_requests(self):
        """Deprecated: kept for Scrapy <2.13 compatibility. Use start() instead."""
        self._load_cutoff_date()
        query = getattr(self, "query", "python")
        limit = int(getattr(self, "limit", 10))
        rss_url = f"https://www.reddit.com/search.rss?q={quote_plus(query)}&sort=new&limit={limit}"
        yield scrapy.Request(
            rss_url,
            callback=self.parse_rss,
            meta={"query": query, "limit": limit},
            errback=self._fallback_to_search,
        )

    async def start(self):
        self._load_cutoff_date()
        query = getattr(self, "query", "python")
        limit = int(getattr(self, "limit", 10))
        rss_url = f"https://www.reddit.com/search.rss?q={quote_plus(query)}&sort=new&limit={limit}"
        yield scrapy.Request(
            rss_url,
            callback=self.parse_rss,
            meta={"query": query, "limit": limit},
            errback=self._fallback_to_search,
        )

    def _fallback_to_search(self, failure):
        query = failure.request.meta["query"]
        limit = failure.request.meta["limit"]
        url = f"https://old.reddit.com/search?q={quote_plus(query)}&sort=new&type=link"
        yield scrapy.Request(url, meta={"query": query, "limit": limit, "count": 0})

    def parse_rss(self, response):
        query = response.meta["query"]
        limit = response.meta["limit"]

        import feedparser
        feed = feedparser.parse(response.text)

        count = 0
        for entry in feed.entries:
            if count >= limit:
                return

            title = entry.get("title", "")
            url = entry.get("link", "").replace("www.reddit.com", "old.reddit.com")
            published = entry.get("updated", "") or entry.get("published", "")

            if not title or not url:
                continue

            count += 1

            if published and self.cutoff_date:
                try:
                    post_time = date_parser.parse(published)
                    cutoff = date_parser.parse(self.cutoff_date)
                    if post_time < cutoff:
                        self.logger.info(
                            f"Skipping RSS post older than cutoff: {title}"
                        )
                        continue
                except Exception:
                    pass

            yield response.follow(
                url,
                callback=self.parse_post_page,
                meta={"query": query, "limit": limit, "count": count},
            )

        if count == 0:
            self.logger.info("RSS returned no entries, falling back to HTML search")
            yield from self._fallback_to_search(FakeFailure(response))

    def parse(self, response):
        """Fallback: old.reddit.com search results (Strategy 2)."""
        query = response.meta["query"]
        limit = response.meta["limit"]
        count = response.meta["count"]
        start_count = count

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

        if count == start_count:
            self.logger.warning("HTML selectors found nothing, trying LLM fallback")
            yield from llm_fallback(self, response, PostItem)
            return

        if count < limit:
            next_link = response.css('a[rel="nofollow next"]::attr(href)').get()
            if next_link:
                yield response.follow(
                    next_link,
                    meta={"query": query, "limit": limit, "count": count},
                )

    def parse_post_page(self, response):
        """Extract full post content from detail page."""
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
        if post_url.startswith("//"):
            post_url = f"https:{post_url}"
        elif not post_url.startswith("http"):
            post_url = f"https://old.reddit.com{post_url}"

        score_text = response.css("div.score.unvoted::text").get("")
        try:
            score = int(score_text) if score_text else 0
        except (ValueError, TypeError):
            score = 0

        comment_text = response.css("a.comments::text").get("")
        try:
            comment_count = (
                int(comment_text.replace(",", "").split()[0])
                if comment_text and comment_text.split()
                else 0
            )
        except (ValueError, IndexError):
            comment_count = 0

        author = response.css("a.author::text").get("")
        title = response.css("a.title::text").get("")

        if not post_url:
            self.logger.warning("Skipping post with no URL")
            return

        if not title:
            self.logger.warning(f"Skipping post with no title: {post_url}")
            return

        yield PostItem(
            site=self.site,
            url=post_url,
            title=title.strip(),
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


