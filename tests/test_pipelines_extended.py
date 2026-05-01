import pytest
from unittest.mock import MagicMock, patch
from scrapy.exceptions import DropItem
from scrapper.items import PostItem, ProductItem
from scrapper.pipelines import ValidatePipeline, DedupInMemoryPipeline


class FakeSpider:
    name = "test_spider"


class FakeCrawler:
    def __init__(self):
        self.settings = {"SUPABASE_URL": "", "SUPABASE_KEY": ""}


class TestValidatePipeline:
    def test_drops_missing_url(self):
        pipe = ValidatePipeline()
        item = PostItem(title="Has title but no URL")
        with pytest.raises(DropItem, match="Missing URL"):
            pipe.process_item(item, FakeSpider())

    def test_drops_missing_title(self):
        pipe = ValidatePipeline()
        item = PostItem(url="http://example.com", title="")
        with pytest.raises(DropItem, match="Missing title"):
            pipe.process_item(item, FakeSpider())

    def test_passes_valid_item(self):
        pipe = ValidatePipeline()
        item = PostItem(site="reddit", url="http://x.com", title="Valid")
        result = pipe.process_item(item, FakeSpider())
        assert result is item


class TestDedupInMemory:
    def test_drops_duplicate(self):
        pipe = DedupInMemoryPipeline()
        item1 = PostItem(site="reddit", url="http://x.com/1", title="A")
        item2 = PostItem(site="reddit", url="http://x.com/1", title="B")
        pipe.process_item(item1, FakeSpider())
        with pytest.raises(DropItem, match="Duplicate URL"):
            pipe.process_item(item2, FakeSpider())

    def test_allows_unique(self):
        pipe = DedupInMemoryPipeline()
        item1 = PostItem(site="reddit", url="http://x.com/1", title="A")
        item2 = PostItem(site="reddit", url="http://x.com/2", title="B")
        assert pipe.process_item(item1, FakeSpider()) is item1
        assert pipe.process_item(item2, FakeSpider()) is item2


class TestSupabasePipeline:
    def test_init(self):
        from scrapper.pipelines import SupabasePipeline
        pipe = SupabasePipeline("http://test.com", "key")
        assert pipe.client is not None

    def test_from_crawler(self):
        from scrapper.pipelines import SupabasePipeline
        crawler = FakeCrawler()
        crawler.settings = {"SUPABASE_URL": "http://test.com", "SUPABASE_KEY": "key123"}
        pipe = SupabasePipeline.from_crawler(crawler)
        assert pipe is not None

    def test_process_item_post(self):
        from scrapper.pipelines import SupabasePipeline
        pipe = SupabasePipeline("http://test.com", "key")

        item = PostItem(site="reddit", url="http://test.com/1", title="Test")

        spider = FakeSpider()
        spider.logger = MagicMock()

        with patch.object(pipe.client, "table") as mock_table:
            mock_table.return_value.upsert.return_value.execute.return_value = MagicMock()
            result = pipe.process_item(item, spider)

        assert result is item

    def test_process_item_product(self):
        from scrapper.pipelines import SupabasePipeline
        pipe = SupabasePipeline("http://test.com", "key")

        item = ProductItem(site="amazon", url="http://test.com/1", title="Product")

        spider = FakeSpider()
        spider.logger = MagicMock()

        with patch.object(pipe.client, "table") as mock_table:
            mock_table.return_value.upsert.return_value.execute.return_value = MagicMock()
            result = pipe.process_item(item, spider)

        assert result is item