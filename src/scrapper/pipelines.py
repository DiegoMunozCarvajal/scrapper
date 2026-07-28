from collections import defaultdict
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger
from scrapy.exceptions import DropItem, NotConfigured
from supabase import create_client

from .items import GenericItem, OddsItem, PostItem, TennisMatchItem


class DataQualityPipeline:
    """Flag items with quality issues. Report stats at close."""

    def __init__(self):
        self._stats = defaultdict(lambda: {"total": 0, "issues": 0})
        self._crawler = None

    @classmethod
    def from_crawler(cls, crawler):
        pipe = cls()
        pipe._crawler = crawler
        return pipe

    def process_item(self, item, spider):
        issues = self._validate(item)
        spider_name = spider.name
        self._stats[spider_name]["total"] += 1
        if issues:
            self._stats[spider_name]["issues"] += 1
            existing = item.get("quality_issues") or []
            item["quality_issues"] = existing + issues
        return item

    def close_spider(self, spider):
        spider_name = spider.name
        stats = self._stats.get(spider_name, {"total": 0, "issues": 0})
        if stats["total"] > 0:
            pct = stats["issues"] / stats["total"] * 100
            if pct > 30:
                logger.warning(
                    f"[{spider_name}] Data quality: {stats['issues']}/{stats['total']} "
                    f"items with issues ({pct:.1f}%)"
                )
            else:
                logger.info(
                    f"[{spider_name}] Data quality: {stats['issues']}/{stats['total']} "
                    f"items with issues ({pct:.1f}%)"
                )

    def _validate(self, item) -> list[str]:
        issues = []
        is_post = isinstance(item, PostItem)
        is_generic = isinstance(item, GenericItem)

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

        if is_generic:
            page_type = item.get("page_type")
            if page_type == "product":
                self._validate_price_rating(item, issues)
            elif page_type == "forum":
                self._validate_score(item, issues)
        elif not is_post:
            self._validate_price_rating(item, issues)
        else:
            score = item.get("score")
            if score is not None:
                try:
                    int(score)
                except (TypeError, ValueError):
                    issues.append("score_not_integer")

        return issues

    @staticmethod
    def _validate_price_rating(item, issues):
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

    @staticmethod
    def _validate_score(item, issues):
        score = item.get("score")
        if score is not None:
            try:
                int(score)
            except (TypeError, ValueError):
                issues.append("score_not_integer")


class ValidatePipeline:
    """Drop items missing URL or title."""

    def __init__(self):
        self._crawler = None

    @classmethod
    def from_crawler(cls, crawler):
        pipe = cls()
        pipe._crawler = crawler
        return pipe

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

    # Field allowlists per item type (not table name).
    # Table routing is by spider.name — see process_item().
    TABLE_FIELDS = {
        "posts": {
            "site",
            "url",
            "title",
            "author",
            "content",
            "score",
            "comment_count",
            "published_at",
            "link_flair",
            "domain",
            "nsfw",
            "is_self_post",
            "permalink",
            "quality_issues",
            "metadata",
            "scraped_at",
        },
        "products": {
            "site",
            "url",
            "title",
            "price",
            "currency",
            "rating",
            "review_count",
            "seller",
            "availability",
            "quality_issues",
            "metadata",
            "scraped_at",
        },
        "scraped_pages": {
            "site",
            "url",
            "page_type",
            "title",
            "content",
            "price",
            "currency",
            "rating",
            "review_count",
            "score",
            "author",
            "image_url",
            "category",
            "published_at",
            "quality_issues",
            "metadata",
            "scraped_at",
        },
        "odds": {
            "site",
            "url",
            "title",
            "sport",
            "league",
            "tournament",
            "match_date",
            "commence_time",
            "player_a",
            "player_b",
            "odds_a",
            "odds_b",
            "surface",
            "market_type",
            "quality_issues",
            "metadata",
            "scraped_at",
        },
        "tennis_match": {
            "url",
            "title",
            "winner_name",
            "loser_name",
            "score",
            "surface",
            "tourney_date",
            "tourney_level",
            "tourney_name",
            "round",
            "best_of",
            "source_url",
            "scraped_at",
        },
    }

    def __init__(self, supabase_url: str, supabase_key: str):
        self.client = create_client(supabase_url, supabase_key)

    @classmethod
    def from_crawler(cls, crawler):
        supabase_url = crawler.settings.get("SUPABASE_URL", "")
        supabase_key = crawler.settings.get("SUPABASE_KEY", "")
        if not supabase_url or not supabase_key:
            raise NotConfigured("SUPABASE_URL and SUPABASE_KEY are required for SupabasePipeline")
        return cls(supabase_url=supabase_url, supabase_key=supabase_key)

    def _serialize_item(self, item, item_type: str) -> dict:
        allowed = self.TABLE_FIELDS[item_type]
        return {key: value for key, value in dict(item).items() if key in allowed}

    def process_item(self, item, spider):
        if isinstance(item, GenericItem):
            item_type = "scraped_pages"
        elif isinstance(item, PostItem):
            item_type = "posts"
        elif isinstance(item, OddsItem):
            item_type = "odds"
        elif isinstance(item, TennisMatchItem):
            item_type = "tennis_match"
        else:
            item_type = "products"

        table = spider.name
        data = self._serialize_item(item, item_type)
        # Pick conflict key: use site+url when both present, else url only
        on_conflict = "site,url" if "site" in data else "url"
        for attempt in range(1, 4):
            try:
                self.client.table(table).upsert(data, on_conflict=on_conflict).execute()
                break
            except Exception as e:
                logger.warning(
                    f"Supabase upsert attempt {attempt}/3 failed for {item.get('url')}: {e}"
                )
                if attempt == 3:
                    logger.error(f"Supabase upsert FAILED after 3 retries for {item.get('url')}")
        return item

    def close_spider(self, spider):
        try:
            self.client.postgrest.session.close()
        except Exception:
            pass


class SQLiteOddsPipeline:
    """Write OddsItems to local SQLite database (odds_snapshots table)."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = None

    @classmethod
    def from_crawler(cls, crawler):
        db_path = crawler.settings.get(
            "SQLITE_ODDS_DB",
            str(Path.home() / "sports-betting-system/output/web_app.db"),
        )
        return cls(db_path=db_path)

    @property
    def conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        return self._conn

    def process_item(self, item, spider):
        if not isinstance(item, OddsItem):
            return item

        now = datetime.now(timezone.utc).isoformat()
        row_id = str(uuid.uuid4())

        data = {
            "id": row_id,
            "created_at": now,
            "source": "stake",
            "site": item.get("site", "stake"),
            "sport": item.get("sport", "tennis"),
            "player_a": item.get("player_a", ""),
            "player_b": item.get("player_b", ""),
            "stake_odds_a": item.get("odds_a"),
            "stake_odds_b": item.get("odds_b"),
            "ref_odds_a": None,
            "ref_odds_b": None,
            "tournament": item.get("tournament", ""),
            "surface": item.get("surface", ""),
            "match_date": item.get("match_date", ""),
            "commence_time": item.get("commence_time", item.get("match_date", "")),
            "captured_at": now,
            "validation_status": "raw",
            "raw_json": json.dumps(dict(item), ensure_ascii=False),
        }

        try:
            self.conn.execute(
                """INSERT OR REPLACE INTO odds_snapshots
                   (id, created_at, source, site, sport, player_a, player_b,
                    stake_odds_a, stake_odds_b, ref_odds_a, ref_odds_b,
                    tournament, surface, match_date, commence_time, captured_at,
                    validation_status, raw_json)
                   VALUES
                   (:id, :created_at, :source, :site, :sport, :player_a, :player_b,
                    :stake_odds_a, :stake_odds_b, :ref_odds_a, :ref_odds_b,
                    :tournament, :surface, :match_date, :commence_time, :captured_at,
                    :validation_status, :raw_json)""",
                data,
            )
            self.conn.commit()
        except Exception as e:
            logger.error(
                f"SQLite insert failed for {item.get('player_a')} vs {item.get('player_b')}: {e}"
            )
            raise DropItem(f"SQLite insert failed: {e}")

        return item

    def close_spider(self, spider):
        if self._conn:
            self._conn.close()
            self._conn = None


class SQLiteRedditPipeline:
    """Store PostItem objects in local SQLite database (reddit_posts.db)."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = None

    @classmethod
    def from_crawler(cls, crawler):
        db_path = crawler.settings.get("SQLITE_REDDIT_DB", "reddit_posts.db")
        return cls(db_path=db_path)

    @property
    def conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site TEXT,
                    url TEXT UNIQUE,
                    title TEXT,
                    author TEXT,
                    content TEXT,
                    score INTEGER DEFAULT 0,
                    comment_count INTEGER DEFAULT 0,
                    published_at TEXT,
                    link_flair TEXT,
                    domain TEXT,
                    nsfw INTEGER DEFAULT 0,
                    is_self_post INTEGER DEFAULT 0,
                    permalink TEXT,
                    quality_issues TEXT DEFAULT '[]',
                    metadata TEXT DEFAULT '{}',
                    scraped_at TEXT
                )"""
            )
            self._conn.commit()
        return self._conn

    def process_item(self, item, spider):
        if not isinstance(item, PostItem):
            return item

        data = dict(item)
        for f in ("quality_issues", "metadata"):
            if f in data and not isinstance(data[f], str):
                data[f] = json.dumps(data[f], ensure_ascii=False)

        columns = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data)

        try:
            self.conn.execute(
                f"INSERT OR REPLACE INTO posts ({columns}) VALUES ({placeholders})",
                data,
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"SQLiteRedditPipeline insert failed for {item.get('url')}: {e}")

        return item

    def close_spider(self, spider):
        if self._conn:
            self._conn.close()
            self._conn = None
