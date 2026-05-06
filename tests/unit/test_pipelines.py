import pytest
from scrapy.exceptions import DropItem, NotConfigured
from scrapper.items import GenericItem, PostItem, ProductItem
from scrapper.pipelines import ValidatePipeline, DedupInMemoryPipeline, DataQualityPipeline, SupabasePipeline


class FakeSpider:
    name = "test_spider"


class FakeCrawler:
    spider = FakeSpider()


def _spider():
    return FakeSpider()


def test_validate_drops_missing_url():
    pipe = ValidatePipeline()
    pipe._crawler = FakeCrawler()
    item = PostItem(title="Has title but no URL")
    with pytest.raises(DropItem, match="Missing URL"):
        pipe.process_item(item, spider=_spider())


def test_validate_drops_missing_title():
    pipe = ValidatePipeline()
    pipe._crawler = FakeCrawler()
    item = PostItem(url="http://example.com", title="")
    with pytest.raises(DropItem, match="Missing title"):
        pipe.process_item(item, spider=_spider())


def test_validate_passes_valid_item():
    pipe = ValidatePipeline()
    pipe._crawler = FakeCrawler()
    item = PostItem(site="reddit", url="http://x.com", title="Valid")
    result = pipe.process_item(item, spider=_spider())
    assert result is item


def test_dedup_drops_duplicate():
    pipe = DedupInMemoryPipeline()
    item1 = PostItem(site="reddit", url="http://x.com/1", title="A")
    item2 = PostItem(site="reddit", url="http://x.com/1", title="B")
    pipe.process_item(item1, spider=_spider())
    with pytest.raises(DropItem, match="Duplicate URL"):
        pipe.process_item(item2, spider=_spider())


def test_dedup_allows_unique():
    pipe = DedupInMemoryPipeline()
    item1 = PostItem(site="reddit", url="http://x.com/1", title="A")
    item2 = PostItem(site="reddit", url="http://x.com/2", title="B")
    assert pipe.process_item(item1, spider=_spider()) is item1
    assert pipe.process_item(item2, spider=_spider()) is item2


class TestDataQualityPipeline:
    def test_valid_item_no_issues(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = PostItem(
            site="reddit",
            url="https://example.com/post",
            title="A Valid Post Title",
            content="This is some valid content.",
            score=42,
        )
        result = pipe.process_item(item, spider=_spider())
        assert result is item
        assert item.get("quality_issues") == []

    def test_invalid_url_scheme_flagged(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = PostItem(
            site="reddit",
            url="ftp://example.com/post",
            title="A Valid Post Title",
        )
        pipe.process_item(item, spider=_spider())
        assert "quality_issues" in item
        assert "invalid_url_scheme" in item["quality_issues"]

    def test_title_too_short_flagged(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = PostItem(
            site="reddit",
            url="https://example.com/post",
            title="ab",
        )
        pipe.process_item(item, spider=_spider())
        assert "title_too_short" in item["quality_issues"]

    def test_content_too_short_flagged(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = PostItem(
            site="reddit",
            url="https://example.com/post",
            title="Valid Title",
            content="short",
        )
        pipe.process_item(item, spider=_spider())
        assert "content_too_short" in item["quality_issues"]

    def test_content_none_not_flagged(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = PostItem(
            site="reddit",
            url="https://example.com/post",
            title="Valid Title",
            content=None,
        )
        pipe.process_item(item, spider=_spider())
        assert item.get("quality_issues") == []

    def test_price_invalid_flagged(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = ProductItem(
            site="hotmart",
            url="https://example.com/product",
            title="Product",
            price=-5,
        )
        pipe.process_item(item, spider=_spider())
        assert "price_invalid" in item["quality_issues"]

    def test_price_not_numeric_flagged(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = ProductItem(
            site="hotmart",
            url="https://example.com/product",
            title="Product",
            price="gratis",
        )
        pipe.process_item(item, spider=_spider())
        assert "price_not_numeric" in item["quality_issues"]

    def test_rating_out_of_range_flagged(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = ProductItem(
            site="hotmart",
            url="https://example.com/product",
            title="Product",
            rating=6.0,
        )
        pipe.process_item(item, spider=_spider())
        assert "rating_out_of_range" in item["quality_issues"]

    def test_score_not_integer_flagged(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = PostItem(
            site="reddit",
            url="https://example.com/post",
            title="Valid Title",
            score="not-a-number",
        )
        pipe.process_item(item, spider=_spider())
        assert "score_not_integer" in item["quality_issues"]

    def test_price_none_not_flagged(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = ProductItem(
            site="hotmart",
            url="https://example.com/product",
            title="Product",
            price=None,
        )
        pipe.process_item(item, spider=_spider())
        assert item.get("quality_issues") == []

    def test_close_spider_reports_stats(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = PostItem(
            site="reddit",
            url="https://example.com/post",
            title="ab",  # triggers title_too_short
        )
        pipe.process_item(item, spider=_spider())
        pipe.close_spider(spider=pipe._crawler.spider)
        stats = pipe._stats["test_spider"]
        assert stats["total"] == 1
        assert stats["issues"] == 1

    def test_generic_product_price_rating_validation(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = GenericItem(
            site="example.com",
            url="https://example.com/product",
            title="Test Product",
            page_type="product",
            price=-10,
            rating=6.0,
        )
        pipe.process_item(item, spider=_spider())
        assert "price_invalid" in item["quality_issues"]
        assert "rating_out_of_range" in item["quality_issues"]

    def test_generic_forum_score_validation(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = GenericItem(
            site="example.com",
            url="https://example.com/post",
            title="Test Post",
            page_type="forum",
            score="not-a-number",
        )
        pipe.process_item(item, spider=_spider())
        assert "score_not_integer" in item["quality_issues"]

    def test_generic_article_no_price_validation(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = GenericItem(
            site="example.com",
            url="https://example.com/article",
            title="Test Article",
            page_type="article",
            content="This is a proper article with enough content.",
        )
        pipe.process_item(item, spider=_spider())
        assert item.get("quality_issues") == []

    def test_generic_unknown_type_basic_validation_only(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = GenericItem(
            site="example.com",
            url="https://example.com/page",
            title="Test Page",
            page_type="other",
        )
        pipe.process_item(item, spider=_spider())
        assert item.get("quality_issues") == []

    def test_generic_validate_passes_valid(self):
        pipe = ValidatePipeline()
        pipe._crawler = FakeCrawler()
        item = GenericItem(site="example.com", url="http://x.com", title="Valid")
        result = pipe.process_item(item, spider=_spider())
        assert result is item

    def test_generic_dedup_works(self):
        pipe = DedupInMemoryPipeline()
        item1 = GenericItem(site="example.com", url="http://x.com/1", title="A")
        item2 = GenericItem(site="example.com", url="http://x.com/1", title="B")
        pipe.process_item(item1, spider=_spider())
        with pytest.raises(DropItem, match="Duplicate URL"):
            pipe.process_item(item2, spider=_spider())


class FakeSettings(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeCrawlerWithSettings:
    def __init__(self, settings):
        self.settings = FakeSettings(settings)


def test_supabase_pipeline_disabled_without_credentials():
    crawler = FakeCrawlerWithSettings({"SUPABASE_URL": "", "SUPABASE_KEY": ""})
    with pytest.raises(NotConfigured, match="SUPABASE_URL and SUPABASE_KEY"):
        SupabasePipeline.from_crawler(crawler)


def test_supabase_pipeline_serializes_only_table_columns():
    pipe = SupabasePipeline.__new__(SupabasePipeline)
    item = PostItem(
        site="reddit",
        url="https://old.reddit.com/r/test/comments/abc/title/",
        title="Title",
        thumbnail="https://example.com/thumb.jpg",
        link_flair="Discussion",
        domain="self.test",
        nsfw=False,
        is_self_post=True,
        permalink="/r/test/comments/abc/title/",
        quality_issues=["low_score"],
        metadata={"strategy": "json_api"},
    )

    data = pipe._serialize_item(item, "posts")

    assert data["thumbnail"] == "https://example.com/thumb.jpg"
    assert data["link_flair"] == "Discussion"
    assert data["is_self_post"] is True
    assert data["quality_issues"] == ["low_score"]
    # Fields not in TABLE_FIELDS["posts"] must be excluded
    assert "extra_field" not in data
