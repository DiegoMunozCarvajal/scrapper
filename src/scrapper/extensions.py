"""Scrapy extensions for monitoring and alerting."""

import json
import time
from urllib.request import Request, urlopen

from scrapy import signals
from loguru import logger


class StatsLogger:
    """Log scraping stats at spider completion and persist to metrics.json."""

    def __init__(self, metrics_dir: str = "metrics", metrics_max_runs: int = 100):
        self.start_time = None
        self.metrics_dir = metrics_dir
        self.metrics_max_runs = metrics_max_runs

    @classmethod
    def from_crawler(cls, crawler):
        metrics_dir = crawler.settings.get("METRICS_DIR", "metrics")
        metrics_max_runs = int(crawler.settings.get("METRICS_MAX_RUNS", 100))
        ext = cls(metrics_dir=metrics_dir, metrics_max_runs=metrics_max_runs)
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_opened(self, spider):
        self.start_time = time.time()
        logger.info(f"[{spider.name}] Spider opened")

    def spider_closed(self, spider, reason):
        stats = spider.crawler.stats
        elapsed = time.time() - self.start_time if self.start_time else 0
        items = stats.get_value("item_scraped_count", 0)

        if elapsed:
            logger.info(
                f"[{spider.name}] Spider closed: {reason} | "
                f"(items={items}, elapsed={elapsed:.1f}s, "
                f"rate={items/elapsed*60:.1f}/min)"
            )
        else:
            logger.info(
                f"[{spider.name}] Spider closed: {reason} | "
                f"(items={items}, elapsed={elapsed:.1f}s, "
                f"rate=0.0/min)"
            )

        logger.info(
            f"[{spider.name}] Stats: "
            f"responses={stats.get_value('response_received_count', 0)}, "
            f"errors={stats.get_value('log_count/ERROR', 0)}, "
            f"items={items}"
        )

        self._persist_metrics(spider, reason, stats, elapsed, items)

    def _persist_metrics(self, spider, reason, stats, elapsed, items):
        from datetime import datetime, timezone
        from pathlib import Path

        now = datetime.now(timezone.utc)
        started_at = (
            datetime.fromtimestamp(self.start_time, tz=timezone.utc).isoformat()
            if self.start_time
            else now.isoformat()
        )

        status_map = {"finished": "finished", "cancelled": "cancelled"}
        status = status_map.get(reason, "failed")

        run = {
            "spider": spider.name,
            "started_at": started_at,
            "finished_at": now.isoformat(),
            "status": status,
            "reason": reason,
            "items": items,
            "responses": stats.get_value("response_received_count", 0),
            "errors": stats.get_value("log_count/ERROR", 0),
            "elapsed_seconds": round(elapsed, 1),
            "rate_per_minute": items / elapsed * 60 if elapsed else 0,
        }

        metrics_path = Path(self.metrics_dir)
        metrics_path.mkdir(parents=True, exist_ok=True)
        metrics_file = metrics_path / "metrics.json"

        if metrics_file.exists():
            data = json.loads(metrics_file.read_text())
        else:
            data = {"runs": []}

        data["runs"].append(run)

        # Prune oldest entries per spider if over max
        spider_runs = [r for r in data["runs"] if r["spider"] == spider.name]
        if len(spider_runs) > self.metrics_max_runs:
            excess = len(spider_runs) - self.metrics_max_runs
            keep_ids = {id(r) for r in spider_runs[excess:]}
            data["runs"] = [r for r in data["runs"] if r["spider"] != spider.name or id(r) in keep_ids]

        metrics_file.write_text(json.dumps(data, indent=2))


class ErrorAlerter:
    """POST to a webhook URL when a spider encounters critical errors."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.error_count = 0

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls(webhook_url=crawler.settings.get("ALERT_WEBHOOK_URL", ""))
        crawler.signals.connect(ext.spider_error, signal=signals.spider_error)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_error(self, failure, response, spider):
        self.error_count += 1
        if self.error_count <= 5:
            logger.error(
                f"[{spider.name}] Error on {response.url if response else 'unknown'}: "
                f"{failure.getErrorMessage()}"
            )

    def spider_closed(self, spider, reason):
        if self.error_count > 5 and self.webhook_url:
            payload = json.dumps({
                "content": f":warning: **{spider.name}** closed with **{self.error_count} errors**. Reason: `{reason}`"
            }).encode()
            try:
                req = Request(self.webhook_url, data=payload, headers={"Content-Type": "application/json"})
                urlopen(req, timeout=5)
            except Exception as e:
                logger.error(f"Failed to send alert webhook: {e}")