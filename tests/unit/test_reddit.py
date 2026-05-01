from unittest.mock import MagicMock, patch
from scrapper.spiders.reddit import RedditSpider


class TestRedditSpider:
    def _make_spider(self):
        with patch.object(RedditSpider, "_load_cutoff_date", return_value=None):
            spider = RedditSpider()
        spider.cutoff_date = None
        return spider

    def test_parse_post_page_extracts_fields(self):
        spider = self._make_spider()

        response = MagicMock()
        response.url = "https://old.reddit.com/r/test/comments/abc/test_post/"
        response.meta = {}

        def mock_css(selector):
            mock = MagicMock()
            if selector == "time::attr(datetime)":
                mock.get.return_value = "2026-04-15T10:30:00Z"
            elif selector == "div.md *::text":
                mock.getall.return_value = ["Post content here"]
            elif selector == "div.commentarea div.md":
                first = MagicMock()
                first.css.return_value.getall.return_value = ["Top comment"]
                return [first]
            elif selector == "div.score.unvoted::text":
                mock.get.return_value = "42"
            elif selector == "a.comments::text":
                mock.get.return_value = "1,234 comments"
            elif selector == "a.author::text":
                mock.get.return_value = "u_testuser"
            elif selector == "a.title::text":
                mock.get.return_value = "Test Post Title"
            return mock

        response.css.side_effect = mock_css

        results = list(spider.parse_post_page(response))
        assert len(results) == 1
        item = results[0]
        assert item["score"] == 42
        assert item["comment_count"] == 1234
        assert item["title"] == "Test Post Title"
        assert item["author"] == "u_testuser"
        assert item["published_at"] == "2026-04-15T10:30:00Z"

    def test_parse_post_page_handles_missing_score(self):
        spider = self._make_spider()

        response = MagicMock()
        response.url = "https://old.reddit.com/r/test/comments/abc/test_post/"
        response.meta = {}

        def mock_css(selector):
            mock = MagicMock()
            if selector == "time::attr(datetime)":
                mock.get.return_value = None
            elif selector == "div.md *::text":
                mock.getall.return_value = []
            elif selector == "div.commentarea div.md":
                return []
            elif selector == "div.score.unvoted::text":
                mock.get.return_value = None
            elif selector == "a.comments::text":
                mock.get.return_value = None
            elif selector == "a.author::text":
                mock.get.return_value = None
            elif selector == "a.title::text":
                mock.get.return_value = "Test Title"
            return mock

        response.css.side_effect = mock_css

        results = list(spider.parse_post_page(response))
        assert len(results) == 1
        item = results[0]
        assert item["score"] == 0
        assert item["comment_count"] == 0
        assert item["author"] == ""
