import pytest
from scrapy.exceptions import DropItem
from scrapper.items import PostItem
from scrapper.pipelines import ValidatePipeline, DedupInMemoryPipeline


class FakeSpider:
    name = "test_spider"


def test_validate_drops_missing_url():
    pipe = ValidatePipeline()
    item = PostItem(title="Has title but no URL")
    with pytest.raises(DropItem, match="Missing URL"):
        pipe.process_item(item, FakeSpider())


def test_validate_drops_missing_title():
    pipe = ValidatePipeline()
    item = PostItem(url="http://example.com", title="")
    with pytest.raises(DropItem, match="Missing title"):
        pipe.process_item(item, FakeSpider())


def test_validate_passes_valid_item():
    pipe = ValidatePipeline()
    item = PostItem(site="reddit", url="http://x.com", title="Valid")
    result = pipe.process_item(item, FakeSpider())
    assert result is item


def test_dedup_drops_duplicate():
    pipe = DedupInMemoryPipeline()
    item1 = PostItem(site="reddit", url="http://x.com/1", title="A")
    item2 = PostItem(site="reddit", url="http://x.com/1", title="B")
    pipe.process_item(item1, FakeSpider())
    with pytest.raises(DropItem, match="Duplicate URL"):
        pipe.process_item(item2, FakeSpider())


def test_dedup_allows_unique():
    pipe = DedupInMemoryPipeline()
    item1 = PostItem(site="reddit", url="http://x.com/1", title="A")
    item2 = PostItem(site="reddit", url="http://x.com/2", title="B")
    assert pipe.process_item(item1, FakeSpider()) is item1
    assert pipe.process_item(item2, FakeSpider()) is item2