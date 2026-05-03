import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scrapper.extensions import StatsLogger


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
            assert run["rate_per_minute"] == pytest.approx(109.1, rel=0.01)
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

    def test_persist_metrics_unknown_reason_maps_to_failed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ext = StatsLogger(metrics_dir=tmpdir, metrics_max_runs=100)
            ext.start_time = 1000.0
            spider = FakeSpider()
            spider.name = "reddit"
            stats = MagicMock()
            stats.get_value.return_value = 0
            spider.crawler = MagicMock()
            spider.crawler.stats = stats

            with patch("time.time", return_value=1005.0):
                ext.spider_closed(spider, "shutdown")

            data = json.loads(Path(tmpdir, "metrics.json").read_text())
            assert data["runs"][0]["status"] == "failed"


class TestLogRotation:
    def test_log_rotation_settings_exist(self):
        from scrapper import settings
        assert settings.LOG_FILE_PATH == "logs/scrapy.log"
        assert settings.LOG_FILE_MAX_BYTES == 5 * 1024 * 1024
        assert settings.LOG_FILE_BACKUP_COUNT == 5
        assert settings.LOG_FILE_TIME == "logs/scrapy-daily.log"
        assert settings.LOG_FILE_TIME_WHEN == "00:00"
        assert settings.LOG_FILE_TIME_BACKUP == 7

    def test_setup_log_rotation_adds_handlers(self, monkeypatch):
        import scrapper.extensions as ext_mod
        from loguru import logger

        # Reset global guard before test
        ext_mod._log_handlers_configured = False

        initial_handlers = len(logger._core.handlers)

        from scrapper.extensions import StatsLogger
        ext = StatsLogger(metrics_dir="/tmp/fake")
        Path("/tmp/fake/logs").mkdir(parents=True, exist_ok=True)
        ext._setup_log_rotation()

        assert len(logger._core.handlers) >= initial_handlers + 2

        # Cleanup: remove handlers added by test
        while len(logger._core.handlers) > initial_handlers:
            logger.remove()

        # Reset global guard
        ext_mod._log_handlers_configured = False

    def test_setup_log_rotation_called_once(self, monkeypatch):
        from scrapper.extensions import StatsLogger
        import scrapper.extensions as ext_mod
        from loguru import logger

        initial_count = len(logger._core.handlers)

        ext = StatsLogger(metrics_dir="/tmp/fake")
        Path("/tmp/fake/logs").mkdir(parents=True, exist_ok=True)
        ext._setup_log_rotation()
        first_count = len(logger._core.handlers)
        ext._setup_log_rotation()

        assert len(logger._core.handlers) == first_count

        while len(logger._core.handlers) > initial_count:
            logger.remove()
        ext_mod._log_handlers_configured = False


class FakeStats:
    def get_value(self, key, default=0):
        return {"item_scraped_count": 10, "response_received_count": 2, "log_count/ERROR": 7}.get(key, default)


class TestEmailAlerter:
    def test_init(self):
        from scrapper.extensions import EmailAlerter
        ext = EmailAlerter(
            smtp_host="smtp.test.com", smtp_port=587,
            from_addr="a@b.com", password="pw", to_addr="c@d.com",
        )
        assert ext.smtp_host == "smtp.test.com"
        assert ext.error_count == 0

    def test_from_crawler_reads_settings(self):
        from scrapper.extensions import EmailAlerter
        crawler = FakeCrawler()
        crawler.settings = {
            "ALERT_SMTP_HOST": "mx.example.com",
            "ALERT_SMTP_PORT": 2525,
            "ALERT_EMAIL_FROM": "from@x.com",
            "_ALERT_EMAIL_PASSWORD": "secret",
            "ALERT_EMAIL_TO": "to@x.com",
            "METRICS_DIR": "mymetrics",
            "ALERT_ERROR_THRESHOLD": 10,
        }
        ext = EmailAlerter.from_crawler(crawler)
        assert ext.smtp_host == "mx.example.com"
        assert ext.smtp_port == 2525
        assert ext.from_addr == "from@x.com"
        assert ext.to_addr == "to@x.com"
        assert ext.metrics_dir == "mymetrics"
        assert ext.error_threshold == 10

    def test_spider_error_counts(self):
        from scrapper.extensions import EmailAlerter
        ext = EmailAlerter("h", 587, "a", "p", "t")
        failure = MagicMock()
        response = MagicMock()
        response.url = "https://test.com"
        spider = FakeSpider()
        spider.name = "test"
        ext.spider_error(failure, response, spider)
        ext.spider_error(failure, response, spider)
        assert ext.error_count == 2

    def test_email_not_sent_without_credentials(self):
        from scrapper.extensions import EmailAlerter
        ext = EmailAlerter("h", 587, "", "", "")
        ext.error_count = 10
        spider = MagicMock()
        spider.name = "test"
        spider.crawler = MagicMock()
        spider.crawler.stats = FakeStats()
        with patch("smtplib.SMTP") as mock_smtp:
            ext.spider_closed(spider, "finished")
            mock_smtp.assert_not_called()

    def test_email_sent_on_critical_error(self):
        from scrapper.extensions import EmailAlerter
        ext = EmailAlerter("h", 587, "from@x.com", "pw", "to@x.com")
        ext.error_count = 10
        spider = MagicMock()
        spider.name = "test"
        spider.crawler = MagicMock()
        spider.crawler.stats = FakeStats()
        with patch("smtplib.SMTP") as mock_smtp:
            ext.spider_closed(spider, "finished")
            mock_smtp.assert_called_once()

    def test_anomaly_detects_item_drop(self):
        from scrapper.extensions import EmailAlerter
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_file = Path(tmpdir) / "metrics.json"
            runs_data = {"runs": [
                {"spider": "test", "items": 10, "errors": 0, "status": "finished",
                 "started_at": "2026-05-03T00:00:00+00:00",
                 "finished_at": "2026-05-03T00:00:05+00:00", "reason": "finished",
                 "responses": 2, "elapsed_seconds": 5.0, "rate_per_minute": 120.0}
                for _ in range(10)
            ]}
            metrics_file.write_text(json.dumps(runs_data))

            ext = EmailAlerter("h", 587, "from@x.com", "pw", "to@x.com", metrics_dir=tmpdir)
            spider = MagicMock()
            spider.name = "test"

            result = ext._detect_anomaly(spider)
            assert result is None

            runs_data["runs"].append({
                "spider": "test", "items": 2, "errors": 0, "status": "failed",
                "started_at": "2026-05-03T01:00:00+00:00",
                "finished_at": "2026-05-03T01:00:05+00:00", "reason": "cancelled",
                "responses": 2, "elapsed_seconds": 5.0, "rate_per_minute": 24.0,
            })
            metrics_file.write_text(json.dumps(runs_data))

            result = ext._detect_anomaly(spider)
            assert result is not None
            assert "items 2 vs avg 10" in result
            assert "status=failed" in result

    def test_anomaly_no_false_positive_on_low_baseline(self):
        from scrapper.extensions import EmailAlerter
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_file = Path(tmpdir) / "metrics.json"
            metrics_file.write_text(json.dumps({"runs": [
                {"spider": "test", "items": 1, "errors": 0, "status": "finished",
                 "started_at": "2026-05-03T00:00:00+00:00",
                 "finished_at": "2026-05-03T00:00:05+00:00", "reason": "finished",
                 "responses": 1, "elapsed_seconds": 5.0, "rate_per_minute": 12.0}
            ]}))
            ext = EmailAlerter("h", 587, "from@x.com", "pw", "to@x.com", metrics_dir=tmpdir)
            spider = MagicMock()
            spider.name = "test"
            result = ext._detect_anomaly(spider)
            assert result is None

    def test_smtp_exception_handled_gracefully(self):
        from scrapper.extensions import EmailAlerter
        ext = EmailAlerter("h", 587, "from@x.com", "pw", "to@x.com")
        ext.error_count = 10
        spider = MagicMock()
        spider.name = "test"
        spider.crawler = MagicMock()
        spider.crawler.stats = FakeStats()
        with patch("smtplib.SMTP", side_effect=Exception("Connection refused")):
            ext.spider_closed(spider, "finished")


class TestEmailAlerterIntegration:
    def test_full_flow_stats_to_email(self):
        import json
        import tempfile
        from pathlib import Path
        from scrapper.extensions import EmailAlerter, StatsLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            stats_ext = StatsLogger(metrics_dir=tmpdir, metrics_max_runs=100)
            stats_ext.start_time = 1000.0
            spider = FakeSpider()
            spider.name = "test_spider"
            stats = FakeStats()
            spider.crawler = MagicMock()
            spider.crawler.stats = stats
            with patch("time.time", return_value=1005.0):
                stats_ext.spider_closed(spider, "finished")

            email_ext = EmailAlerter("h", 587, "a@b.com", "pw", "c@d.com", metrics_dir=tmpdir)
            anomaly = email_ext._detect_anomaly(spider)
            assert anomaly is None

            for i in range(9):
                run = {
                    "spider": "test_spider", "items": 10, "errors": 0, "status": "finished",
                    "started_at": f"2026-05-0{i+1}T00:00:00+00:00",
                    "finished_at": f"2026-05-0{i+1}T00:00:05+00:00",
                    "reason": "finished", "responses": 2,
                    "elapsed_seconds": 5.0, "rate_per_minute": 120.0,
                }
                metrics_path = Path(tmpdir) / "metrics.json"
                data = json.loads(metrics_path.read_text())
                data["runs"].append(run)
                metrics_path.write_text(json.dumps(data))

            run = {
                "spider": "test_spider", "items": 2, "errors": 0, "status": "finished",
                "started_at": "2026-05-10T00:00:00+00:00",
                "finished_at": "2026-05-10T00:00:05+00:00",
                "reason": "finished", "responses": 2,
                "elapsed_seconds": 5.0, "rate_per_minute": 24.0,
            }
            data = json.loads(metrics_path.read_text())
            data["runs"].append(run)
            metrics_path.write_text(json.dumps(data))

            anomaly = email_ext._detect_anomaly(spider)
            assert anomaly is not None
            assert "items 2 vs avg 10" in anomaly