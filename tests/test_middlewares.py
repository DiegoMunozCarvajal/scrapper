from unittest.mock import MagicMock
from scrapper.middlewares import ProxyRotationMiddleware, UARotationMiddleware


class FakeSpider:
    name = "test_spider"


class TestProxyRotation:
    def test_init_with_list(self):
        mw = ProxyRotationMiddleware("http://proxy1.com,http://proxy2.com")
        assert len(mw.proxies) == 2

    def test_from_crawler(self):
        crawler = MagicMock()
        crawler.settings = {"PROXY_LIST": "http://proxy.com"}
        mw = ProxyRotationMiddleware.from_crawler(crawler)
        assert "http://proxy.com" in mw.proxies

    def test_init_empty(self):
        mw = ProxyRotationMiddleware("")
        assert len(mw.proxies) == 0


class TestUARotation:
    def test_has_user_agents(self):
        assert len(UARotationMiddleware.USER_AGENTS) > 0