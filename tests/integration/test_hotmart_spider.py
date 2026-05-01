import json

from scrapper.items import ProductItem
from scrapper.spiders.hotmart import _parse_price, _parse_review_count


class TestParsePrice:
    def test_dollar_price(self):
        assert _parse_price("$49.99") == 49.99

    def test_dollar_price_integer(self):
        assert _parse_price("$50") == 50.0

    def test_brazilian_real(self):
        assert _parse_price("R$ 79,90") == 79.90

    def test_brazilian_real_with_thousands(self):
        assert _parse_price("R$ 1.299,90") == 1299.90

    def test_empty_returns_none(self):
        assert _parse_price("") is None

    def test_none_returns_none(self):
        assert _parse_price(None) is None

    def test_non_numeric_returns_none(self):
        assert _parse_price("Free") is None


class TestParseReviewCount:
    def test_extracts_number(self):
        assert _parse_review_count("234 reviews") == 234

    def test_no_reviews(self):
        assert _parse_review_count("") == 0

    def test_none_returns_zero(self):
        assert _parse_review_count(None) == 0

    def test_no_number_found(self):
        assert _parse_review_count("No reviews") == 0


class TestHotmartAPIResponseParsing:
    def test_extract_products_from_fixture(self, hotmart_api_json):
        data = json.loads(hotmart_api_json)
        products = data["data"]["search"]["products"]
        assert len(products) == 2

        prod1 = products[0]
        assert prod1["name"] == "Digital Marketing Masterclass"
        assert prod1["price"]["value"] == 49.99
        assert prod1["rating"] == 4.7
        assert prod1["reviewCount"] == 234
        assert prod1["author"]["name"] == "John Smith"

    def test_build_product_item_from_api(self, hotmart_api_json):
        data = json.loads(hotmart_api_json)
        prod = data["data"]["search"]["products"][0]

        item = ProductItem(
            site="hotmart",
            url=prod["url"],
            title=prod["name"],
            price=prod["price"]["value"],
            currency=prod["price"]["currency"],
            rating=prod["rating"],
            review_count=prod["reviewCount"],
            seller=prod["author"]["name"],
            availability="",
            metadata={"query": "python"},
        )

        assert item["title"] == "Digital Marketing Masterclass"
        assert item["price"] == 49.99
        assert item["seller"] == "John Smith"
        assert item["review_count"] == 234


class TestProductItemDefaults:
    def test_price_none_by_default(self):
        item = ProductItem(site="hotmart", url="http://x.com", title="X")
        assert item.get("price") is None

    def test_review_count_zero_by_default(self):
        item = ProductItem(site="hotmart", url="http://x.com", title="X")
        assert item["review_count"] == 0
