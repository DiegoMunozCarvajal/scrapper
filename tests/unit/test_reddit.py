import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import scrapy
from scrapy.http import HtmlResponse

from scrapper.items import PostItem
from scrapper.spiders.reddit import RedditSpider


class TestRedditSpider:
    def _make_spider(self):
        with patch.object(RedditSpider, "_load_cutoff_date", return_value=None):
            spider = RedditSpider()
        spider.cutoff_date = None
        spider.settings = MagicMock()
        spider.settings.getbool.return_value = False
        return spider

    def _make_response(self, body, url="https://old.reddit.com/r/test/comments/abc/test_post/"):
        from scrapy import Request
        request = Request(url=url, meta={"query": "test"})
        return HtmlResponse(url=url, body=body.encode(), encoding="utf-8", request=request)

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
        assert item["published_at"] == "2026-04-15T10:30:00+00:00"
        assert item["metadata"]["subreddit"] == "test"
        assert isinstance(item["metadata"]["top_comments"], list)

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
            elif selector == "div.score::text":
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

    def test_parse_post_page_extracts_content(self):
        spider = self._make_spider()
        url = "https://old.reddit.com/r/Python/comments/abc123/test_post/"
        response = self._make_response(
            body="<html><body><a class='title'>Test Title</a><div class='md'><p>Post body content here.</p></div></body></html>",
            url=url,
        )
        result = list(spider.parse_post_page(response))
        assert len(result) == 1
        item = result[0]
        assert item["content"] == "Post body content here."
        assert item["url"] == url

    def test_parse_post_page_no_content(self):
        spider = self._make_spider()
        url = "https://old.reddit.com/r/Python/comments/abc123/test_post/"
        response = self._make_response(body="<html><body><a class='title'>Test Title</a></body></html>", url=url)
        result = list(spider.parse_post_page(response))
        assert len(result) == 1
        item = result[0]
        assert item["content"] == ""

    def test_cutoff_date_filters_old_posts(self):
        spider = self._make_spider()
        spider.cutoff_date = "2026-05-03T00:00:00+00:00"
        spider._cutoff_dt = datetime(2026, 5, 3, tzinfo=timezone.utc)
        post_date = datetime(2026, 5, 2, tzinfo=timezone.utc)
        html = f'<html><body><time datetime="{post_date.isoformat()}">old</time><a class="title">Title</a><a class="author">Author</a></body></html>'
        response = self._make_response(url="https://old.reddit.com/r/Python/comments/abc123/title/", body=html)
        items = list(spider.parse_post_page(response))
        assert len(items) == 0

    def test_track_latest_published_newer_replaces(self):
        spider = self._make_spider()
        spider._track_latest_published("2026-01-01T00:00:00Z")
        spider._track_latest_published("2026-05-01T00:00:00Z")
        assert spider._latest_published == "2026-05-01T00:00:00Z"

    def test_track_latest_published_older_ignored(self):
        spider = self._make_spider()
        spider._track_latest_published("2026-05-01T00:00:00Z")
        spider._track_latest_published("2026-01-01T00:00:00Z")
        assert spider._latest_published == "2026-05-01T00:00:00Z"

    def test_build_html_search_request(self):
        spider = self._make_spider()
        spider.query = "python"
        spider.limit = 5
        req = spider._build_html_search_request()
        assert "old.reddit.com/search" in req.url
        assert "python" in req.url
        assert req.meta["query"] == "python"
        assert req.meta["limit"] == 5

    def test_build_html_search_request_with_params(self):
        spider = self._make_spider()
        req = spider._build_html_search_request(query="javascript", limit=3)
        assert "javascript" in req.url
        assert req.meta["query"] == "javascript"
        assert req.meta["limit"] == 3

    def test_handle_post_error_429(self):
        spider = self._make_spider()
        from scrapy.spidermiddlewares.httperror import HttpError
        from scrapy.http import Response

        fake_response = Response(
            url="https://old.reddit.com/r/test/comments/abc",
            status=429,
            headers={b"Retry-After": b"120"},
        )
        failure = MagicMock()
        failure.check.return_value = True
        failure.value.response = fake_response
        failure.request.url = "https://old.reddit.com/r/test/comments/abc"

        spider._handle_post_error(failure)
        failure.check.assert_called_once_with(HttpError)

    def test_handle_pagination_error_503(self):
        spider = self._make_spider()
        from scrapy.spidermiddlewares.httperror import HttpError
        from scrapy.http import Response

        fake_response = Response(
            url="https://old.reddit.com/search?q=test&after=t3_123",
            status=503,
        )
        failure = MagicMock()
        failure.check.return_value = True
        failure.value.response = fake_response
        failure.request.url = fake_response.url

        spider._handle_pagination_error(failure)
        failure.check.assert_called_once_with(HttpError)

    def test_calculate_time_filter_no_cutoff(self):
        spider = self._make_spider()
        spider.cutoff_date = None
        assert spider._calculate_time_filter() == "all"

    def test_calculate_time_filter_hour(self):
        spider = self._make_spider()
        spider.cutoff_date = "2026-05-04T10:49:00+00:00"
        spider._cutoff_dt = datetime(2026, 5, 4, 10, 49, 0, tzinfo=timezone.utc)
        with patch("scrapper.spiders.reddit.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 4, 10, 49, 30, tzinfo=timezone.utc)
            mock_dt.timezone = timezone
            assert spider._calculate_time_filter() == "hour"

    def test_calculate_time_filter_day(self):
        spider = self._make_spider()
        spider.cutoff_date = "2026-05-03T10:00:00+00:00"
        spider._cutoff_dt = datetime(2026, 5, 3, 10, 0, 0, tzinfo=timezone.utc)
        with patch("scrapper.spiders.reddit.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 4, 10, 0, 0, tzinfo=timezone.utc)
            mock_dt.timezone = timezone
            assert spider._calculate_time_filter() == "day"

    def test_calculate_time_filter_week(self):
        spider = self._make_spider()
        spider.cutoff_date = "2026-04-28T10:00:00+00:00"
        spider._cutoff_dt = datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc)
        with patch("scrapper.spiders.reddit.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 4, 10, 0, 0, tzinfo=timezone.utc)
            mock_dt.timezone = timezone
            assert spider._calculate_time_filter() == "week"

    def test_build_json_request(self):
        spider = self._make_spider()
        spider.query = "python"
        spider.limit = 30
        req = spider._build_json_request()
        assert "search.json" in req.url
        assert "python" in req.url
        assert "sort=new" in req.url
        assert "t=all" in req.url
        assert "raw_json=1" in req.url
        assert "limit=30" in req.url
        assert req.meta["strategy"] == "json_api"
        assert req.callback == spider.parse_json_results

    def test_build_json_request_limit_capped(self):
        spider = self._make_spider()
        spider.limit = 200
        req = spider._build_json_request()
        assert "limit=100" in req.url

    def test_build_json_request_with_after(self):
        spider = self._make_spider()
        spider.query = "python"
        req = spider._build_json_request(after="t3_abc123", count=25)
        assert "after=t3_abc123" in req.url
        assert "count=25" in req.url
        assert req.meta["count"] == 25

    def test_build_json_request_no_query(self):
        spider = self._make_spider()
        spider.subreddit = "Python"
        spider.query = None
        spider._has_query = False
        req = spider._build_json_request()
        assert "old.reddit.com/r/Python/new.json" in req.url
        assert "raw_json=1" in req.url

    def test_build_json_request_with_sort(self):
        spider = self._make_spider()
        spider.subreddit = "Python"
        spider.query = None
        spider._has_query = False
        spider.sort = "top"
        req = spider._build_json_request()
        assert "old.reddit.com/r/Python/top.json" in req.url

    def test_build_json_request_with_time_filter(self):
        spider = self._make_spider()
        spider.subreddit = "Python"
        spider.query = None
        spider._has_query = False
        spider.time_filter = "week"
        req = spider._build_json_request()
        assert "t=week" in req.url

    def test_json_request_error_falls_back(self):
        spider = self._make_spider()
        spider.query = "test"
        spider.settings = MagicMock()
        spider.settings.getbool.return_value = False
        from twisted.python.failure import Failure
        from scrapy import Request

        failure = Failure(Exception("network error"), Request("http://test"))
        results = list(spider._json_request_error(failure))
        assert len(results) == 1
        assert results[0].callback == spider.parse

    def test_parse_skips_old_cards_at_listing_level(self):
        spider = self._make_spider()
        spider.cutoff_date = "2026-05-04T00:00:00+00:00"
        spider._cutoff_dt = datetime(2026, 5, 4, tzinfo=timezone.utc)

        def make_card(title, href, posted_at):
            card = MagicMock()

            def card_css(selector):
                m = MagicMock()
                if selector == "a.search-title":
                    title_el = MagicMock()

                    def title_css(inner):
                        inner_m = MagicMock()
                        if inner == "::text":
                            inner_m.get.return_value = title
                        elif inner == "::attr(href)":
                            inner_m.get.return_value = href
                        return inner_m

                    title_el.css.side_effect = title_css
                    return title_el
                elif selector == "time::attr(datetime)":
                    m.get.return_value = posted_at
                return m

            card.css.side_effect = card_css
            return card

        old_card = make_card("Old Post", "/r/test/comments/old/", "2026-05-03T00:00:00+00:00")
        new_card = make_card("New Post", "/r/test/comments/new/", "2026-05-04T12:00:00+00:00")

        response = MagicMock()
        response.url = "https://old.reddit.com/search?q=test&sort=new"
        response.meta = {"query": "test", "limit": 5, "count": 0}

        def response_css(selector):
            if selector == "div.search-result-link":
                return [old_card, new_card]
            m = MagicMock()
            m.get.return_value = None
            return m

        response.css.side_effect = response_css
        response.follow.side_effect = lambda url, **kw: MagicMock(url=url, meta=kw.get("meta", {}))

        results = list(spider.parse(response))
        assert len(results) == 1
        assert "/r/test/comments/new/" in results[0].url

    def test_parse_all_old_cards_stops_gracefully(self):
        spider = self._make_spider()
        spider.cutoff_date = "2026-05-04T00:00:00+00:00"
        spider._cutoff_dt = datetime(2026, 5, 4, tzinfo=timezone.utc)

        def make_card(title, href, posted_at):
            card = MagicMock()

            def card_css(selector):
                m = MagicMock()
                if selector == "a.search-title":
                    title_el = MagicMock()

                    def title_css(inner):
                        inner_m = MagicMock()
                        if inner == "::text":
                            inner_m.get.return_value = title
                        elif inner == "::attr(href)":
                            inner_m.get.return_value = href
                        return inner_m

                    title_el.css.side_effect = title_css
                    return title_el
                elif selector == "time::attr(datetime)":
                    m.get.return_value = posted_at
                return m

            card.css.side_effect = card_css
            return card

        old_card = make_card("Old Post", "/r/test/comments/old/", "2026-05-03T00:00:00+00:00")

        response = MagicMock()
        response.url = "https://old.reddit.com/search?q=test"
        response.meta = {"query": "test", "limit": 5, "count": 0}

        def response_css(selector):
            if selector == "div.search-result-link":
                return [old_card]
            m = MagicMock()
            m.get.return_value = None
            return m

        response.css.side_effect = response_css

        results = list(spider.parse(response))
        assert len(results) == 0

    def test_date_str_to_epoch(self):
        spider = self._make_spider()
        ts = spider._date_str_to_epoch("2026-04-15")
        expected = datetime(2026, 4, 15, tzinfo=timezone.utc).timestamp()
        assert ts == expected

    def test_date_str_to_epoch_end_of_day(self):
        spider = self._make_spider()
        ts = spider._date_str_to_epoch("2026-04-15", end_of_day=True)
        expected = datetime(2026, 4, 15, 23, 59, 59, tzinfo=timezone.utc).timestamp()
        assert ts == expected

    def test_date_str_to_epoch_invalid(self):
        spider = self._make_spider()
        assert spider._date_str_to_epoch("2026-13-01") == 0

    def test_build_pullpush_request_basic(self):
        spider = self._make_spider()
        spider.query = "python"
        spider.limit = 30
        req = spider._build_pullpush_request()
        assert "api.pullpush.io" in req.url
        assert "q=python" in req.url
        assert "size=30" in req.url
        assert "sort=desc" in req.url
        assert req.meta["strategy"] == "pullpush"
        assert req.meta["pullpush_page"] == 1
        assert req.meta["scraped_count"] == 0

    def test_build_pullpush_request_with_dates(self):
        spider = self._make_spider()
        spider.query = "test"
        req = spider._build_pullpush_request(
            date_from="2026-01-01", date_to="2026-03-31"
        )
        assert "api.pullpush.io" in req.url
        assert "after=" in req.url
        assert "before=" in req.url
        assert req.meta["date_from"] == "2026-01-01"
        assert req.meta["date_to"] == "2026-03-31"

    def test_build_pullpush_request_pagination(self):
        spider = self._make_spider()
        req = spider._build_pullpush_request(
            date_from="2026-01-01", date_to="2026-03-31",
            before=1746496400.0, page=2, scraped_count=50
        )
        assert "before=1746496400" in req.url
        assert req.meta["pullpush_page"] == 2
        assert req.meta["scraped_count"] == 50

    def test_parse_pullpush_maps_fields(self):
        spider = self._make_spider()
        response = MagicMock()
        response.meta = {
            "query": "test", "limit": 10, "strategy": "pullpush",
            "pullpush_page": 1, "pullpush_size": 25,
            "date_from": None, "date_to": None, "scraped_count": 0,
        }
        response.text = json.dumps({
            "data": [{
                "title": "Test Post",
                "selftext": "Post body",
                "author": "test_user",
                "score": 42,
                "num_comments": 7,
                "created_utc": 1746496400.0,
                "permalink": "/r/test/comments/abc123/test_post/",
                "subreddit": "test",
                "id": "abc123",
            }]
        })
        items = list(spider.parse_pullpush(response))
        assert len(items) == 1
        item = items[0]
        assert item["title"] == "Test Post"
        assert item["content"] == "Post body"
        assert item["author"] == "test_user"
        assert item["score"] == 42
        assert item["comment_count"] == 7
        assert item["published_at"] is not None
        assert "old.reddit.com" in item["url"]
        assert item["metadata"]["strategy"] == "pullpush"
        assert item["metadata"]["subreddit"] == "test"

    def test_parse_pullpush_skips_removed(self):
        spider = self._make_spider()
        response = MagicMock()
        response.meta = {
            "query": "test", "limit": 10, "pullpush_page": 1,
            "pullpush_size": 25, "date_from": None, "date_to": None,
            "scraped_count": 0,
        }
        response.text = json.dumps({
            "data": [
                {"title": "Removed", "selftext": "[removed]", "permalink": "/r/t/comments/a/", "created_utc": 1},
                {"title": "Deleted", "selftext": "[deleted]", "permalink": "/r/t/comments/b/", "created_utc": 2},
                {"title": "Good", "selftext": "OK", "permalink": "/r/t/comments/c/", "author": "u", "created_utc": 3},
            ]
        })
        items = list(spider.parse_pullpush(response))
        assert len(items) == 1
        assert items[0]["title"] == "Good"

    def test_parse_pullpush_skips_no_title(self):
        spider = self._make_spider()
        response = MagicMock()
        response.meta = {
            "query": "test", "limit": 10, "pullpush_page": 1,
            "pullpush_size": 25, "date_from": None, "date_to": None,
            "scraped_count": 0,
        }
        response.text = json.dumps({
            "data": [
                {"title": "Good", "selftext": "OK", "permalink": "/r/t/comments/c/", "author": "u", "created_utc": 1},
                {"title": "", "selftext": "No title", "permalink": "/r/t/comments/d/", "author": "x", "created_utc": 2},
            ]
        })
        items = list(spider.parse_pullpush(response))
        assert len(items) == 1
        assert items[0]["title"] == "Good"

    def test_parse_pullpush_stops_at_limit(self):
        spider = self._make_spider()
        response = MagicMock()
        response.meta = {
            "query": "test", "limit": 2, "pullpush_page": 1,
            "pullpush_size": 25, "date_from": None, "date_to": None,
            "scraped_count": 0,
        }
        posts = []
        for i in range(5):
            posts.append({
                "title": f"Post {i}",
                "selftext": f"Body {i}",
                "permalink": f"/r/t/comments/{i}/",
                "author": f"u{i}",
                "created_utc": 1746496400.0 + i,
                "score": 1, "num_comments": 0,
            })
        response.text = json.dumps({"data": posts})
        items = list(spider.parse_pullpush(response))
        assert len(items) == 2

    def test_parse_pullpush_pagination_continues(self):
        spider = self._make_spider()
        response = MagicMock()
        response.meta = {
            "query": "test", "limit": 100, "pullpush_page": 1,
            "pullpush_size": 25, "date_from": None, "date_to": None,
            "scraped_count": 0,
        }
        posts = []
        for i in range(25):
            posts.append({
                "title": f"Post {i}",
                "selftext": f"Body {i}",
                "permalink": f"/r/t/comments/{i}/",
                "author": f"u{i}",
                "created_utc": 1746496400.0 + i,
                "score": 1, "num_comments": 0,
            })
        response.text = json.dumps({"data": posts})
        items = list(spider.parse_pullpush(response))
        # 25 posts + 1 pagination request = 26 items
        assert len(items) == 26
        # Last item should be pagination request
        assert isinstance(items[-1], scrapy.Request)

    def test_parse_pullpush_pagination_stops_at_date_from(self):
        spider = self._make_spider()
        response = MagicMock()
        response.meta = {
            "query": "test", "limit": 100, "pullpush_page": 1,
            "pullpush_size": 25,
            "date_from": "2026-05-01",
            "date_to": None,
            "scraped_count": 0,
        }
        # All posts are from May 1, 2026 → at or before date_from boundary
        may1_epoch = int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp())
        posts = []
        for i in range(25):
            posts.append({
                "title": f"Post {i}",
                "selftext": f"Body {i}",
                "permalink": f"/r/t/comments/{i}/",
                "author": f"u{i}",
                "created_utc": may1_epoch + i,
                "score": 1, "num_comments": 0,
            })
        response.text = json.dumps({"data": posts})
        items = list(spider.parse_pullpush(response))
        # Last item should NOT be a pagination request
        assert all(not isinstance(it, scrapy.Request) for it in items)

    def test_parse_pullpush_invalid_json(self):
        spider = self._make_spider()
        response = MagicMock()
        response.meta = {
            "query": "test", "limit": 10, "pullpush_page": 1,
            "pullpush_size": 25, "date_from": None, "date_to": None,
            "scraped_count": 0,
        }
        response.text = "not json"
        items = list(spider.parse_pullpush(response))
        assert len(items) == 0

    def test_parse_pullpush_tracks_latest_published(self):
        spider = self._make_spider()
        response = MagicMock()
        response.meta = {
            "query": "test", "limit": 10, "pullpush_page": 1,
            "pullpush_size": 25, "date_from": None, "date_to": None,
            "scraped_count": 0,
        }
        response.text = json.dumps({
            "data": [{
                "title": "Newest", "selftext": "Body",
                "permalink": "/r/t/comments/a/", "author": "u",
                "created_utc": 1746500000.0, "score": 1, "num_comments": 0,
            }]
        })
        list(spider.parse_pullpush(response))
        assert spider._latest_published is not None

    def test_parse_pullpush_pagination_uses_minus_one(self):
        spider = self._make_spider()
        response = MagicMock()
        response.meta = {
            "query": "test", "limit": 100, "pullpush_page": 1,
            "pullpush_size": 25, "date_from": None, "date_to": None,
            "scraped_count": 0,
        }
        posts = []
        for i in range(25):
            posts.append({
                "title": f"Post {i}", "selftext": f"Body {i}",
                "permalink": f"/r/t/comments/{i}/", "author": f"u{i}",
                "created_utc": 1746403200.0 + i,
                "score": 1, "num_comments": 0,
            })
        response.text = json.dumps({"data": posts})
        items = list(spider.parse_pullpush(response))
        # Find the pagination request
        req = next(it for it in items if isinstance(it, scrapy.Request))
        assert "before=1746403199" in req.url

    def test_pullpush_error_falls_back(self):
        spider = self._make_spider()
        spider.query = "test"
        spider.limit = 10
        spider.settings = MagicMock()
        spider.settings.getbool.return_value = False
        from twisted.python.failure import Failure

        failure = Failure(Exception("connection refused"), scrapy.Request("http://test"))
        results = list(spider._handle_pullpush_error(failure))
        assert len(results) == 1
        assert results[0].callback == spider.parse

    def test_build_pullpush_request_size_capped(self):
        spider = self._make_spider()
        spider.limit = 200
        req = spider._build_pullpush_request()
        assert "size=100" in req.url

    def test_build_pullpush_request_scraped_count_propagated(self):
        spider = self._make_spider()
        req = spider._build_pullpush_request(
            date_from="2026-01-01", date_to="2026-03-31",
            before=1700000000.0, page=3, scraped_count=75
        )
        assert req.meta["scraped_count"] == 75
        assert req.meta["pullpush_page"] == 3
        assert "before=1700000000" in req.url

    def test_cache_key_global(self):
        spider = self._make_spider()
        spider.query = "python"
        spider.subreddit = None
        assert spider._cache_key == "python"

    def test_cache_key_with_subreddit(self):
        spider = self._make_spider()
        spider.query = "python"
        spider.subreddit = "learnpython"
        assert spider._cache_key == "learnpython:python"

    def test_cache_key_sort_only_no_subreddit(self):
        spider = self._make_spider()
        spider.subreddit = None
        spider.query = None
        spider._has_query = False
        spider.sort = "top"
        assert spider._cache_key == "sort=top"

    def test_build_html_search_request_with_subreddit(self):
        spider = self._make_spider()
        spider.query = "async"
        spider.limit = 5
        spider.subreddit = "learnpython"
        req = spider._build_html_search_request()
        assert "old.reddit.com/r/learnpython/search" in req.url
        assert "restrict_sr=on" in req.url
        assert "async" in req.url

    def test_build_json_request_with_subreddit(self):
        spider = self._make_spider()
        spider.query = "async"
        spider.subreddit = "learnpython"
        spider.limit = 25
        req = spider._build_json_request()
        assert "search.json" in req.url
        assert "r/learnpython" in req.url
        assert "restrict_sr=on" in req.url
        assert "async" in req.url
        assert "raw_json=1" in req.url

    def test_build_rss_request_with_subreddit(self):
        spider = self._make_spider()
        spider.query = "async"
        spider.subreddit = "learnpython"
        req = spider._build_rss_request()
        assert "r/learnpython/search.rss" in req.url
        assert "restrict_sr=on" in req.url
        assert "async" in req.url

    def test_build_rss_request_global(self):
        spider = self._make_spider()
        spider.query = "python"
        spider.subreddit = None
        req = spider._build_rss_request()
        assert "reddit.com/search.rss" in req.url
        assert "restrict_sr=on" not in req.url

    def test_build_pullpush_request_with_subreddit(self):
        spider = self._make_spider()
        spider.query = "python"
        spider.subreddit = "learnpython"
        req = spider._build_pullpush_request()
        assert "api.pullpush.io" in req.url
        assert "subreddit=learnpython" in req.url
        assert "q=python" in req.url

    def test_build_pullpush_request_without_subreddit(self):
        spider = self._make_spider()
        spider.query = "python"
        spider.subreddit = None
        req = spider._build_pullpush_request()
        assert "subreddit=" not in req.url

    def test_parse_post_page_extracts_subreddit_from_url(self):
        spider = self._make_spider()

        response = MagicMock()
        response.url = "https://old.reddit.com/r/learnpython/comments/abc/async_question/"
        response.meta = {}

        def mock_css(selector):
            mock = MagicMock()
            if selector == "time::attr(datetime)":
                mock.get.return_value = "2026-05-04T10:30:00Z"
            elif selector == "div.md *::text":
                mock.getall.return_value = ["How do I use async?"]
            elif selector == "div.commentarea div.md":
                first = MagicMock()
                first.css.return_value.getall.return_value = ["Use asyncio.run()"]
                return [first]
            elif selector == "div.score.unvoted::text":
                mock.get.return_value = "15"
            elif selector == "a.comments::text":
                mock.get.return_value = "3 comments"
            elif selector == "a.author::text":
                mock.get.return_value = "u_learner"
            elif selector == "a.title::text":
                mock.get.return_value = "Async Question"
            return mock

        response.css.side_effect = mock_css

        results = list(spider.parse_post_page(response))
        assert len(results) == 1
        item = results[0]
        assert item["metadata"]["subreddit"] == "learnpython"

    def test_parse_post_page_no_subreddit_in_url(self):
        spider = self._make_spider()

        response = MagicMock()
        response.url = "https://old.reddit.com/comments/abc/nosub/"
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
            elif selector == "div.score::text":
                mock.get.return_value = None
            elif selector == "a.comments::text":
                mock.get.return_value = None
            elif selector == "a.author::text":
                mock.get.return_value = None
            elif selector == "a.title::text":
                mock.get.return_value = "Title"
            return mock

        response.css.side_effect = mock_css

        results = list(spider.parse_post_page(response))
        assert len(results) == 1
        assert results[0]["metadata"]["subreddit"] == ""

    def test_load_local_cutoff_date_with_subreddit_key(self):
        with patch.object(RedditSpider, "_load_cutoff_date", return_value=None):
            spider = RedditSpider()
        spider.subreddit = "learnpython"
        spider.query = "async"
        spider.settings = MagicMock()
        spider.settings.get.return_value = "/tmp/test_metrics"

        cutoff_data = {"learnpython:async": "2026-05-01T00:00:00Z"}
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.mkdir"), \
             patch("builtins.open", create=True), \
             patch("portalocker.lock"), \
             patch("portalocker.unlock"), \
             patch("json.load", return_value=cutoff_data):
            spider._load_local_cutoff_date()
            assert spider.cutoff_date == "2026-05-01T00:00:00Z"

    def test_save_cutoff_cache_with_subreddit_key(self):
        with patch.object(RedditSpider, "_load_cutoff_date", return_value=None):
            spider = RedditSpider()
        spider.subreddit = "learnpython"
        spider.query = "async"
        spider._cutoff_cache_path = MagicMock()
        spider._cutoff_cache_path.parent = MagicMock()
        spider._latest_published = "2026-05-04T00:00:00Z"

        with patch("builtins.open", create=True), \
             patch("portalocker.lock"), \
             patch("portalocker.unlock"), \
             patch("json.load", return_value={}), \
             patch("json.dump") as mock_dump:
            spider._save_cutoff_cache()
            written_data = mock_dump.call_args[0][0]
            assert "learnpython:async" in written_data
            assert written_data["learnpython:async"] == "2026-05-04T00:00:00Z"

    # ── parse_json_results tests ──────────────────────

    def _make_json_search_response(self, data=None, after=None):
        if data is None:
            data = {}
        response = MagicMock()
        response.meta = {"query": "test", "limit": 10, "count": 0, "strategy": "json_api"}
        response.text = json.dumps({
            "kind": "Listing",
            "data": {
                "after": after,
                "before": None,
                "children": data.get("children", []),
            },
        })
        response.url = "https://old.reddit.com/search.json?q=test"
        return response

    def _make_json_post_child(self, **overrides):
        base = {
            "kind": "t3",
            "data": {
                "title": "Test Post",
                "permalink": "/r/test/comments/abc123/test_post/",
                "author": "u_tester",
                "score": 42,
                "num_comments": 7,
                "created_utc": 1746403200.0,
                "selftext": "Post content here.",
                "selftext_html": "<p>Post content</p>",
                "thumbnail": "self",
                "link_flair_text": "Discussion",
                "domain": "self.test",
                "over_18": False,
                "is_self": True,
                "subreddit": "test",
                "id": "abc123",
                "name": "t3_abc123",
            },
        }
        base["data"].update(overrides)
        return base

    def test_parse_json_results_self_post_emitted_directly(self):
        spider = self._make_spider()
        post_data = {
            "title": "Self Post",
            "permalink": "/r/test/comments/abc/self/",
            "author": "u_author",
            "score": 15,
            "num_comments": 3,
            "created_utc": 1746403200.0,
            "selftext": "Content",
            "thumbnail": "self",
            "link_flair_text": "Discussion",
            "domain": "self.test",
            "over_18": False,
            "is_self": True,
            "subreddit": "test",
            "id": "abc",
        }
        response = self._make_json_search_response({
            "children": [{"kind": "t3", "data": post_data}],
        })
        items = list(spider.parse_json_results(response))
        assert len(items) == 1
        item = items[0]
        assert isinstance(item, PostItem)
        assert item["title"] == "Self Post"
        assert item["content"] == "Content"
        assert item["is_self_post"] is True
        assert item["thumbnail"] == "self"
        assert item["link_flair"] == "Discussion"
        assert item["domain"] == "self.test"
        assert item["nsfw"] is False
        assert item["permalink"] == "/r/test/comments/abc/self/"
        assert item["metadata"]["strategy"] == "json_api"

    def test_parse_json_results_link_post_follows_detail(self):
        spider = self._make_spider()
        post_data = {
            "title": "Link Post",
            "permalink": "/r/test/comments/abc/link/",
            "author": "u_author",
            "score": 25,
            "num_comments": 5,
            "created_utc": 1746403200.0,
            "selftext": "",
            "is_self": False,
            "subreddit": "test",
            "id": "abc",
        }
        response = self._make_json_search_response({
            "children": [{"kind": "t3", "data": post_data}],
        })

        def mock_follow(url, **kw):
            mock = MagicMock()
            mock.url = url
            mock.meta = kw.get("meta", {})
            mock.callback = kw.get("callback")
            return mock

        response.follow.side_effect = mock_follow

        items = list(spider.parse_json_results(response))
        assert len(items) == 1
        assert items[0].callback == spider.parse_post_page

    def test_parse_json_results_nsfw_exclude(self):
        spider = self._make_spider()
        spider.nsfw = "exclude"
        response = self._make_json_search_response({
            "children": [
                self._make_json_post_child(title="SFW", over_18=False),
                self._make_json_post_child(title="NSFW", over_18=True, id="nsfw1", name="t3_nsfw1"),
            ],
        })
        items = list(spider.parse_json_results(response))
        assert len(items) == 1
        assert items[0]["title"] == "SFW"

    def test_parse_json_results_nsfw_only(self):
        spider = self._make_spider()
        spider.nsfw = "only"
        response = self._make_json_search_response({
            "children": [
                self._make_json_post_child(title="SFW", over_18=False),
                self._make_json_post_child(title="NSFW", over_18=True, id="nsfw1", name="t3_nsfw1"),
            ],
        })
        items = list(spider.parse_json_results(response))
        assert len(items) == 1
        assert items[0]["title"] == "NSFW"

    def test_parse_json_results_cutoff_filters_old(self):
        spider = self._make_spider()
        spider.cutoff_date = "2026-05-04T00:00:00+00:00"
        spider._cutoff_dt = datetime(2026, 5, 4, tzinfo=timezone.utc)
        cutoff_ts = spider._cutoff_dt.timestamp()
        new_epoch = cutoff_ts + 3600
        old_epoch = cutoff_ts - 3600
        response = self._make_json_search_response({
            "children": [
                self._make_json_post_child(title="New", created_utc=new_epoch, id="n", name="t3_n"),
                self._make_json_post_child(title="Old", created_utc=old_epoch, id="o", name="t3_o"),
            ],
        })
        items = list(spider.parse_json_results(response))
        assert len(items) == 1
        assert items[0]["title"] == "New"

    def test_parse_json_results_skips_removed(self):
        spider = self._make_spider()
        response = self._make_json_search_response({
            "children": [
                self._make_json_post_child(title="[removed]", id="r", name="t3_r"),
                self._make_json_post_child(title="Good", id="g", name="t3_g"),
            ],
        })
        items = list(spider.parse_json_results(response))
        assert len(items) == 1
        assert items[0]["title"] == "Good"

    def test_parse_json_results_skips_no_title(self):
        spider = self._make_spider()
        response = self._make_json_search_response({
            "children": [
                self._make_json_post_child(title="", id="nt", name="t3_nt"),
                self._make_json_post_child(title="Good", id="g", name="t3_g"),
            ],
        })
        items = list(spider.parse_json_results(response))
        assert len(items) == 1
        assert items[0]["title"] == "Good"

    def test_parse_json_results_skips_t1_comments(self):
        spider = self._make_spider()
        response = self._make_json_search_response({
            "children": [
                {"kind": "t1", "data": {"body": "comment", "id": "c1", "name": "t1_c1"}},
                self._make_json_post_child(title="Good", id="g", name="t3_g"),
            ],
        })
        items = list(spider.parse_json_results(response))
        assert len(items) == 1
        assert items[0]["title"] == "Good"

    def test_parse_json_results_no_posts(self):
        spider = self._make_spider()
        response = self._make_json_search_response({"children": []})
        items = list(spider.parse_json_results(response))
        assert len(items) == 0

    def test_parse_json_results_invalid_json(self):
        spider = self._make_spider()
        response = MagicMock()
        response.meta = {"query": "test", "limit": 10, "count": 0}
        response.text = "not json"
        items = list(spider.parse_json_results(response))
        assert len(items) >= 1
        assert isinstance(items[0], scrapy.Request)

    def test_parse_json_results_pagination(self):
        spider = self._make_spider()
        response = self._make_json_search_response(
            {"children": [self._make_json_post_child()]},
            after="t3_next_page",
        )
        items = list(spider.parse_json_results(response))
        assert len(items) == 2
        assert isinstance(items[0], PostItem)
        assert isinstance(items[1], scrapy.Request)

    def test_parse_json_results_pagination_stops_at_limit(self):
        spider = self._make_spider()
        children = []
        for i in range(5):
            children.append(self._make_json_post_child(
                title=f"Post {i}", id=f"p{i}", name=f"t3_p{i}"
            ))
        response = self._make_json_search_response(
            {"children": children}, after="t3_next",
        )
        response.meta["limit"] = 3
        items = list(spider.parse_json_results(response))
        assert len(items) == 3

    def test_parse_json_results_falls_back_on_empty(self):
        spider = self._make_spider()
        spider.settings.getbool.return_value = False
        response = self._make_json_search_response({
            "children": [
                self._make_json_post_child(title="[removed]", id="r", name="t3_r"),
            ],
        })
        items = list(spider.parse_json_results(response))
        assert len(items) == 1
        assert isinstance(items[0], scrapy.Request)

    def test_build_post_item_from_json_all_fields(self):
        spider = self._make_spider()
        post_data = {
            "title": "Full Post",
            "permalink": "/r/test/comments/abc/full/",
            "author": "u_tester",
            "score": 100,
            "num_comments": 50,
            "created_utc": 1746403200.0,
            "selftext": "Full content",
            "thumbnail": "self",
            "link_flair_text": "Flair",
            "domain": "self.test",
            "over_18": False,
            "is_self": True,
            "subreddit": "test",
            "id": "abc",
        }
        item = spider._build_post_item_from_json(post_data, "test_query")
        assert item["title"] == "Full Post"
        assert item["score"] == 100
        assert item["comment_count"] == 50
        assert item["author"] == "u_tester"
        assert item["content"] == "Full content"
        assert item["thumbnail"] == "self"
        assert item["link_flair"] == "Flair"
        assert item["domain"] == "self.test"
        assert item["nsfw"] is False
        assert item["is_self_post"] is True
        assert item["permalink"] == "/r/test/comments/abc/full/"
        assert item["metadata"]["strategy"] == "json_api"
        assert item["metadata"]["query"] == "test_query"
        assert item["metadata"]["subreddit"] == "test"
        assert item["metadata"]["id"] == "abc"
        assert item["published_at"] is not None

    def test_build_post_item_from_json_tracks_latest(self):
        spider = self._make_spider()
        post_data = {
            "title": "Newest",
            "permalink": "/r/test/comments/n/new/",
            "author": "u_tester",
            "score": 1,
            "num_comments": 1,
            "created_utc": 1746403200.0,
            "selftext": "",
            "subreddit": "test",
            "id": "n",
        }
        spider._build_post_item_from_json(post_data, "q")
        assert spider._latest_published is not None

    # ── parse_comments_json tests ──────────────────────

    def _make_post_fields_meta(self, **overrides):
        base = {
            "site": "reddit",
            "url": "https://old.reddit.com/r/test/comments/abc/",
            "title": "Test Post",
            "author": "u_tester",
            "content": "Post body",
            "score": 42,
            "comment_count": 7,
            "published_at": "2026-05-05T00:00:00Z",
            "thumbnail": "self",
            "link_flair": "Discussion",
            "domain": "self.test",
            "nsfw": False,
            "is_self_post": True,
            "permalink": "/r/test/comments/abc/",
            "_query": "test",
            "_subreddit": "test",
            "_strategy": "json_api",
            "_post_id": "abc",
        }
        base.update(overrides)
        return base

    def test_parse_comments_json_extracts_top_comments(self):
        spider = self._make_spider()
        response = MagicMock()
        response.meta = {"_post_fields": self._make_post_fields_meta()}
        response.text = json.dumps([
            {"kind": "Listing", "data": {"children": []}},
            {"kind": "Listing", "data": {"children": [
                {"kind": "t1", "data": {"author": "u_c1", "score": 50, "body": "First"}},
                {"kind": "t1", "data": {"author": "u_c2", "score": 30, "body": "Second"}},
            ]}},
        ])
        items = list(spider.parse_comments_json(response))
        assert len(items) == 1
        item = items[0]
        assert item["metadata"]["type"] == "detail"
        assert item["metadata"]["strategy"] == "json_api"
        assert item["metadata"]["id"] == "abc"
        assert item["metadata"]["query"] == "test"
        comments = item["metadata"]["top_comments"]
        assert len(comments) == 2
        assert comments[0]["author"] == "u_c1"
        assert comments[0]["score"] == 50
        assert comments[0]["body"] == "First"
        assert item["comment_count"] == 7
        assert item["title"] == "Test Post"
        assert item["content"] == "Post body"

    def test_parse_comments_json_skips_t3(self):
        spider = self._make_spider()
        response = MagicMock()
        response.meta = {"_post_fields": self._make_post_fields_meta()}
        response.text = json.dumps([
            {"kind": "Listing", "data": {"children": []}},
            {"kind": "Listing", "data": {"children": [
                {"kind": "t3", "data": {"title": "not a comment"}},
                {"kind": "t1", "data": {"author": "u_c1", "score": 1, "body": "Real"}},
            ]}},
        ])
        items = list(spider.parse_comments_json(response))
        assert len(items[0]["metadata"]["top_comments"]) == 1

    def test_parse_comments_json_invalid(self):
        spider = self._make_spider()
        response = MagicMock()
        response.meta = {"_post_fields": self._make_post_fields_meta()}
        response.text = "not json"
        items = list(spider.parse_comments_json(response))
        assert len(items) == 1
        assert items[0]["title"] == "Test Post"

    def test_parse_comments_json_empty(self):
        spider = self._make_spider()
        response = MagicMock()
        response.meta = {"_post_fields": self._make_post_fields_meta()}
        response.text = json.dumps([
            {"kind": "Listing", "data": {"children": []}},
            {"kind": "Listing", "data": {"children": []}},
        ])
        items = list(spider.parse_comments_json(response))
        assert len(items) == 1
        assert items[0]["metadata"]["top_comments"] == []

    def test_parse_comments_json_missing_meta(self):
        spider = self._make_spider()
        response = MagicMock()
        response.meta = {}
        response.text = json.dumps([{}])
        items = list(spider.parse_comments_json(response))
        assert len(items) == 0

    # ── nsfw param tests ────────────────────────────

    def test_include_comments_param_default(self):
        with patch.object(RedditSpider, "_load_cutoff_date", return_value=None):
            spider = RedditSpider()
        assert spider.include_comments is False

    def test_include_comments_param_true(self):
        with patch.object(RedditSpider, "_load_cutoff_date", return_value=None):
            spider = RedditSpider()
        setattr(spider, "include_comments", True)
        assert spider.include_comments is True

    # ── _is_past_cutoff tests ─────────────────────────

    def test_is_past_cutoff_with_timestamp(self):
        spider = self._make_spider()
        spider._cutoff_dt = datetime(2026, 5, 3, tzinfo=timezone.utc)
        # May 3 00:00 UTC = 1777766400.0, May 5 00:00 UTC = 1777939200.0
        assert spider._is_past_cutoff(1777766400.0) is True  # May 3 00:00 UTC (on cutoff)
        assert spider._is_past_cutoff(1777939200.0) is False  # May 5 00:00 UTC (after cutoff)

    def test_is_past_cutoff_with_string(self):
        spider = self._make_spider()
        spider._cutoff_dt = datetime(2026, 5, 3, tzinfo=timezone.utc)
        assert spider._is_past_cutoff("2026-05-02T00:00:00Z") is True
        assert spider._is_past_cutoff("2026-05-04T00:00:00Z") is False

    def test_is_past_cutoff_no_cutoff(self):
        spider = self._make_spider()
        spider._cutoff_dt = None
        assert spider._is_past_cutoff("2020-01-01T00:00:00Z") is False

    def test_is_past_cutoff_invalid_input(self):
        spider = self._make_spider()
        spider._cutoff_dt = datetime(2026, 5, 3, tzinfo=timezone.utc)
        assert spider._is_past_cutoff("not-a-date") is False
        assert spider._is_past_cutoff(None) is False

    def test_calculate_time_filter_uses_cached_dt(self):
        spider = self._make_spider()
        spider._cutoff_dt = datetime(2026, 5, 3, 10, 0, 0, tzinfo=timezone.utc)
        with patch("scrapper.spiders.reddit.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 4, 10, 0, 0, tzinfo=timezone.utc)
            mock_dt.timezone = timezone
            assert spider._calculate_time_filter() == "day"

    def test_normalize_post_url_absolute(self):
        spider = self._make_spider()
        assert spider._normalize_post_url("https://old.reddit.com/r/test/comments/abc") == \
            "https://old.reddit.com/r/test/comments/abc"

    def test_normalize_post_url_relative(self):
        spider = self._make_spider()
        assert spider._normalize_post_url("/r/test/comments/abc") == \
            "https://old.reddit.com/r/test/comments/abc"

    def test_normalize_post_url_protocol_relative(self):
        spider = self._make_spider()
        assert spider._normalize_post_url("//old.reddit.com/r/test/comments/abc") == \
            "https://old.reddit.com/r/test/comments/abc"

    def test_normalize_post_url_empty(self):
        spider = self._make_spider()
        assert spider._normalize_post_url("") == ""

    def test_normalize_published_at_with_tz(self):
        spider = self._make_spider()
        result = spider._normalize_published_at("2026-05-04T10:30:00Z")
        assert result == "2026-05-04T10:30:00+00:00"

    def test_normalize_published_at_without_tz(self):
        spider = self._make_spider()
        result = spider._normalize_published_at("2026-05-04T10:30:00")
        assert "+00:00" in result

    def test_normalize_published_at_none(self):
        spider = self._make_spider()
        assert spider._normalize_published_at(None) is None
        assert spider._normalize_published_at("") is None

    def test_normalize_published_at_invalid(self):
        spider = self._make_spider()
        result = spider._normalize_published_at("not-a-date")
        assert result == "not-a-date"
