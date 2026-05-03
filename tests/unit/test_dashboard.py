import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from scrapper.dashboard import MetricsDashboard


class FakeCrawler:
    def __init__(self):
        self.settings = {}
        self.signals = MagicMock()


class FakeSpider:
    name = "test_spider"


class TestMetricsDashboard:
    def test_from_crawler(self):
        crawler = FakeCrawler()
        crawler.settings = {"METRICS_DIR": "my_metrics"}
        ext = MetricsDashboard.from_crawler(crawler)
        assert ext.metrics_dir == "my_metrics"

    def test_from_crawler_default_dir(self):
        crawler = FakeCrawler()
        crawler.settings = {}
        ext = MetricsDashboard.from_crawler(crawler)
        assert ext.metrics_dir == "metrics"

    def test_build_dashboard_creates_html(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_file = Path(tmpdir) / "metrics.json"
            metrics_file.write_text(json.dumps({
                "runs": [
                    {
                        "spider": "reddit",
                        "started_at": "2026-05-03T00:54:32+00:00",
                        "finished_at": "2026-05-03T00:54:38+00:00",
                        "status": "finished",
                        "reason": "finished",
                        "items": 10,
                        "responses": 1,
                        "errors": 2,
                        "elapsed_seconds": 5.5,
                        "rate_per_minute": 109.1,
                    }
                ]
            }))

            ext = MetricsDashboard(metrics_dir=tmpdir)
            ext._build_dashboard()

            dashboard = Path(tmpdir) / "dashboard.html"
            assert dashboard.exists()
            content = dashboard.read_text()
            assert "<!DOCTYPE html>" in content
            assert "</html>" in content

    def test_dashboard_embeds_metrics_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_file = Path(tmpdir) / "metrics.json"
            metrics_file.write_text(json.dumps({"runs": []}))

            ext = MetricsDashboard(metrics_dir=tmpdir)
            ext._build_dashboard()

            dashboard = Path(tmpdir) / "dashboard.html"
            content = dashboard.read_text()
            assert "const METRICS =" in content
            assert '"runs"' in content

    def test_build_dashboard_creates_metrics_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent = str(Path(tmpdir) / "new_metrics_dir")
            ext = MetricsDashboard(metrics_dir=nonexistent)
            ext._build_dashboard()
            assert Path(nonexistent).is_dir()
            assert (Path(nonexistent) / "dashboard.html").exists()

    def test_build_dashboard_no_crash_on_missing_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ext = MetricsDashboard(metrics_dir=tmpdir)
            ext._build_dashboard()

            dashboard = Path(tmpdir) / "dashboard.html"
            assert dashboard.exists()
            content = dashboard.read_text()
            assert "No metrics data yet" in content.lower() or "const METRICS = " in content
