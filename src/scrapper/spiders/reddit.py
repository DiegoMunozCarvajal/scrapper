import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
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

_JSON_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

_PULLPUSH_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

_PULLPUSH_BASE = "https://api.pullpush.io/reddit/search/submission/"

_REDDIT_JSON_LIMIT = 100


class RedditSpider(scrapy.Spider):
    name = "reddit"
    site = "reddit"
    site_type = "post"

    LLM_PROMPT = REDDIT_PROMPT

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cutoff_date = None
        self._cutoff_dt = None
        self._latest_published = None
        self._cutoff_cache_path = None
        self.subreddit = getattr(self, "subreddit", None)
        self.query = getattr(self, "query", None)
        self.sort = getattr(self, "sort", "new")
        self.time_filter = getattr(self, "time_filter", None)
        self.nsfw = getattr(self, "nsfw", "include")
        self.include_comments = getattr(self, "include_comments", False)
        if not self.query:
            if self.subreddit:
                self._has_query = False
            else:
                self.query = "python"
                self._has_query = True
        else:
            self._has_query = True
        self._validate_subreddit()

    def _validate_subreddit(self):
        """Warn if subreddit name looks invalid."""
        if self.subreddit and not self._has_query:
            if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_]{1,20}$', self.subreddit):
                self.logger.warning(
                    f"Subreddit '{self.subreddit}' looks invalid — may produce no results"
                )

    @staticmethod
    def _normalize_post_url(url):
        """Normalize a Reddit URL: ensure https protocol and full old.reddit.com domain."""
        if not url:
            return ""
        if url.startswith("//"):
            return f"https:{url}"
        if not url.startswith("http"):
            return f"https://old.reddit.com{url}"
        return url

    def _build_reddit_base_url(self, path, query=None, sort=None, time_filter=None,
                               restrict_sr=False, type_filter=None, raw_json=False,
                               limit=None):
        """Build an old.reddit.com URL with consistent query parameters."""
        params = []
        if query:
            params.append(f"q={quote_plus(query)}")
        if sort:
            params.append(f"sort={sort}")
        if type_filter:
            params.append(f"type={type_filter}")
        if restrict_sr:
            if self.subreddit:
                params.append("restrict_sr=on")
            else:
                params.append("restrict_sr=off")
        if time_filter:
            params.append(f"t={time_filter}")
        if raw_json:
            params.append("raw_json=1")
        if limit is not None:
            params.append(f"limit={limit}")
        url = f"https://old.reddit.com{path}"
        if params:
            url += "?" + "&".join(params)
        return url

    @property
    def _cache_key(self):
        if self._has_query:
            return f"{self.subreddit}:{self.query}" if self.subreddit else self.query
        if self.subreddit:
            return f"{self.subreddit}:sort={self.sort}"
        return f"sort={self.sort}"

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
                )
                if self._has_query:
                    q = q.eq("metadata->>'query'", self.query)
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
                    except (AttributeError, Exception):
                        try:
                            client.postgrest.session.close()
                        except Exception:
                            pass

        if not self.cutoff_date:
            self._load_local_cutoff_date()

        if self.cutoff_date:
            try:
                self._cutoff_dt = date_parser.parse(self.cutoff_date)
                if self._cutoff_dt.tzinfo is None:
                    self._cutoff_dt = self._cutoff_dt.replace(tzinfo=timezone.utc)
            except Exception:
                self._cutoff_dt = None

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
                try:
                    self._cutoff_dt = date_parser.parse(cutoff)
                    if self._cutoff_dt.tzinfo is None:
                        self._cutoff_dt = self._cutoff_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    self._cutoff_dt = None
                self.logger.info(
                    f"Incremental mode (local cache): cutoff date = {self.cutoff_date}"
                )
        except (json.JSONDecodeError, OSError) as e:
            self.logger.warning(f"Could not load local cutoff cache: {e}")

    def _calculate_time_filter(self):
        if self._cutoff_dt is None:
            return "all"
        now = datetime.now(timezone.utc)
        hours_since = (now - self._cutoff_dt).total_seconds() / 3600

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
        query = self.query if self._has_query else None
        limit = min(int(getattr(self, "limit", 25)), _REDDIT_JSON_LIMIT)
        time_filter = self.time_filter or self._calculate_time_filter()
        if self._has_query:
            path = f"/r/{self.subreddit}/search.rss" if self.subreddit else "/search.rss"
            url = self._build_reddit_base_url(
                path=path, query=query, sort="new", restrict_sr=bool(self.subreddit),
                time_filter=time_filter, limit=limit,
            )
        else:
            if self.sort == "new":
                path = f"/r/{self.subreddit}/new.rss"
                url = self._build_reddit_base_url(path=path, sort="new", limit=limit)
            else:
                path = f"/r/{self.subreddit}.rss"
                url = self._build_reddit_base_url(path=path, limit=limit)
        return scrapy.Request(
            url,
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
            yield self._build_json_request()

    def start_requests(self):
        """Synchronous fallback for Scrapy < 2.13 (when async start() is not supported)."""
        yield scrapy.Request(
            "https://old.reddit.com/",
            callback=self._health_check,
            errback=self._health_check_error,
            dont_filter=True,
            meta={"health_check": True},
        )
        yield self._build_json_request()

    def _health_check(self, response):
        self.logger.info("Health check: old.reddit.com is reachable")

    def _health_check_error(self, failure):
        self.logger.error(
            f"Health check failed: old.reddit.com unreachable ({failure.value})"
        )

    def _build_json_request(self, after=None, count=0):
        query = self.query if self._has_query else None
        limit = min(int(getattr(self, "limit", 25)), _REDDIT_JSON_LIMIT)
        time_filter = self.time_filter or self._calculate_time_filter()
        sort = self.sort

        if self._has_query:
            path = f"/r/{self.subreddit}/search.json" if self.subreddit else "/search.json"
            url = self._build_reddit_base_url(
                path=path, query=query, sort=sort, type_filter="link",
                restrict_sr=bool(self.subreddit), time_filter=time_filter,
                raw_json=True, limit=limit,
            )
        else:
            valid_sorts = ("new", "hot", "top", "rising", "controversial")
            if sort not in valid_sorts:
                sort = "new"
            path = f"/r/{self.subreddit}/{sort}.json"
            url = self._build_reddit_base_url(
                path=path, time_filter=time_filter, raw_json=True, limit=limit,
            )

        if after:
            url += f"&after={after}"
        if count:
            url += f"&count={count}"

        return scrapy.Request(
            url,
            callback=self.parse_json_results,
            errback=self._json_request_error,
            meta={
                "query": query,
                "limit": limit,
                "count": count,
                "strategy": "json_api",
            },
            headers=_JSON_HEADERS,
        )

    def parse_json_results(self, response):
        try:
            data = json.loads(response.text)
        except (json.JSONDecodeError, ValueError):
            self.logger.warning(
                "JSON API: invalid JSON response, falling through to fallback"
            )
            yield self._continue_to_full_search()
            return

        children = data.get("data", {}).get("children", [])
        posts = [p for p in children if p.get("kind") == "t3"]

        if not posts:
            self.logger.info("JSON API: no posts found")
            return

        query = response.meta["query"]
        limit = response.meta["limit"]
        count = response.meta["count"]
        start_count = count

        skipped_old = 0

        for post in posts:
            if count >= limit:
                break

            post_data = post["data"]
            title = (post_data.get("title", "") or "").strip()
            permalink = post_data.get("permalink", "")

            if not title or not permalink:
                continue

            if title in ("[removed]", "[deleted]") or \
               post_data.get("author", "") in ("[deleted]",):
                continue

            if self.nsfw == "exclude" and post_data.get("over_18"):
                continue
            if self.nsfw == "only" and not post_data.get("over_18"):
                continue

            created_utc = post_data.get("created_utc", 0)
            if created_utc and self._is_past_cutoff(created_utc):
                skipped_old += 1
                continue

            count += 1
            is_self = post_data.get("is_self", False)

            post_url = (
                f"https://old.reddit.com{permalink}"
                if permalink.startswith("/")
                else permalink
            )

            if is_self and not self.include_comments:
                yield self._build_post_item_from_json(post_data, query)
            else:
                yield response.follow(
                    post_url,
                    callback=self.parse_post_page,
                    errback=self._handle_post_error,
                    meta={
                        "query": query,
                        "limit": limit,
                        "strategy": "json_api",
                        "_json_data": post_data,
                    },
                    headers=_SEARCH_HEADERS,
                )

        if count == start_count:
            if skipped_old > 0:
                self.logger.info(
                    f"JSON API: all {skipped_old} posts older than cutoff, stopping"
                )
                return
            self.logger.warning(
                "JSON API: no usable posts, falling through to HTML search"
            )
            yield self._build_html_search_request()
            return

        after_fullname = data.get("data", {}).get("after")
        if count < limit and after_fullname:
            self.logger.info(
                f"JSON API: page done ({count}/{limit}), fetching next page"
            )
            yield self._build_json_request(after=after_fullname, count=count)

    def _make_post_item(self, title, url, author="", content="", score=0,
                        comment_count=0, published_at=None, thumbnail="",
                        link_flair="", domain="", nsfw=False, is_self_post=False,
                        permalink="", query=None, strategy="unknown",
                        subreddit="", post_id="", top_comments=None):
        """Centralized PostItem factory for Reddit spider."""
        return PostItem(
            site=self.site,
            url=url,
            title=title.strip() if title else "",
            author=author.strip() if author else "",
            content=content,
            score=score,
            comment_count=comment_count,
            published_at=published_at,
            thumbnail=thumbnail or "",
            link_flair=link_flair or "",
            domain=domain or "",
            nsfw=nsfw,
            is_self_post=is_self_post,
            permalink=permalink or "",
            metadata={
                "type": "detail",
                "strategy": strategy,
                "top_comments": top_comments or [],
                "query": query,
                "subreddit": subreddit,
                "id": post_id,
            },
        )

    def _build_post_item_from_json(self, post_data, query):
        created_utc = post_data.get("created_utc", 0)
        published_at = (
            datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
            if created_utc
            else None
        )

        permalink = post_data.get("permalink", "")
        post_url = self._normalize_post_url(permalink)

        if published_at:
            self._track_latest_published(published_at)

        return self._make_post_item(
            title=post_data.get("title", ""),
            url=post_url,
            author=post_data.get("author", ""),
            content=post_data.get("selftext", ""),
            score=post_data.get("score", 0),
            comment_count=post_data.get("num_comments", 0),
            published_at=published_at,
            thumbnail=post_data.get("thumbnail", ""),
            link_flair=post_data.get("link_flair_text", ""),
            domain=post_data.get("domain", ""),
            nsfw=post_data.get("over_18", False),
            is_self_post=True,
            permalink=permalink,
            query=query,
            strategy="json_api",
            subreddit=post_data.get("subreddit", ""),
            post_id=post_data.get("id", ""),
        )

    def _is_past_cutoff(self, dt_value):
        """Check if a datetime/timestamp/string is older than the cutoff. Returns bool.

        Uses <= (inclusive): posts created exactly at the cutoff are excluded.
        """
        if self._cutoff_dt is None:
            return False
        if dt_value is None:
            return False
        try:
            if isinstance(dt_value, (int, float)):
                return dt_value <= self._cutoff_dt.timestamp()
            dt = dt_value
            if isinstance(dt, str):
                dt = date_parser.parse(dt)
            if not isinstance(dt, datetime):
                return False
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt <= self._cutoff_dt
        except Exception:
            return False

    @staticmethod
    def _normalize_published_at(raw_date):
        """Convert a date string to ISO 8601 with UTC timezone."""
        if not raw_date:
            return None
        try:
            dt = date_parser.parse(raw_date)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except Exception:
            return raw_date  # Return as-is if parsing fails

    def _json_request_error(self, failure):
        self.logger.warning(
            f"JSON request failed ({failure.value}), falling through to full search"
        )
        yield self._continue_to_full_search()

    def _continue_to_full_search(self):
        rss_enabled = self.settings.getbool("REDDIT_RSS_ENABLED", True)
        if rss_enabled:
            return self._build_rss_request()
        return self._build_html_search_request()

    def _build_html_search_request(self, query=None, limit=None):
        query = query if query is not None else self.query
        limit = limit or int(getattr(self, "limit", 10))
        time_filter = self._calculate_time_filter()
        if self._has_query:
            path = f"/r/{self.subreddit}/search" if self.subreddit else "/search"
            url = self._build_reddit_base_url(
                path=path, query=query, sort="new", type_filter="link",
                restrict_sr=bool(self.subreddit), time_filter=time_filter,
            )
        else:
            if self.sort == "new":
                path = f"/r/{self.subreddit}/new"
                url = self._build_reddit_base_url(path=path, sort="new")
            else:
                path = f"/r/{self.subreddit}/"
                url = self._build_reddit_base_url(path=path)
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
            query=failure.request.meta.get("query", self.query),
            limit=failure.request.meta.get("limit", int(getattr(self, "limit", 10))),
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
        query = self.query if self._has_query else None
        limit = int(getattr(self, "limit", 25))
        size = min(limit, 100)

        params = {
            "size": size,
            "sort": "desc",
            "sort_type": "created_utc",
        }

        if self._has_query:
            params["q"] = self.query
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

            post_url = self._normalize_post_url(permalink)

            published_at = (
                datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
                if created_utc
                else None
            )

            if published_at:
                self._track_latest_published(published_at)

            scraped_count += 1
            yield self._make_post_item(
                title=title,
                url=post_url,
                author=author.strip() if author else "",
                content=selftext,
                score=item_data.get("score", 0),
                comment_count=item_data.get("num_comments", 0),
                published_at=published_at,
                thumbnail=item_data.get("thumbnail", "") or "",
                link_flair=item_data.get("link_flair_text", "") or "",
                domain=item_data.get("domain", "") or "",
                nsfw=item_data.get("over_18", False),
                is_self_post=item_data.get("is_self", False),
                permalink=permalink or "",
                query=query,
                strategy="pullpush",
                subreddit=item_data.get("subreddit", ""),
                post_id=item_data.get("id", ""),
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
                before=min_created_utc - 1,
                page=page + 1,
                scraped_count=scraped_count,
            )

    def _handle_pullpush_error(self, failure):
        self.logger.warning(
            f"PullPush request failed ({failure.value}), "
            "falling back to Reddit native scraper (no date filter)"
        )
        yield self._build_html_search_request()

    def parse_rss(self, response):
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

            if self._is_past_cutoff(published):
                self.logger.info(f"Skipping RSS post older than cutoff: {title}")
                filtered_count += 1
                continue

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
        """Fallback: old.reddit.com search results or subreddit listing (Strategy 2)."""
        query = response.meta.get("query")
        limit = response.meta["limit"]
        count = response.meta["count"]
        start_count = count

        if self._has_query:
            cards = response.css("div.search-result-link")
        else:
            cards = response.css("#siteTable div.thing[data-type='link']:not(.stickied)")

        if not cards:
            self.logger.warning(
                "CSS selectors found no results "
                "(HTML structure may have changed), trying LLM fallback"
            )
            yield from llm_fallback(self, response, PostItem)
            return

        cards_with_time = 0
        cards_skipped_old = 0

        for card in cards:
            if count >= limit:
                break

            if self._has_query:
                title_el = card.css("a.search-title")
            else:
                title_el = card.css("a.title")
            title = title_el.css("::text").get("")
            href = title_el.css("::attr(href)").get("")

            if not title or not href:
                continue

            post_time_str = card.css("time::attr(datetime)").get()
            if post_time_str:
                cards_with_time += 1
                if self._is_past_cutoff(post_time_str):
                    cards_skipped_old += 1
                    continue

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
                    f"All {cards_with_time} dated results older than cutoff, stopping"
                )
            elif cards_with_time == 0 and len(cards) > 0:
                self.logger.warning(
                    "No <time> tags found in results, "
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

    def _finalize_post_fields(self, post_fields, top_comments):
        """Extract internal meta keys, build metadata, return clean PostItem."""
        query_val = post_fields.pop("_query", None)
        subreddit_val = post_fields.pop("_subreddit", "")
        strategy_val = post_fields.pop("_strategy", "json_api")
        post_id_val = post_fields.pop("_post_id", "")
        post_fields["metadata"] = {
            "type": "detail",
            "strategy": strategy_val,
            "top_comments": top_comments,
            "query": query_val,
            "subreddit": subreddit_val,
            "id": post_id_val,
        }
        return PostItem(post_fields)

    def parse_comments_json(self, response):
        """Extract top comments from /comments/{id}.json and yield combined PostItem."""
        post_fields = dict(response.meta.get("_post_fields", {}))
        if not post_fields:
            self.logger.warning("Comments: missing _post_fields in meta, skipping")
            return

        try:
            data = json.loads(response.text)
        except (json.JSONDecodeError, ValueError):
            self.logger.warning(f"Comments JSON: invalid response for {post_fields.get('url')}")
            yield self._finalize_post_fields(post_fields, [])
            return

        if isinstance(data, list):
            if len(data) > 1:
                comment_listing = data[1]
            elif len(data) == 1:
                comment_listing = data[0]
            else:
                comment_listing = {}
        else:
            comment_listing = data

        children = comment_listing.get("data", {}).get("children", [])
        top_comments = []
        for c in children[:5]:
            if c.get("kind") != "t1":
                continue
            cd = c.get("data", {})
            if not cd.get("body"):
                continue
            top_comments.append({
                "author": cd.get("author", ""),
                "score": cd.get("score", 0),
                "body": cd.get("body", ""),
            })

        yield self._finalize_post_fields(post_fields, top_comments)

    def _handle_comments_error(self, failure):
        post_fields = failure.request.meta.get("_post_fields", {})
        if post_fields:
            post_fields = dict(post_fields)
            yield self._finalize_post_fields(post_fields, [])
        else:
            self.logger.debug(f"Comments request failed: {failure.value}")

    def _handle_post_error(self, failure):
        if failure.check(HttpError):
            response = failure.value.response
            if response.status == 429:
                retry_after = response.headers.get(b"Retry-After", b"unknown").decode()
                delay = self.settings.getint("DOWNLOAD_DELAY", 2)
                self.logger.warning(
                    f"Rate limited (429) on {failure.request.url}. "
                    f"Retry-After: {retry_after}. "
                    f"Current DOWNLOAD_DELAY: {delay}s. Consider increasing it."
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

    def _parse_post_from_json(self, response, json_data):
        """Extract post from JSON data embedded in response meta (API strategy)."""
        strategy = response.meta.get("strategy", "unknown")
        created_utc = json_data.get("created_utc", 0)

        if created_utc and self._is_past_cutoff(created_utc):
            self.logger.info(f"Stopping: post older than cutoff {self.cutoff_date}")
            return

        author = json_data.get("author", "").strip()
        if author in ("[deleted]",):
            self.logger.info(f"Skipping removed/deleted post: {response.url}")
            return

        title = json_data.get("title", "").strip()
        post_url = self._normalize_post_url(response.url)

        if not post_url or not title:
            self.logger.warning(f"Skipping post with no URL/title: {post_url}")
            return

        published_at = None
        if created_utc:
            published_at = datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
            self._track_latest_published(published_at)

        subreddit_name = json_data.get("subreddit", "")
        post_id = json_data.get("id", "")
        num_comments = json_data.get("num_comments", 0)

        if self.include_comments and post_id and num_comments > 0:
            comments_url = (
                f"https://old.reddit.com/comments/{post_id}.json"
                f"?limit=5&raw_json=1"
            )
            post_fields = {
                "site": self.site,
                "url": post_url,
                "title": title,
                "author": author,
                "content": json_data.get("selftext", ""),
                "score": json_data.get("score", 0),
                "comment_count": num_comments,
                "published_at": published_at,
                "thumbnail": json_data.get("thumbnail", ""),
                "link_flair": json_data.get("link_flair_text", ""),
                "domain": json_data.get("domain", ""),
                "nsfw": json_data.get("over_18", False),
                "is_self_post": json_data.get("is_self", False),
                "permalink": json_data.get("permalink", ""),
                "_query": response.meta.get("query"),
                "_subreddit": subreddit_name,
                "_strategy": strategy,
                "_post_id": post_id,
            }
            yield scrapy.Request(
                comments_url,
                callback=self.parse_comments_json,
                errback=self._handle_comments_error,
                meta={"_post_fields": post_fields},
                headers=_JSON_HEADERS,
            )
        else:
            yield self._make_post_item(
                title=title,
                url=post_url,
                author=author,
                content=json_data.get("selftext", ""),
                score=json_data.get("score", 0),
                comment_count=num_comments,
                published_at=published_at,
                thumbnail=json_data.get("thumbnail", ""),
                link_flair=json_data.get("link_flair_text", ""),
                domain=json_data.get("domain", ""),
                nsfw=json_data.get("over_18", False),
                is_self_post=json_data.get("is_self", False),
                permalink=json_data.get("permalink", ""),
                query=response.meta.get("query"),
                strategy=strategy,
                subreddit=subreddit_name,
                post_id=post_id,
            )

    def _parse_post_from_html(self, response):
        """Extract post from detail page via CSS scraping (HTML strategy)."""
        post_time_str = response.css("time::attr(datetime)").get()
        if self._is_past_cutoff(post_time_str):
            self.logger.info(f"Stopping: post {post_time_str} older than cutoff {self.cutoff_date}")
            return

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

        post_url = self._normalize_post_url(response.url)

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

        top_comments = [{"author": "", "body": top_comment[:500], "score": 0}] if top_comment else []

        post_id = ""
        url_parts_for_id = post_url.rstrip("/").split("/comments/")
        if len(url_parts_for_id) > 1:
            post_id = url_parts_for_id[1].split("/")[0]

        yield self._make_post_item(
            title=title,
            url=post_url,
            author=author.strip() if author else "",
            content=content,
            score=score,
            comment_count=comment_count,
            published_at=self._normalize_published_at(post_time_str),
            query=response.meta.get("query"),
            strategy=response.meta.get("strategy", "unknown"),
            subreddit=subreddit_name,
            post_id=post_id,
            top_comments=top_comments,
        )

    def parse_post_page(self, response):
        """Extract full post content from detail page. Dispatches to JSON or HTML path."""
        json_data = response.meta.get("_json_data", {})
        if json_data:
            yield from self._parse_post_from_json(response, json_data)
        else:
            yield from self._parse_post_from_html(response)
