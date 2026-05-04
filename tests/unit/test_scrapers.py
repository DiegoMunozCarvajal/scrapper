from scrapper.models import Post, Product, ScrapeResult


class TestModels:
    def test_post_creation(self):
        post = Post(
            title="Test Post",
            url="https://example.com/post",
            author="tester",
            score=42,
        )
        assert post.title == "Test Post"
        assert post.score == 42
        assert post.content == ""
        assert post.comment_count == 0

    def test_product_creation(self):
        product = Product(
            title="Test Product",
            url="https://example.com/product",
            price=19.99,
            currency="USD",
            rating=4.5,
        )
        assert product.price == 19.99
        assert product.rating == 4.5
        assert product.review_count == 0

    def test_scrape_result(self):
        result = ScrapeResult(source="test", query="hello")
        assert result.source == "test"
        assert result.posts == []
        assert result.products == []
        assert result.scraped_at is not None
