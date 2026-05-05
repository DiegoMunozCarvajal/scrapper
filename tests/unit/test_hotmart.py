import json

from scrapy import Request
from scrapy.http import TextResponse
from scrapper.spiders.hotmart import HotmartSpider, _parse_price, _parse_review_count


class TestHotmartSpider:
    def test_spider_importable(self):
        assert HotmartSpider is not None

    def test_spider_name(self):
        spider = HotmartSpider()
        assert spider.name == "hotmart"

    def test_parse_price_dollar(self):
        result = _parse_price("$29.99")
        assert result == 29.99

    def test_parse_price_brazilian_real(self):
        result = _parse_price("R$ 19,90")
        assert result == 19.90

    def test_parse_price_none(self):
        result = _parse_price(None)
        assert result is None

    def test_parse_price_empty(self):
        result = _parse_price("")
        assert result is None

    def test_parse_review_count(self):
        result = _parse_review_count("(1234 avaliações)")
        assert result == 1234

    def test_parse_review_count_none(self):
        result = _parse_review_count(None)
        assert result == 0


def test_review_count_with_thousands_separator():
    assert _parse_review_count("1,234 reviews") == 1234
    assert _parse_review_count("1.234 avaliações") == 1234


def test_start_request_installs_api_interceptor_before_navigation():
    from scrapper.spiders.hotmart import HotmartSpider

    spider = HotmartSpider()
    spider._api_endpoint_cache = None
    req = next(spider.start_requests())
    assert req.meta["playwright"] is True
    assert callable(req.meta["playwright_page_init_callback"])


def test_parse_api_carries_scraped_count_across_pages():
    spider = HotmartSpider()
    spider._api_endpoint_cache = "https://api.hotmart.test/search"
    body = json.dumps({
        "data": {
            "search": {
                "pagination": {"totalPages": 2},
                "items": [
                    {"name": "A", "url": "https://example.com/a"},
                    {"name": "B", "url": "https://example.com/b"},
                ],
            }
        }
    })
    request = Request(
        "https://api.hotmart.test/search?q=x&page=1&size=5",
        meta={"query": "x", "limit": 5, "page": 1, "strategy": "api", "scraped_count": 1},
    )
    response = TextResponse(request.url, body=body.encode(), encoding="utf-8", request=request)

    results = list(spider.parse_api(response))

    items = [r for r in results if not isinstance(r, Request)]
    requests = [r for r in results if isinstance(r, Request)]
    assert len(items) == 2
    assert requests[0].meta["scraped_count"] == 3
