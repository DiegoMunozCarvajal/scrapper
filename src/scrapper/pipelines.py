from scrapy.exceptions import DropItem
from supabase import create_client

from .items import PostItem


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