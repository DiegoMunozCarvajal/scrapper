from scrapper.items import GenericItem, PostItem, ProductItem


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


def test_post_item_has_scraped_at():
    item = PostItem(site="reddit", url="http://x.com", title="X")
    assert item.get("scraped_at") is not None
    assert "T" in item["scraped_at"]  # ISO timestamp has T


def test_product_item_has_scraped_at():
    item = ProductItem(site="amazon", url="http://x.com", title="X")
    assert item.get("scraped_at") is not None
    assert "T" in item["scraped_at"]  # ISO timestamp has T


def test_generic_item_creation():
    item = GenericItem(
        site="example.com",
        url="https://example.com/product",
        title="Test Product",
        page_type="product",
        price=29.99,
        rating=4.5,
        review_count=100,
        content="Product description",
        author="Author Name",
        metadata={"isbn": "123-456"},
    )
    assert item["site"] == "example.com"
    assert item["url"] == "https://example.com/product"
    assert item["page_type"] == "product"
    assert item["price"] == 29.99
    assert item["rating"] == 4.5
    assert item["review_count"] == 100
    assert item["metadata"]["isbn"] == "123-456"


def test_generic_item_defaults():
    item = GenericItem(site="example.com", url="http://x.com", title="X")
    assert item.get("currency") == "USD"
    assert item.get("review_count") == 0
    assert item.get("price") is None
    assert item.get("rating") is None
    assert item.get("content") is None
    assert item.get("author") is None
    assert item.get("page_type") is None


def test_generic_item_missing_optional_does_not_raise():
    item = GenericItem()
    assert item.get("url") is None


def test_generic_item_has_scraped_at():
    item = GenericItem(site="example.com", url="http://x.com", title="X")
    assert item.get("scraped_at") is not None
    assert "T" in item["scraped_at"]


def test_generic_item_new_fields():
    item = GenericItem(
        site="example.com",
        url="https://example.com/job/1",
        title="Senior Engineer",
        image_url="https://example.com/img/photo.jpg",
        category="Engineering",
    )
    assert item["image_url"] == "https://example.com/img/photo.jpg"
    assert item["category"] == "Engineering"


def test_generic_item_new_fields_default_to_none():
    item = GenericItem(site="example.com", url="http://x.com", title="X")
    assert item.get("image_url") is None
    assert item.get("category") is None