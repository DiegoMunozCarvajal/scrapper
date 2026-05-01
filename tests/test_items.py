from scrapper.items import PostItem, ProductItem


def test_post_item_creation():
    item = PostItem(site="reddit", url="https://reddit.com/r/test/1", title="Test Post")
    assert item["site"] == "reddit"
    assert item["url"] == "https://reddit.com/r/test/1"
    assert item["title"] == "Test Post"
    assert item.get("score", 0) == 0


def test_post_item_defaults():
    item = PostItem(site="reddit", url="http://x.com", title="X")
    assert item["content"] == ""
    assert item["comment_count"] == 0
    assert item.get("published_at") is None


def test_product_item_creation():
    item = ProductItem(
        site="amazon",
        url="https://amazon.com/dp/B0TEST",
        title="Widget",
        price=29.99,
        currency="USD",
        rating=4.5,
        review_count=100,
        seller="Acme Corp",
        availability="In Stock",
        metadata={"asin": "B0TEST"},
    )
    assert item["site"] == "amazon"
    assert item["price"] == 29.99
    assert item["rating"] == 4.5
    assert item["metadata"]["asin"] == "B0TEST"


def test_product_item_defaults():
    item = ProductItem(site="ml", url="http://x.com", title="X")
    assert item.get("price") is None
    assert item.get("currency") == "USD"
    assert item.get("review_count") == 0


def test_post_item_missing_required_does_not_raise():
    item = PostItem()
    assert item.get("url") is None