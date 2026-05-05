from scrapy import Request
from scrapy.http import Response
from scrapy.settings import Settings
from scrapper.middlewares import (
    ProxyRotationMiddleware,
    UARotationMiddleware,
    RetryWithBackoffMiddleware,
)
from scrapper.utils import USER_AGENTS


class FakeLogger:
    def debug(self, msg):
        pass


class FakeSpider:
    name = "test_spider"
    logger = FakeLogger()


class FakeRequest:
    def __init__(self, meta=None, headers=None):
        self.meta = meta if meta is not None else {}
        self.headers = headers if headers is not None else {}


class TestProxyRotationMiddleware:
    def test_no_proxies_does_nothing(self):
        mw = ProxyRotationMiddleware(proxy_list="")
        request = FakeRequest()
        result = mw.process_request(request)
        assert result is None
        assert "proxy" not in request.meta

    def test_sets_proxy_for_regular_request(self):
        mw = ProxyRotationMiddleware(proxy_list="http://proxy1:8080,http://proxy2:8080")
        request = FakeRequest()
        result = mw.process_request(request)
        assert result is None
        assert "proxy" in request.meta
        assert request.meta["proxy"] in (
            "http://proxy1:8080",
            "http://proxy2:8080",
        )

    def test_sets_proxy_for_playwright_request(self):
        mw = ProxyRotationMiddleware(proxy_list="http://proxy1:8080")
        request = FakeRequest(meta={"playwright": True})
        result = mw.process_request(request)
        assert result is None
        assert "playwright_context_kwargs" in request.meta
        assert request.meta["playwright_context_kwargs"]["proxy"] == {
            "server": "http://proxy1:8080"
        }


class TestUARotationMiddleware:
    def test_sets_ua_header(self):
        mw = UARotationMiddleware()
        request = FakeRequest()
        mw.process_request(request)
        assert "User-Agent" in request.headers
        ua = request.headers["User-Agent"]
        assert isinstance(ua, str)
        assert len(ua) > 10

    def test_sets_ua_for_playwright_context(self):
        mw = UARotationMiddleware()
        request = FakeRequest(meta={"playwright": True})
        mw.process_request(request)
        assert "playwright_context_kwargs" in request.meta
        assert "user_agent" in request.meta["playwright_context_kwargs"]
        assert isinstance(
            request.meta["playwright_context_kwargs"]["user_agent"], str
        )

    def test_ua_is_from_list(self):
        mw = UARotationMiddleware()
        request = FakeRequest()
        mw.process_request(request)
        assert request.headers["User-Agent"] in USER_AGENTS


class TestRetryWithBackoffMiddleware:
    def test_retry_middleware_importable(self):
        assert RetryWithBackoffMiddleware is not None

    def test_retry_middleware_has_expected_methods(self):
        assert hasattr(RetryWithBackoffMiddleware, "process_response")
        assert hasattr(RetryWithBackoffMiddleware, "process_exception")


class FakeStats:
    def inc_value(self, *args, **kwargs):
        pass


class FakeCrawlerForRetry:
    settings = Settings({"RETRY_TIMES": 1, "RETRY_PRIORITY_ADJUST": -1})
    stats = FakeStats()


class FakeSpiderForRetry:
    crawler = FakeCrawlerForRetry()


def test_retry_signature_matches_scrapy_215():
    mw = RetryWithBackoffMiddleware(FakeCrawlerForRetry().settings)
    mw.crawler = FakeCrawlerForRetry()
    mw.crawler.spider = FakeSpiderForRetry()
    retry_request = mw._retry(Request("https://example.com"), "500 Internal Server Error")
    assert retry_request is not None
    assert retry_request.meta["retry_times"] == 1


def test_process_response_retries_on_500():
    mw = RetryWithBackoffMiddleware(FakeCrawlerForRetry().settings)
    mw.crawler = FakeCrawlerForRetry()
    mw.crawler.spider = FakeSpiderForRetry()
    request = Request("https://example.com")
    response = Response("https://example.com", status=500, request=request)

    result = mw.process_response(request=request, response=response, spider=mw.crawler.spider)

    assert isinstance(result, Request)
    assert result.meta["retry_times"] == 1
    assert result.meta["retry_delay"] == 1


def test_process_response_passes_through_200():
    mw = RetryWithBackoffMiddleware(FakeCrawlerForRetry().settings)
    mw.crawler = FakeCrawlerForRetry()
    mw.crawler.spider = FakeSpiderForRetry()
    request = Request("https://example.com")
    response = Response("https://example.com", status=200, request=request)

    result = mw.process_response(request=request, response=response, spider=mw.crawler.spider)

    assert result is response
