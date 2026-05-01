from unittest.mock import MagicMock
from scrapper.extensions import StatsLogger, ErrorAlerter


class FakeCrawler:
    def __init__(self):
        self.settings = {}
        self.signals = MagicMock()


class FakeSpider:
    name = "test_spider"


class TestStatsLogger:
    def test_init(self):
        ext = StatsLogger()
        assert ext.start_time is None

    def test_from_crawler(self):
        crawler = FakeCrawler()
        ext = StatsLogger.from_crawler(crawler)
        assert ext.start_time is None

    def test_spider_opened_sets_time(self):
        ext = StatsLogger()
        spider = FakeSpider()
        ext.spider_opened(spider)
        assert ext.start_time is not None


class TestErrorAlerter:
    def test_init(self):
        ext = ErrorAlerter(webhook_url="")
        assert ext.webhook_url == ""
        assert ext.error_count == 0

    def test_from_crawler(self):
        crawler = FakeCrawler()
        ext = ErrorAlerter.from_crawler(crawler)
        assert ext.webhook_url == ""

    def test_spider_error_counts(self):
        ext = ErrorAlerter(webhook_url="")
        spider = FakeSpider()
        response = MagicMock()
        response.url = "http://test.com"
        failure = MagicMock()
        failure.getErrorMessage.return_value = "Test error"

        ext.spider_error(failure, response, spider)
        assert ext.error_count == 1