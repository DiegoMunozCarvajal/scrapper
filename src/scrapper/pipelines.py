from collections import defaultdict
from urllib.parse import urlparse

from loguru import logger
from scrapy.exceptions import DropItem
from supabase import create_client

from .items import PostItem


class DataQualityPipeline:
    """Flag items with quality issues. Report stats at close."""

    def __init__(self):
        self._stats = defaultdict(lambda: {"total": 0, "issues": 0})

    def process_item(self, item, spider):
        issues = self._validate(item)
        self._stats[spider.name]["total"] += 1
        if issues:
            self._stats[spider.name]["issues"] += 1
            item._values.setdefault("quality_issues", []).extend(issues)
        return item

    def close_spider(self, spider):
        stats = self._stats.get(spider.name, {"total": 0, "issues": 0})
        if stats["total"] > 0:
            pct = stats["issues"] / stats["total"] * 100
            if pct > 30:
                logger.warning(
                    f"[{spider.name}] Data quality: {stats['issues']}/{stats['total']} "
                    f"items with issues ({pct:.1f}%)"
                )
            else:
                logger.info(
                    f"[{spider.name}] Data quality: {stats['issues']}/{stats['total']} "
                    f"items with issues ({pct:.1f}%)"
                )

    def _validate(self, item) -> list[str]:
        issues = []
        is_post = isinstance(item, PostItem)

        url = item.get("url", "")
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                issues.append("invalid_url_scheme")
        else:
            issues.append("missing_url")

        title = item.get("title", "")
        if title and len(title.strip()) < 3:
            issues.append("title_too_short")

        content = item.get("content")
        if content is not None and len(str(content)) < 10:
            issues.append("content_too_short")

        if not is_post:
            price = item.get("price")
            if price is not None:
                try:
                    if float(price) <= 0:
                        issues.append("price_invalid")
                except (TypeError, ValueError):
                    issues.append("price_not_numeric")

            rating = item.get("rating")
            if rating is not None:
                try:
                    r = float(rating)
                    if r < 0 or r > 5:
                        issues.append("rating_out_of_range")
                except (TypeError, ValueError):
                    issues.append("rating_not_numeric")
        else:
            score = item.get("score")
            if score is not None:
                try:
                    int(score)
                except (TypeError, ValueError):
                    issues.append("score_not_integer")

        return issues


class ValidatePipeline:
    """Drop items missing URL or title."""

    def process_item(self, item, spider):
        url = item.get("url")
        if not url:
            raise DropItem(f"Missing URL in item from {spider.name}")
        title = item.get("title")
        if not title:
            raise DropItem(f"Missing title in item from {spider.name}: {url}")
        return item


class DedupInMemoryPipeline:
    """Drop duplicate URLs within the same crawl run."""

    def __init__(self):
        self.seen: set[str] = set()

    def process_item(self, item, spider):
        url = item.get("url", "")
        if url in self.seen:
            raise DropItem(f"Duplicate URL in run: {url}")
        self.seen.add(url)
        return item


class SupabasePipeline:
    """Upsert items into Supabase Postgres tables."""

    def __init__(self, supabase_url: str, supabase_key: str):
        self.client = create_client(supabase_url, supabase_key)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            supabase_url=crawler.settings.get("SUPABASE_URL", ""),
            supabase_key=crawler.settings.get("SUPABASE_KEY", ""),
        )

    def process_item(self, item, spider):
        table = "posts" if isinstance(item, PostItem) else "products"
        data = dict(item)
        try:
            self.client.table(table).upsert(data, on_conflict="site,url").execute()
        except Exception as e:
            spider.logger.error(f"Supabase upsert failed for {item.get('url')}: {e}")
        return item