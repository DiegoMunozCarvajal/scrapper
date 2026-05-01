import feedparser

from scrapper.items import PostItem


class TestRedditRSSParsing:
    def test_feedparser_parses_fixture(self, reddit_rss):
        feed = feedparser.parse(reddit_rss)
        assert len(feed.entries) == 2
        assert feed.entries[0]["title"] == "Python 3.13 released"
        assert "abc123" in feed.entries[0]["link"]

    def test_entries_have_required_fields(self, reddit_rss):
        feed = feedparser.parse(reddit_rss)
        for entry in feed.entries:
            assert entry.get("title"), f"Missing title in {entry}"
            assert entry.get("link"), f"Missing link in {entry}"
            assert entry.get("author"), f"Missing author in {entry}"


class TestRedditPostItemFromRSS:
    def test_build_post_item_from_rss_entry(self, reddit_rss):
        feed = feedparser.parse(reddit_rss)
        entry = feed.entries[0]

        item = PostItem(
            site="reddit",
            url=entry.get("link", ""),
            title=entry.get("title", ""),
            author=entry.get("author", ""),
            content="",
            score=0,
            comment_count=0,
            published_at=entry.get("updated", ""),
            metadata={"query": "python", "source": "rss"},
        )

        assert item["site"] == "reddit"
        assert item["url"] == entry["link"]
        assert item["title"] == "Python 3.13 released"
        assert item["author"] == "u_python_dev"
        assert item["published_at"] == "2026-04-15T10:30:00Z"


class TestPostItemFields:
    def test_score_is_integer_default(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test")
        assert item["score"] == 0
        assert isinstance(item["score"], int)

    def test_comment_count_is_integer_default(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test")
        assert item["comment_count"] == 0
        assert isinstance(item["comment_count"], int)

    def test_published_at_optional(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test")
        assert item.get("published_at") is None

    def test_published_at_when_set(self):
        item = PostItem(
            site="reddit",
            url="http://x.com/1",
            title="Test",
            published_at="2026-04-15T10:30:00Z",
        )
        assert item["published_at"] == "2026-04-15T10:30:00Z"

    def test_metadata_stores_query(self):
        item = PostItem(
            site="reddit",
            url="http://x.com/1",
            title="Test",
            metadata={"query": "python"},
        )
        assert item["metadata"]["query"] == "python"
