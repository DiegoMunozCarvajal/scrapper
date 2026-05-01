from scrapper.middlewares import (
    ProxyRotationMiddleware,
    UARotationMiddleware,
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
        result = mw.process_request(request, FakeSpider())
        assert result is None
        assert "proxy" not in request.meta

    def test_sets_proxy_for_regular_request(self):
        mw = ProxyRotationMiddleware(proxy_list="http://proxy1:8080,http://proxy2:8080")
        request = FakeRequest()
        result = mw.process_request(request, FakeSpider())
        assert result is None
        assert "proxy" in request.meta
        assert request.meta["proxy"] in (
            "http://proxy1:8080",
            "http://proxy2:8080",
        )

    def test_sets_proxy_for_playwright_request(self):
        mw = ProxyRotationMiddleware(proxy_list="http://proxy1:8080")
        request = FakeRequest(meta={"playwright": True})
        result = mw.process_request(request, FakeSpider())
        assert result is None
        assert "playwright_context_kwargs" in request.meta
        assert request.meta["playwright_context_kwargs"]["proxy"] == {
            "server": "http://proxy1:8080"
        }


class TestUARotationMiddleware:
    def test_sets_ua_header(self):
        mw = UARotationMiddleware()
        request = FakeRequest()
        mw.process_request(request, FakeSpider())
        assert "User-Agent" in request.headers
        ua = request.headers["User-Agent"]
        assert isinstance(ua, str)
        assert len(ua) > 10

    def test_sets_ua_for_playwright_context(self):
        mw = UARotationMiddleware()
        request = FakeRequest(meta={"playwright": True})
        mw.process_request(request, FakeSpider())
        assert "playwright_context_kwargs" in request.meta
        assert "user_agent" in request.meta["playwright_context_kwargs"]
        assert isinstance(
            request.meta["playwright_context_kwargs"]["user_agent"], str
        )

    def test_ua_is_from_list(self):
        mw = UARotationMiddleware()
        request = FakeRequest()
        mw.process_request(request, FakeSpider())
        assert request.headers["User-Agent"] in USER_AGENTS
