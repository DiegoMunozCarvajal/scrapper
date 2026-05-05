import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import portalocker
import scrapy
from dateutil import parser as date_parser
from scrapy.spidermiddlewares.httperror import HttpError
from supabase import create_async_client

from ..items import PostItem
from ..prompts.reddit import REDDIT_PROMPT
from ..llm_extractor import llm_fallback

_RSS_HEADERS = {
    "Accept": "application/atom+xml,application/rss+xml,application/xml;q=0.9,text/xml;q=0.8,*/*;q=0.1",
    "Accept-Language": "en-US,en;q=0.9",
}

_SEARCH_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_PULLPUSH_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

_PULLPUSH_BASE = "https://api.pullpush.io/reddit/search/submission/"

try:
    import feedparser
except ImportError:
    feedparser = None


class RedditSpider(scrapy.Spider):
    name = "reddit"
    site = "reddit"
    site_type = "post"

    LLM_PROMPT = REDDIT_PROMPT

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cutoff_date = None
        self._latest_published = None
        self._cutoff_cache_path = None
        self.subreddit = getattr(self, "subreddit", None)

    @property
    def _cache_key(self):
        query = getattr(self, "query", "python")
        return f"{self.subreddit}:{query}" if self.subreddit else query

    async def _load_cutoff_date(self):
        supabase_url = self.settings.get("SUPABASE_URL")
        supabase_key = self.settings.get("SUPABASE_KEY")

        if supabase_url and supabase_key:
            client = None
            try:
                client = await create_async_client(supabase_url, supabase_key)
                q = (
                    client.table("posts")
                    .select("scraped_at")
                    .eq("site", "reddit")
                    .eq("metadata->>'query'", getattr(self, "query", "python"))
                )
                if self.subreddit:
                    q = q.eq("metadata->>'subreddit'", self.subreddit)
                result = await (
                    q.order("scraped_at", desc=True)
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
                        await client.postgrest.aclose()
                    except Exception:
                        pass

        if not self.cutoff_date:
            self._load_local_cutoff_date()

    def _load_local_cutoff_date(self):
        metrics_dir = self.settings.get("METRICS_DIR", "metrics")
        cache_file = Path(metrics_dir) / "reddit_cutoff.json"
        self._cutoff_cache_path = cache_file

        if not cache_file.exists():
            return

        try:
            with open(cache_file, "r") as f:
                portalocker.lock(f, portalocker.LOCK_SH)
                try:
                    data = json.load(f)
                finally:
                    portalocker.unlock(f)
            cutoff = data.get(self._cache_key)
            if cutoff:
                self.cutoff_date = cutoff
                self.logger.info(
                    f"Incremental mode (local cache): cutoff date = {self.cutoff_date}"
                )
        except (json.JSONDecodeError, OSError) as e:
            self.logger.warning(f"Could not load local cutoff cache: {e}")

    def _calculate_time_filter(self):
        if not self.cutoff_date:
            return "all"
        try:
            cutoff = date_parser.parse(self.cutoff_date)
            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_since = (now - cutoff).total_seconds() / 3600
        except Exception:
            return "all"

        if hours_since <= 1:
            return "hour"
        elif hours_since <= 24:
            return "day"
        elif hours_since <= 24 * 7:
            return "week"
        elif hours_since <= 24 * 30:
            return "month"
        elif hours_since <= 24 * 365:
            return "year"
        return "all"

    def _save_cutoff_cache(self):
        if not self._cutoff_cache_path:
            return
        latest = self._latest_published or self.cutoff_date
        if not latest:
            return

        self._cutoff_cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = {}
            if self._cutoff_cache_path.exists():
                with open(self._cutoff_cache_path, "r") as f:
                    portalocker.lock(f, portalocker.LOCK_SH)
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError:
                        pass
                    finally:
                        portalocker.unlock(f)
            data[self._cache_key] = latest
            with open(self._cutoff_cache_path, "w") as f:
                portalocker.lock(f, portalocker.LOCK_EX)
                try:
                    json.dump(data, f, indent=2)
                finally:
                    portalocker.unlock(f)
        except OSError as e:
            self.logger.warning(f"Could not save local cutoff cache: {e}")

    def close(self, reason):
        self._save_cutoff_cache()

    def _build_rss_request(self):
        query = getattr(self, "query", "python")
        limit = int(getattr(self, "limit", 10))
        time_filter = self._calculate_time_filter()
        if self.subreddit:
            rss_url = (
                f"https://www.reddit.com/r/{self.subreddit}/search.rss"
                f"?q={quote_plus(query)}&restrict_sr=on&sort=new&t={time_filter}&limit={limit}"
            )
        else:
            rss_url = (
                f"https://www.reddit.com/search.rss"
                f"?q={quote_plus(query)}&sort=new&t={time_filter}&limit={limit}"
            )
        return scrapy.Request(
            rss_url,
            callback=self.parse_rss,
            meta={"query": query, "limit": limit},
            errback=self._fallback_to_search,
            headers=_RSS_HEADERS,
        )

    async def start(self):
        await self._load_cutoff_date()

        yield scrapy.Request(
            "https://old.reddit.com/",
            callback=self._health_check,
            errback=self._health_check_error,
            dont_filter=True,
            meta={"health_check": True},
        )

        date_from = getattr(self, "date_from", None)
        date_to = getattr(self, "date_to", None)

        if date_from or date_to:
            self.logger.info(
                f"PullPush strategy: date_from={date_from}, date_to={date_to}"
            )
            yield self._build_pullpush_request(date_from=date_from, date_to=date_to)
        else:
            yield self._build_json_precheck_request()

    def _health_check(self, response):
        self.logger.info("Health check: old.reddit.com is reachable")

    def _health_check_error(self, failure):
        self.logger.error(
            f"Health check failed: old.reddit.com unreachable ({failure.value})"
        )

    def _build_json_precheck_request(self):
        query = getattr(self, "query", "python")
        time_filter = self._calculate_time_filter()
        if self.subreddit:
            url = (
                f"https://old.reddit.com/r/{self.subreddit}/search.json"
                f"?q={quote_plus(query)}"
                f"&sort=new"
                f"&type=link"
                f"&restrict_sr=on"
                f"&t={time_filter}"
                f"&limit=5"
            )
        else:
            url = (
                f"https://old.reddit.com/search.json"
                f"?q={quote_plus(query)}"
                f"&sort=new"
                f"&type=link"
                f"&restrict_sr=off"
                f"&t={time_filter}"
                f"&limit=5"
            )
        return scrapy.Request(
            url,
            callback=self.parse_json_precheck,
            errback=self._json_precheck_error,
            headers=_SEARCH_HEADERS,
        )

    def parse_json_precheck(self, response):
        try:
            data = json.loads(response.text)
        except (json.JSONDecodeError, ValueError):
            self.logger.warning(
                "JSON precheck: invalid JSON response, falling through to full search"
            )
            yield self._continue_to_full_search()
            return

        posts = data.get("data", {}).get("children", [])
        posts = [p for p in posts if p.get("kind") == "t3"]

        if not posts:
            self.logger.info("JSON precheck: no posts found, skipping full scrape")
            return

        has_new = self._check_json_posts_for_new_content(posts)
        if has_new:
            self.logger.info(
                "JSON precheck: new content found, proceeding with full search"
            )
            yield self._continue_to_full_search()
        else:
            newest_ts = posts[0]["data"].get("created_utc", 0)
            if newest_ts:
                newest_date = datetime.fromtimestamp(newest_ts, tz=timezone.utc).isoformat()
                self.logger.info(
                    f"JSON precheck: no new content since cutoff. "
                    f"Newest post from {newest_date}"
                )
            else:
                self.logger.info("JSON precheck: no new content since cutoff")

    def _check_json_posts_for_new_content(self, posts):
        if not self.cutoff_date:
            return True
        try:
            cutoff = date_parser.parse(self.cutoff_date)
            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=timezone.utc)
            cutoff_ts = cutoff.timestamp()
        except Exception:
            return True

        for post in posts:
            created_utc = post["data"].get("created_utc", 0)
            if created_utc > cutoff_ts:
                return True
        return False

    def _json_precheck_error(self, failure):
        self.logger.warning(
            f"JSON precheck request failed ({failure.value}), "
            "falling through to full search"
        )
        yield self._continue_to_full_search()

    def _continue_to_full_search(self):
        rss_enabled = self.settings.getbool("REDDIT_RSS_ENABLED", False)
        if rss_enabled:
            return self._build_rss_request()
        return self._build_html_search_request()

    def _build_html_search_request(self, query=None, limit=None):
        query = query or getattr(self, "query", "python")
        limit = limit or int(getattr(self, "limit", 10))
        time_filter = self._calculate_time_filter()
        if self.subreddit:
            url = (
                f"https://old.reddit.com/r/{self.subreddit}/search"
                f"?q={quote_plus(query)}"
                f"&sort=new"
                f"&type=link"
                f"&restrict_sr=on"
                f"&t={time_filter}"
            )
        else:
            url = (
                f"https://old.reddit.com/search"
                f"?q={quote_plus(query)}"
                f"&sort=new"
                f"&type=link"
                f"&restrict_sr=off"
                f"&t={time_filter}"
            )
        return scrapy.Request(
            url,
            callback=self.parse,
            errback=self._handle_search_error,
            meta={"query": query, "limit": limit, "count": 0},
            headers=_SEARCH_HEADERS,
        )

    def _handle_search_error(self, failure):
        self.logger.error(f"Search request failed: {failure.value}")

    def _fallback_to_search(self, failure):
        yield self._build_html_search_request(
            query=failure.request.meta["query"],
            limit=failure.request.meta["limit"],
        )

    def _date_str_to_epoch(self, date_str, end_of_day=False):
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            dt = dt.replace(tzinfo=timezone.utc)
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt.timestamp()
        except (ValueError, TypeError):
            self.logger.warning(f"Invalid date format: {date_str}, expected YYYY-MM-DD")
            return 0

    def _build_pullpush_request(
        self, date_from=None, date_to=None, before=None, page=1, scraped_count=0
    ):
        query = getattr(self, "query", "python")
        limit = int(getattr(self, "limit", 25))
        size = min(limit, 100)

        params = {
            "q": query,
            "size": size,
            "sort": "desc",
            "sort_type": "created_utc",
        }

        if self.subreddit:
            params["subreddit"] = self.subreddit

        if before is not None:
            params["before"] = int(before)
        elif date_to:
            params["before"] = int(self._date_str_to_epoch(date_to, end_of_day=True))

        if date_from:
            params["after"] = int(self._date_str_to_epoch(date_from))

        url = _PULLPUSH_BASE + "?" + "&".join(f"{k}={v}" for k, v in params.items())

        return scrapy.Request(
            url,
            callback=self.parse_pullpush,
            errback=self._handle_pullpush_error,
            meta={
                "query": query,
                "limit": limit,
                "strategy": "pullpush",
                "pullpush_page": page,
                "pullpush_size": size,
                "date_from": date_from,
                "date_to": date_to,
                "scraped_count": scraped_count,
            },
            headers=_PULLPUSH_HEADERS,
            dont_filter=True,
        )

    def parse_pullpush(self, response):
        try:
            data = json.loads(response.text)
        except (json.JSONDecodeError, ValueError):
            self.logger.warning("PullPush: invalid JSON response, stopping")
            return

        items = data.get("data", [])
        if not items:
            self.logger.info("PullPush: no results found")
            return

        query = response.meta["query"]
        limit = response.meta["limit"]
        date_from = response.meta["date_from"]
        date_to = response.meta["date_to"]
        scraped_count = response.meta["scraped_count"]
        page = response.meta["pullpush_page"]
        page_size = response.meta["pullpush_size"]

        min_created_utc = None

        for item_data in items:
            if scraped_count >= limit:
                return

            title = item_data.get("title", "")
            selftext = item_data.get("selftext", "")
            permalink = item_data.get("permalink", "")
            created_utc = item_data.get("created_utc", 0)
            author = item_data.get("author", "")

            if not title or not permalink:
                continue

            if selftext and selftext in ("[removed]", "[deleted]"):
                continue

            if min_created_utc is None or created_utc < min_created_utc:
                min_created_utc = created_utc

            post_url = (
                f"https://old.reddit.com{permalink}"
                if permalink.startswith("/")
                else permalink
            )

            published_at = (
                datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
                if created_utc
                else None
            )

            scraped_count += 1
            yield PostItem(
                site=self.site,
                url=post_url,
                title=title.strip(),
                author=author,
                content=selftext,
                score=item_data.get("score", 0),
                comment_count=item_data.get("num_comments", 0),
                published_at=published_at,
                metadata={
                    "type": "detail",
                    "strategy": "pullpush",
                    "query": query,
                    "top_comment": "",
                    "subreddit": item_data.get("subreddit", ""),
                    "id": item_data.get("id", ""),
                },
            )

        if scraped_count < limit and len(items) == page_size and min_created_utc:
            date_from_epoch = self._date_str_to_epoch(date_from) if date_from else 0
            if min_created_utc <= date_from_epoch:
                self.logger.info(
                    f"PullPush: reached date_from boundary at page {page}, stopping"
                )
                return

            self.logger.info(
                f"PullPush: page {page} done ({scraped_count}/{limit}), "
                f"fetching page {page + 1}"
            )
            yield self._build_pullpush_request(
                date_from=date_from,
                date_to=date_to,
                before=min_created_utc,
                page=page + 1,
                scraped_count=scraped_count,
            )

    def _handle_pullpush_error(self, failure):
        self.logger.warning(
            f"PullPush request failed ({failure.value}), "
            "falling back to Reddit native search (no date filter)"
        )
        yield self._build_html_search_request()

    def parse_rss(self, response):
        if feedparser is None:
            self.logger.error("feedparser not installed, falling back to HTML search")
            yield self._build_html_search_request(
                query=response.meta["query"],
                limit=response.meta["limit"],
            )
            return

        query = response.meta["query"]
        limit = response.meta["limit"]

        feed = feedparser.parse(response.text)

        if feed.bozo and not feed.entries:
            self.logger.warning(
                f"Malformed RSS feed (bozo_exception={feed.bozo_exception}), "
                "falling back to HTML search"
            )
            yield self._build_html_search_request(query=query, limit=limit)
            return

        count = 0
        filtered_count = 0
        for entry in feed.entries:
            if count >= limit:
                break

            title = entry.get("title", "")
            url = entry.get("link", "").replace("www.reddit.com", "old.reddit.com")
            published = entry.get("updated", "") or entry.get("published", "")

            if not title or not url:
                continue

            if published and self.cutoff_date:
                try:
                    post_time = date_parser.parse(published)
                    cutoff = date_parser.parse(self.cutoff_date)
                    if post_time < cutoff:
                        self.logger.info(
                            f"Skipping RSS post older than cutoff: {title}"
                        )
                        filtered_count += 1
                        continue
                except Exception:
                    pass

            count += 1

            yield response.follow(
                url,
                callback=self.parse_post_page,
                errback=self._handle_post_error,
                meta={"query": query, "limit": limit, "strategy": "rss"},
                headers=_SEARCH_HEADERS,
            )

        if count == 0 and filtered_count == 0:
            self.logger.info("RSS returned no entries, falling back to HTML search")
            yield self._build_html_search_request(query=query, limit=limit)
        elif count == 0:
            self.logger.info(
                f"All {filtered_count} RSS entries filtered by cutoff date, stopping"
            )

    def parse(self, response):
        """Fallback: old.reddit.com search results (Strategy 2)."""
        query = response.meta["query"]
        limit = response.meta["limit"]
        count = response.meta["count"]
        start_count = count

        cards = response.css("div.search-result-link")
        if not cards:
            self.logger.warning(
                "CSS selectors found no search-result-link cards "
                "(HTML structure may have changed), trying LLM fallback"
            )
            yield from llm_fallback(self, response, PostItem)
            return

        cards_with_time = 0
        cards_skipped_old = 0

        for card in cards:
            if count >= limit:
                break

            title_el = card.css("a.search-title")
            title = title_el.css("::text").get("")
            href = title_el.css("::attr(href)").get("")

            if not title or not href:
                continue

            post_time_str = card.css("time::attr(datetime)").get()
            if post_time_str:
                cards_with_time += 1
                if self.cutoff_date:
                    try:
                        post_time = date_parser.parse(post_time_str)
                        cutoff = date_parser.parse(self.cutoff_date)
                        if post_time < cutoff:
                            cards_skipped_old += 1
                            continue
                    except Exception:
                        pass

            count += 1
            yield response.follow(
                href,
                callback=self.parse_post_page,
                errback=self._handle_post_error,
                meta={"query": query, "limit": limit, "strategy": "html"},
                headers=_SEARCH_HEADERS,
            )

        if count == start_count:
            if cards_with_time > 0 and cards_with_time == cards_skipped_old:
                self.logger.info(
                    f"All {cards_with_time} dated search results older than cutoff, stopping"
                )
            elif cards_with_time == 0 and len(cards) > 0:
                self.logger.warning(
                    "No <time> tags found in search results, "
                    "HTML structure may have changed, trying LLM fallback"
                )
                yield from llm_fallback(self, response, PostItem)
            else:
                self.logger.warning(
                    "HTML selectors found nothing usable, trying LLM fallback"
                )
                yield from llm_fallback(self, response, PostItem)
            return

        if count < limit:
            next_link = response.css('a[rel="nofollow next"]::attr(href)').get()
            if next_link:
                yield response.follow(
                    next_link,
                    callback=self.parse,
                    errback=self._handle_pagination_error,
                    meta={"query": query, "limit": limit, "count": count},
                    headers=_SEARCH_HEADERS,
                )

    def _handle_post_error(self, failure):
        if failure.check(HttpError):
            response = failure.value.response
            if response.status == 429:
                retry_after = response.headers.get(b"Retry-After", b"unknown").decode()
                self.logger.warning(
                    f"Rate limited (429) on {failure.request.url}. "
                    f"Retry-After: {retry_after}"
                )
            else:
                self.logger.warning(
                    f"Post page returned HTTP {response.status}: {failure.request.url}"
                )
        else:
            self.logger.warning(
                f"Post page request failed after retries: {failure.request.url}"
            )

    def _handle_pagination_error(self, failure):
        if failure.check(HttpError):
            response = failure.value.response
            if response.status == 429:
                self.logger.warning(
                    f"Rate limited on pagination: {failure.request.url}"
                )
            else:
                self.logger.warning(
                    f"Pagination returned HTTP {response.status}: "
                    f"{failure.request.url}"
                )
        else:
            self.logger.warning(
                f"Pagination request failed, stopping: {failure.request.url}"
            )

    def _track_latest_published(self, post_time_str):
        if not self._latest_published:
            self._latest_published = post_time_str
        else:
            try:
                current = date_parser.parse(post_time_str)
                latest = date_parser.parse(self._latest_published)
                if current.tzinfo is None:
                    current = current.replace(tzinfo=timezone.utc)
                if latest.tzinfo is None:
                    latest = latest.replace(tzinfo=timezone.utc)
                if current > latest:
                    self._latest_published = post_time_str
            except Exception:
                pass

    def parse_post_page(self, response):
        """Extract full post content from detail page."""
        post_time_str = response.css("time::attr(datetime)").get()
        if post_time_str and self.cutoff_date:
            try:
                post_time = date_parser.parse(post_time_str)
                cutoff = date_parser.parse(self.cutoff_date)
                if post_time.tzinfo is None:
                    post_time = post_time.replace(tzinfo=timezone.utc)
                if cutoff.tzinfo is None:
                    cutoff = cutoff.replace(tzinfo=timezone.utc)
                if post_time < cutoff:
                    self.logger.info(
                        f"Stopping: post {post_time} older than cutoff {self.cutoff_date}"
                    )
                    return
            except Exception:
                pass

        content = "".join(response.css("div.md *::text").getall()).strip()

        removed_indicators = (
            response.css("div.md::text").getall()
            + response.css("a.author::text").getall()
        )
        if any("[removed]" in t or "[deleted]" in t for t in removed_indicators):
            self.logger.info(f"Skipping removed/deleted post: {response.url}")
            return

        if not content:
            domain_text = response.css("div.domain a::text").get("")
            if domain_text:
                content = domain_text

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

        score_text = (
            response.css("div.score.unvoted::text").get("")
            or response.css("div.score::text").get("")
            or ""
        )
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

        if post_time_str:
            self._track_latest_published(post_time_str)

        subreddit_name = ""
        url_parts = post_url.split("/r/")
        if len(url_parts) > 1:
            subreddit_name = url_parts[1].split("/")[0]

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
                "strategy": response.meta.get("strategy", "unknown"),
                "top_comment": top_comment[:500],
                "query": response.meta.get("query"),
                "subreddit": subreddit_name,
            },
        )
