"""Scrapy extensions for monitoring and alerting."""

import portalocker
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from scrapy import signals
from loguru import logger

_log_handlers_configured = False


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

    @staticmethod
    def _setup_log_rotation():
        global _log_handlers_configured
        if _log_handlers_configured:
            return
        _log_handlers_configured = True

        from pathlib import Path
        from . import settings

        Path("logs").mkdir(parents=True, exist_ok=True)

        logger.add(
            settings.LOG_FILE_PATH,
            rotation=settings.LOG_FILE_MAX_BYTES,
            retention=settings.LOG_FILE_BACKUP_COUNT,
            level=settings.LOG_LEVEL,
            format="{time:YYYY-MM-DD HH:mm:ss} [{name}] {level}: {message}",
        )

        logger.add(
            settings.LOG_FILE_TIME,
            rotation=settings.LOG_FILE_TIME_WHEN,
            retention=settings.LOG_FILE_TIME_BACKUP,
            level=settings.LOG_LEVEL,
            format="{time:YYYY-MM-DD HH:mm:ss} [{name}] {level}: {message}",
        )

    def spider_opened(self, spider):
        self.start_time = time.time()
        self._setup_log_rotation()
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
            "rate_per_minute": round(items / elapsed * 60, 1) if elapsed else 0,
        }

        metrics_path = Path(self.metrics_dir)
        metrics_path.mkdir(parents=True, exist_ok=True)
        metrics_file = metrics_path / "metrics.json"

        with open(metrics_file, "a+") as f:
            portalocker.lock(f, portalocker.LOCK_EX)
            try:
                f.seek(0)
                content = f.read()
                if content.strip():
                    try:
                        data = json.loads(content)
                        if not isinstance(data, dict) or "runs" not in data:
                            data = {"runs": []}
                    except (json.JSONDecodeError, ValueError):
                        logger.warning(
                            "Corrupted metrics.json detected, resetting to empty"
                        )
                        data = {"runs": []}
                else:
                    data = {"runs": []}
                data["runs"].append(run)

                # Prune oldest entries per spider if over max
                spider_runs = [r for r in data["runs"] if r["spider"] == spider.name]
                if len(spider_runs) > self.metrics_max_runs:
                    excess = len(spider_runs) - self.metrics_max_runs
                    keep_keys = {r["started_at"] for r in spider_runs[excess:]}
                    data["runs"] = [r for r in data["runs"] if r["spider"] != spider.name or r["started_at"] in keep_keys]

                f.seek(0)
                f.truncate()
                f.write(json.dumps(data, indent=2))
            finally:
                portalocker.unlock(f)


class EmailAlerter:
    """Send email alerts on critical errors and metric anomalies."""

    def __init__(self, smtp_host, smtp_port, from_addr, password, to_addr,
                 metrics_dir="metrics", error_threshold=5):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.from_addr = from_addr
        self._password = password
        self.to_addr = to_addr
        self.metrics_dir = metrics_dir
        self.error_threshold = error_threshold
        self.error_count = 0

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls(
            smtp_host=crawler.settings.get("ALERT_SMTP_HOST", "smtp.gmail.com"),
            smtp_port=int(crawler.settings.get("ALERT_SMTP_PORT", 587)),
            from_addr=crawler.settings.get("ALERT_EMAIL_FROM", ""),
            password=crawler.settings.get("_ALERT_EMAIL_PASSWORD", ""),
            to_addr=crawler.settings.get("ALERT_EMAIL_TO", ""),
            metrics_dir=crawler.settings.get("METRICS_DIR", "metrics"),
            error_threshold=int(crawler.settings.get("ALERT_ERROR_THRESHOLD", 5)),
        )
        crawler.signals.connect(ext.spider_error, signal=signals.spider_error)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_error(self, failure, response, spider):
        self.error_count += 1

    def spider_closed(self, spider, reason):
        alerts = []

        if self.error_count > self.error_threshold:
            alerts.append(
                ("CRITICAL", f"{spider.name}: {self.error_count} errors. Reason: {reason}")
            )

        anomaly = self._detect_anomaly(spider)
        if anomaly:
            alerts.append(("WARNING", anomaly))

        if alerts and self.from_addr and self._password:
            self._send_email(spider.name, alerts)

    def _detect_anomaly(self, spider) -> str | None:
        import json
        from pathlib import Path

        metrics_path = Path(self.metrics_dir) / "metrics.json"
        if not metrics_path.exists():
            return None

        data = json.loads(metrics_path.read_text())
        runs = [r for r in data["runs"] if r["spider"] == spider.name]
        if len(runs) < 3:
            return None

        current = runs[-1]
        historical = runs[-11:-1]

        avg_items = sum(r["items"] for r in historical) / len(historical)
        current_items = current.get("items", 0)
        current_errors = current.get("errors", 0)

        issues = []

        if avg_items > 0 and current_items < avg_items * 0.5:
            issues.append(
                f"items {current_items} vs avg {avg_items:.0f} "
                f"(-{100 - int(current_items / avg_items * 100)}%)"
            )

        if current_errors > 5:
            issues.append(f"errors {current_errors}")

        if current.get("status") != "finished":
            issues.append(f"status={current.get('status')}")

        if issues:
            return f"{spider.name}: {', '.join(issues)}"
        return None

    def _send_email(self, spider_name, alerts):
        import smtplib
        from email.mime.text import MIMEText

        is_critical = any(a[0] == "CRITICAL" for a in alerts)
        subject = f"[Scrapper] {spider_name} — {'CRITICAL' if is_critical else 'Warning'}"
        body = "\n".join(f"[{level}] {msg}" for level, msg in alerts)
        body += "\n\nDashboard: metrics/dashboard.html"

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = self.to_addr

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.from_addr, self._password)
                server.send_message(msg)
            logger.info(f"Alert email sent to {self.to_addr}")
        except Exception as e:
            logger.error(f"Failed to send alert email: {e}")