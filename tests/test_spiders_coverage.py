from unittest.mock import MagicMock
from scrapper.spiders.reddit import RedditSpider
from scrapper.spiders.amazon import AmazonSpider
from scrapper.spiders.mercadolibre import MercadoLibreSpider
from scrapper.spiders.hotmart import HotmartSpider
from scrapper.spiders.quora import QuoraSpider
from scrapper.items import PostItem, ProductItem


class FakeResponse:
    def __init__(self, url, meta=None):
        self.url = url
        self.meta = meta or {}
        self._css_result = {}

    def css(self, selector):
        results = self._css_result.get(selector, [])
        m = MagicMock()
        m.getall.return_value = results
        m.get.return_value = results[0] if results else ""
        return m

    def follow(self, url, callback=None, meta=None):
        m = MagicMock()
        m.url = url
        m.callback = callback
        m.meta = meta
        return m


class TestSpiderAttributes:
    def test_reddit_has_parse_post(self):
        spider = RedditSpider()
        assert hasattr(spider, "parse_post")

    def test_reddit_custom_settings(self):
        spider = RedditSpider()
        assert spider.custom_settings.get("DOWNLOAD_HANDLERS") == {}

    def test_amazon_has_parse_product(self):
        spider = AmazonSpider()
        assert hasattr(spider, "parse_product")

    def test_amazon_custom_settings(self):
        spider = AmazonSpider()
        assert spider.custom_settings.get("PLAYWRIGHT_BROWSER_TYPE") == "chromium"

    def test_mercadolibre_name(self):
        assert MercadoLibreSpider().name == "mercadolibre"

    def test_hotmart_name(self):
        assert HotmartSpider().name == "hotmart"

    def test_quora_name(self):
        assert QuoraSpider().name == "quora"

    def test_quora_playwright_meta(self):
        spider = QuoraSpider()
        requests = list(spider.start_requests())
        assert requests[0].meta.get("playwright") is True


class TestSpiderParseReturns:
    def test_reddit_parse_is_generator(self):
        spider = RedditSpider()
        response = FakeResponse("http://test.com", {"query": "test", "limit": 1, "count": 0})
        response._css_result = {"a.search-title": []}
        result = spider.parse(response)
        assert hasattr(result, "__iter__")

    def test_amazon_parse_is_generator(self):
        spider = AmazonSpider()
        response = FakeResponse("http://test.com", {"query": "test", "limit": 1, "count": 0})
        response._css_result = {"h2": []}
        result = spider.parse(response)
        assert hasattr(result, "__iter__")

    def test_mercadolibre_parse_is_generator(self):
        spider = MercadoLibreSpider()
        response = FakeResponse("http://test.com", {"query": "test", "limit": 1, "count": 0})
        response._css_result = {"li.ui-search-layout__item": []}
        result = spider.parse(response)
        assert hasattr(result, "__iter__")

    def test_hotmart_parse_is_generator(self):
        spider = HotmartSpider()
        response = FakeResponse("http://test.com", {"query": "test", "limit": 1, "count": 0})
        response._css_result = {'[class*="product"]': []}
        result = spider.parse(response)
        assert hasattr(result, "__iter__")

    def test_quora_parse_is_generator(self):
        spider = QuoraSpider()
        response = FakeResponse("http://test.com", {"query": "test", "limit": 1, "count": 0})
        response._css_result = {'[class*="qu-"]': []}
        result = spider.parse(response)
        assert hasattr(result, "__iter__")


class TestDetailParsesReturnItems:
    def test_reddit_parse_post_returns_postitem(self):
        spider = RedditSpider()
        response = FakeResponse("http://test.com", {"query": "test", "limit": 1, "count": 0})
        response._css_result = {"div.md *::text": ["c"], "a.title::text": ["t"], "a.author::text": ["u"]}
        items = list(spider.parse_post(response))
        assert len(items) > 0 and isinstance(items[0], PostItem)

    def test_amazon_parse_product_returns_productitem(self):
        spider = AmazonSpider()
        response = FakeResponse("http://test.com", {"query": "test", "limit": 1, "count": 0})
        response._css_result = {"#title::text": ["t"], "#sellerName *::text": ["s"], "#availability *::text": ["a"]}
        items = list(spider.parse_product(response))
        assert len(items) > 0 and isinstance(items[0], ProductItem)