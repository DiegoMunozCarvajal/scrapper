import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import scrapy
from scrapy.http import HtmlResponse

from scrapper.spiders.reddit import RedditSpider


class TestRedditSpider:
    def _make_spider(self):
        with patch.object(RedditSpider, "_load_cutoff_date", return_value=None):
            spider = RedditSpider()
        spider.cutoff_date = None
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
        assert item["published_at"] == "2026-04-15T10:30:00Z"
        assert item["metadata"]["subreddit"] == "test"

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
        with patch("scrapper.spiders.reddit.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 4, 10, 49, 30, tzinfo=timezone.utc)
            mock_dt.timezone = timezone
            assert spider._calculate_time_filter() == "hour"

    def test_calculate_time_filter_day(self):
        spider = self._make_spider()
        spider.cutoff_date = "2026-05-03T10:00:00+00:00"
        with patch("scrapper.spiders.reddit.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 4, 10, 0, 0, tzinfo=timezone.utc)
            mock_dt.timezone = timezone
            assert spider._calculate_time_filter() == "day"

    def test_calculate_time_filter_week(self):
        spider = self._make_spider()
        spider.cutoff_date = "2026-04-28T10:00:00+00:00"
        with patch("scrapper.spiders.reddit.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 4, 10, 0, 0, tzinfo=timezone.utc)
            mock_dt.timezone = timezone
            assert spider._calculate_time_filter() == "week"

    def test_build_json_precheck_request(self):
        spider = self._make_spider()
        spider.query = "python"
        req = spider._build_json_precheck_request()
        assert "search.json" in req.url
        assert "python" in req.url
        assert "sort=new" in req.url
        assert "t=all" in req.url

    def test_check_json_posts_for_new_content_no_cutoff(self):
        spider = self._make_spider()
        spider.cutoff_date = None
        posts = [{"data": {"created_utc": 100}}]
        assert spider._check_json_posts_for_new_content(posts) is True

    def test_check_json_posts_for_new_content_all_old(self):
        spider = self._make_spider()
        spider.cutoff_date = "2026-05-04T00:00:00+00:00"
        posts = [
            {"data": {"created_utc": 1746326400.0}},  # May 4, 2026 00:00:00 UTC
        ]
        # created_utc equals cutoff, not newer
        assert spider._check_json_posts_for_new_content(posts) is False

    def test_check_json_posts_for_new_content_has_new(self):
        spider = self._make_spider()
        spider.cutoff_date = "2026-05-01T00:00:00+00:00"
        # May 6, 2026 UTC: ~1778112000
        posts = [
            {"data": {"created_utc": 1778112000.0}},
        ]
        assert spider._check_json_posts_for_new_content(posts) is True

    def test_json_precheck_error_falls_back(self):
        spider = self._make_spider()
        spider.query = "test"
        spider.settings = MagicMock()
        spider.settings.getbool.return_value = False
        from twisted.python.failure import Failure
        from scrapy import Request

        failure = Failure(Exception("network error"), Request("http://test"))
        results = list(spider._json_precheck_error(failure))
        assert len(results) == 1
        assert results[0].callback == spider.parse

    def test_parse_skips_old_cards_at_listing_level(self):
        spider = self._make_spider()
        spider.cutoff_date = "2026-05-04T00:00:00+00:00"

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

    def test_build_html_search_request_with_subreddit(self):
        spider = self._make_spider()
        spider.query = "async"
        spider.limit = 5
        spider.subreddit = "learnpython"
        req = spider._build_html_search_request()
        assert "old.reddit.com/r/learnpython/search" in req.url
        assert "restrict_sr=on" in req.url
        assert "async" in req.url

    def test_build_json_precheck_request_with_subreddit(self):
        spider = self._make_spider()
        spider.query = "async"
        spider.subreddit = "learnpython"
        req = spider._build_json_precheck_request()
        assert "search.json" in req.url
        assert "r/learnpython" in req.url
        assert "restrict_sr=on" in req.url
        assert "async" in req.url

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
