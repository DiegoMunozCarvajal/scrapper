import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestStatsLoggerMetrics:
    def test_constructor_accepts_metrics_params(self):
        ext = StatsLogger(metrics_dir="custom_metrics", metrics_max_runs=50)
        assert ext.metrics_dir == "custom_metrics"
        assert ext.metrics_max_runs == 50

    def test_from_crawler_reads_settings(self):
        crawler = FakeCrawler()
        crawler.settings = {
            "METRICS_DIR": "test_metrics",
            "METRICS_MAX_RUNS": 25,
        }
        ext = StatsLogger.from_crawler(crawler)
        assert ext.metrics_dir == "test_metrics"
        assert ext.metrics_max_runs == 25

    def test_from_crawler_defaults_when_no_settings(self):
        crawler = FakeCrawler()
        crawler.settings = {}
        ext = StatsLogger.from_crawler(crawler)
        assert ext.metrics_dir == "metrics"
        assert ext.metrics_max_runs == 100

    def test_persist_metrics_writes_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ext = StatsLogger(metrics_dir=tmpdir, metrics_max_runs=100)
            ext.start_time = 1000.0
            spider = FakeSpider()
            spider.name = "reddit"
            stats = MagicMock()
            stats.get_value.return_value = 10
            spider.crawler = MagicMock()
            spider.crawler.stats = stats

            with patch("time.time", return_value=1005.5):
                ext.spider_closed(spider, "finished")

            metrics_file = Path(tmpdir) / "metrics.json"
            assert metrics_file.exists()
            data = json.loads(metrics_file.read_text())
            assert "runs" in data
            assert len(data["runs"]) == 1
            run = data["runs"][0]
            assert run["spider"] == "reddit"
            assert run["status"] == "finished"
            assert run["items"] == 10
            assert run["elapsed_seconds"] == 5.5
            assert run["rate_per_minute"] == 109.0909090909091
            assert "started_at" in run
            assert "finished_at" in run

    def test_persist_metrics_prunes_old_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_file = Path(tmpdir) / "metrics.json"
            existing = {
                "runs": [
                    {"spider": "reddit", "started_at": f"2026-05-0{i}T00:00:00+00:00",
                     "finished_at": f"2026-05-0{i}T00:00:05+00:00", "status": "finished",
                     "reason": "finished", "items": i, "responses": 10, "errors": 0,
                     "elapsed_seconds": 5.0, "rate_per_minute": 0.0}
                    for i in range(1, 6)
                ]
            }
            metrics_file.write_text(json.dumps(existing))

            ext = StatsLogger(metrics_dir=tmpdir, metrics_max_runs=3)
            ext.start_time = 2000.0
            spider = FakeSpider()
            spider.name = "reddit"
            stats = MagicMock()
            stats.get_value.return_value = 10
            spider.crawler = MagicMock()
            spider.crawler.stats = stats

            with patch("time.time", return_value=2005.0):
                ext.spider_closed(spider, "finished")

            data = json.loads(metrics_file.read_text())
            assert len(data["runs"]) == 3

    def test_persist_metrics_handles_zero_elapsed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ext = StatsLogger(metrics_dir=tmpdir, metrics_max_runs=100)
            ext.start_time = None
            spider = FakeSpider()
            spider.name = "reddit"
            stats = MagicMock()
            stats.get_value.return_value = 0
            spider.crawler = MagicMock()
            spider.crawler.stats = stats

            ext.spider_closed(spider, "finished")

            metrics_file = Path(tmpdir) / "metrics.json"
            data = json.loads(metrics_file.read_text())
            assert data["runs"][0]["elapsed_seconds"] == 0
            assert data["runs"][0]["rate_per_minute"] == 0