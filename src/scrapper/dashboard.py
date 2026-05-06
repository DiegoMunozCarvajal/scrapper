"""Generate a local HTML dashboard from persisted crawl metrics."""
import json
from datetime import datetime, timezone
from pathlib import Path

from scrapy import signals
from loguru import logger

_TEMPLATE = None


def _get_template() -> str:
    global _TEMPLATE
    if _TEMPLATE is None:
        template_path = Path(__file__).parent / "templates" / "dashboard.html"
        _TEMPLATE = template_path.read_text()
    return _TEMPLATE


class MetricsDashboard:
    """Generate dashboard.html from metrics.json after each crawl."""

    def __init__(self, metrics_dir: str = "metrics"):
        self.metrics_dir = metrics_dir

    @classmethod
    def from_crawler(cls, crawler):
        metrics_dir = crawler.settings.get("METRICS_DIR", "metrics")
        ext = cls(metrics_dir=metrics_dir)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_closed(self, spider, reason):
        self._build_dashboard()

    def _build_dashboard(self):
        Path(self.metrics_dir).mkdir(parents=True, exist_ok=True)
        metrics_path = Path(self.metrics_dir) / "metrics.json"
        if not metrics_path.exists():
            data = {"runs": [], "generated_at": datetime.now(timezone.utc).isoformat()}
        else:
            try:
                data = json.loads(metrics_path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to read metrics.json: {e}, resetting")
                data = {"runs": []}
            data["generated_at"] = datetime.now(timezone.utc).isoformat()

        html = _get_template().replace("__DATA__", json.dumps(data))
        dashboard_path = Path(self.metrics_dir) / "dashboard.html"
        dashboard_path.write_text(html)
        logger.info(f"Dashboard written to {dashboard_path}")
