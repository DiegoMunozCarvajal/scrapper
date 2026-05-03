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
