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


class TestPostItemNewFields:
    def test_thumbnail_field_default(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test")
        assert item.get("thumbnail") is None

    def test_thumbnail_field_when_set(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test", thumbnail="self")
        assert item["thumbnail"] == "self"

    def test_link_flair_field_default(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test")
        assert item.get("link_flair") is None

    def test_link_flair_field_when_set(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test", link_flair="Discussion")
        assert item["link_flair"] == "Discussion"

    def test_domain_field_default(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test")
        assert item.get("domain") is None

    def test_domain_field_when_set(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test", domain="github.com")
        assert item["domain"] == "github.com"

    def test_nsfw_field_default(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test")
        assert item["nsfw"] is False

    def test_nsfw_field_when_set(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test", nsfw=True)
        assert item["nsfw"] is True

    def test_is_self_post_field_default(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test")
        assert item["is_self_post"] is False

    def test_is_self_post_field_when_set(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test", is_self_post=True)
        assert item["is_self_post"] is True

    def test_permalink_field_default(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test")
        assert item.get("permalink") is None

    def test_permalink_field_when_set(self):
        item = PostItem(site="reddit", url="http://x.com/1", title="Test", permalink="/r/test/comments/abc/")
        assert item["permalink"] == "/r/test/comments/abc/"


class TestRedditJSONSearchFixture:
    def test_fixture_has_listing_structure(self, reddit_json_search):
        assert reddit_json_search["kind"] == "Listing"
        assert "children" in reddit_json_search["data"]

    def test_fixture_has_t3_posts(self, reddit_json_search):
        children = reddit_json_search["data"]["children"]
        t3_children = [c for c in children if c["kind"] == "t3"]
        assert len(t3_children) >= 3

    def test_fixture_has_after_cursor(self, reddit_json_search):
        assert "after" in reddit_json_search["data"]
        assert reddit_json_search["data"]["after"] is not None

    def test_build_post_item_from_fixture_data(self, reddit_json_search):
        children = reddit_json_search["data"]["children"]
        t3_posts = [c for c in children if c["kind"] == "t3"]
        first = t3_posts[0]["data"]

        item = PostItem(
            site="reddit",
            url=f"https://old.reddit.com{first['permalink']}",
            title=first["title"],
            author=first["author"],
            content=first.get("selftext", ""),
            score=first["score"],
            comment_count=first["num_comments"],
            published_at="2026-05-05T00:00:00Z",
            thumbnail=first.get("thumbnail", ""),
            link_flair=first.get("link_flair_text", ""),
            domain=first.get("domain", ""),
            nsfw=first.get("over_18", False),
            is_self_post=first.get("is_self", False),
            permalink=first.get("permalink", ""),
            metadata={
                "strategy": "json_api",
                "query": "python",
                "top_comments": [],
                "subreddit": first.get("subreddit", ""),
                "id": first.get("id", ""),
            },
        )
        assert item["title"] == "Is Python fast enough for backends in 2026?"
        assert item["score"] == 245
        assert item["comment_count"] == 67
        assert item["is_self_post"] is True
        assert item["thumbnail"] == "self"
        assert item["link_flair"] == "Discussion"
        assert item["metadata"]["strategy"] == "json_api"

    def test_fixture_nsfw_post(self, reddit_json_search):
        children = reddit_json_search["data"]["children"]
        t3_posts = [c for c in children if c["kind"] == "t3"]
        nsfw_post = [p for p in t3_posts if p["data"].get("over_18")]
        assert len(nsfw_post) == 1
        assert nsfw_post[0]["data"]["title"] == "NSFW: Adult content discussion thread"
        assert nsfw_post[0]["data"]["over_18"] is True
        assert nsfw_post[0]["data"]["thumbnail"] == "nsfw"

    def test_build_post_item_from_link_post(self, reddit_json_search):
        children = reddit_json_search["data"]["children"]
        t3_posts = [c for c in children if c["kind"] == "t3"]
        link_post = [p for p in t3_posts if not p["data"].get("is_self")]
        assert len(link_post) == 1

        post_data = link_post[0]["data"]
        item = PostItem(
            site="reddit",
            url=post_data["url"],
            title=post_data["title"],
            author=post_data["author"],
            score=post_data["score"],
            comment_count=post_data["num_comments"],
            is_self_post=False,
            domain=post_data.get("domain", ""),
            permalink=post_data.get("permalink", ""),
            metadata={"strategy": "json_api"},
        )
        assert item["is_self_post"] is False
        assert item["domain"] == "github.com"
        assert item["title"] == "Show HN: My new framework beats Next.js and Remix"


class TestRedditCommentsFixture:
    def test_fixture_has_two_listings(self, reddit_json_comments):
        assert len(reddit_json_comments) == 2
        assert reddit_json_comments[0]["kind"] == "Listing"
        assert reddit_json_comments[1]["kind"] == "Listing"

    def test_fixture_has_t1_comments(self, reddit_json_comments):
        comments_listing = reddit_json_comments[1]
        children = comments_listing["data"]["children"]
        t1_children = [c for c in children if c["kind"] == "t1"]
        assert len(t1_children) == 3

    def test_fixture_top_comment_fields(self, reddit_json_comments):
        comments_listing = reddit_json_comments[1]
        first_comment = comments_listing["data"]["children"][0]["data"]
        assert "author" in first_comment
        assert "score" in first_comment
        assert "body" in first_comment
