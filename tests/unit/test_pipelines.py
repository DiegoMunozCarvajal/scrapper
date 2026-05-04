import pytest
from scrapy.exceptions import DropItem
from scrapper.items import PostItem, ProductItem
from scrapper.pipelines import ValidatePipeline, DedupInMemoryPipeline, DataQualityPipeline


class FakeCrawler:
    class Spider:
        name = "test_spider"
    spider = Spider()


def test_validate_drops_missing_url():
    pipe = ValidatePipeline()
    pipe._crawler = FakeCrawler()
    item = PostItem(title="Has title but no URL")
    with pytest.raises(DropItem, match="Missing URL"):
        pipe.process_item(item)


def test_validate_drops_missing_title():
    pipe = ValidatePipeline()
    pipe._crawler = FakeCrawler()
    item = PostItem(url="http://example.com", title="")
    with pytest.raises(DropItem, match="Missing title"):
        pipe.process_item(item)


def test_validate_passes_valid_item():
    pipe = ValidatePipeline()
    pipe._crawler = FakeCrawler()
    item = PostItem(site="reddit", url="http://x.com", title="Valid")
    result = pipe.process_item(item)
    assert result is item


def test_dedup_drops_duplicate():
    pipe = DedupInMemoryPipeline()
    item1 = PostItem(site="reddit", url="http://x.com/1", title="A")
    item2 = PostItem(site="reddit", url="http://x.com/1", title="B")
    pipe.process_item(item1)
    with pytest.raises(DropItem, match="Duplicate URL"):
        pipe.process_item(item2)


def test_dedup_allows_unique():
    pipe = DedupInMemoryPipeline()
    item1 = PostItem(site="reddit", url="http://x.com/1", title="A")
    item2 = PostItem(site="reddit", url="http://x.com/2", title="B")
    assert pipe.process_item(item1) is item1
    assert pipe.process_item(item2) is item2


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
        result = pipe.process_item(item)
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
        pipe.process_item(item)
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
        pipe.process_item(item)
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
        pipe.process_item(item)
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
        pipe.process_item(item)
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
        pipe.process_item(item)
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
        pipe.process_item(item)
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
        pipe.process_item(item)
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
        pipe.process_item(item)
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
        pipe.process_item(item)
        assert item.get("quality_issues") == []

    def test_close_spider_reports_stats(self):
        pipe = DataQualityPipeline()
        pipe._crawler = FakeCrawler()
        item = PostItem(
            site="reddit",
            url="https://example.com/post",
            title="ab",  # triggers title_too_short
        )
        pipe.process_item(item)
        pipe.close_spider()
        stats = pipe._stats["test_spider"]
        assert stats["total"] == 1
        assert stats["issues"] == 1
