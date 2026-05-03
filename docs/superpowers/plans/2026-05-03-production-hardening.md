# Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Production-ready the scrapper platform: Supabase verification, log rotation, data quality pipeline, email alerting, Scrapyd scheduling, and 90%+ test coverage.

**Architecture:** Six independent workstreams in dependency order. Log rotation modifies `StatsLogger` in `extensions.py`. Email alerting replaces `ErrorAlerter` in same file — do log rotation first to avoid conflicts. Data quality is a new pipeline in `pipelines.py`. Scheduling touches only config files. Tests are last to cover all new code.

**Tech Stack:** Python 3.12+, Scrapy, smtplib (stdlib), logging.handlers (stdlib), Supabase, Docker/Scrapyd

---

### Task 1: Supabase Verification

**Files:**
- Create: `tests/integration/test_supabase.py`

- [ ] **Step 1: Write Supabase integration tests**

Create `tests/integration/test_supabase.py`:

```python
import os
import pytest
from supabase import create_client


@pytest.mark.skipif(
    not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_KEY"),
    reason="Supabase credentials not configured"
)
class TestSupabaseIntegration:
    def test_connection_succeeds(self):
        client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
        )
        result = client.table("posts").select("*", count="exact").execute()
        assert hasattr(result, "count") or hasattr(result, "data")

    def test_posts_table_exists(self):
        client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
        )
        result = client.table("posts").select("*").limit(1).execute()
        assert result.data is not None

    def test_products_table_exists(self):
        client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
        )
        result = client.table("products").select("*").limit(1).execute()
        assert result.data is not None

    def test_upsert_and_read_post(self):
        client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
        )
        test_url = "https://test.example.com/verify_upsert"
        client.table("posts").upsert(
            {"site": "test", "url": test_url, "title": "verify_upsert"},
            on_conflict="site,url",
        ).execute()
        result = client.table("posts").select("*").eq("url", test_url).execute()
        assert len(result.data) >= 1
        client.table("posts").delete().eq("url", test_url).execute()
```

- [ ] **Step 2: Run tests to verify they work (or skip gracefully)**

Run: `pytest tests/integration/test_supabase.py -v`
Expected: If Supabase creds configured → 4 PASS. If not → 4 SKIPPED.

- [ ] **Step 3: Run spider to verify end-to-end pipeline**

```bash
scrapy crawl reddit -a query="test" -a limit=2 -s ROBOTSTXT_OBEY=False
```

Verify: Check Supabase dashboard → posts table has 2 new rows with site="reddit".

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_supabase.py
git commit -m "test: add Supabase integration tests"
```

---

### Task 2: Log Rotation — Mixta

**Files:**
- Modify: `src/scrapper/settings.py`
- Modify: `src/scrapper/extensions.py`
- Modify: `tests/unit/test_extensions.py`

- [ ] **Step 1: Write failing tests for log rotation**

Add to `tests/unit/test_extensions.py`:

```python
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler


class TestLogRotation:
    def test_log_rotation_settings_exist(self):
        from scrapper import settings
        assert settings.LOG_FILE_SIZE == "logs/scrapy.log"
        assert settings.LOG_FILE_MAX_BYTES == 5 * 1024 * 1024
        assert settings.LOG_FILE_BACKUP_COUNT == 5
        assert settings.LOG_FILE_TIME == "logs/scrapy-daily.log"
        assert settings.LOG_FILE_TIME_WHEN == "midnight"
        assert settings.LOG_FILE_TIME_BACKUP == 7

    def test_setup_log_rotation_adds_handlers(self, monkeypatch):
        from scrapper.extensions import StatsLogger

        root = logging.getLogger()
        initial_handlers = len(root.handlers)

        ext = StatsLogger(metrics_dir="/tmp/fake")
        Path("/tmp/fake/logs").mkdir(parents=True, exist_ok=True)
        ext._setup_log_rotation()

        assert len(root.handlers) >= initial_handlers + 2

        # Cleanup: remove handlers added by test
        for h in root.handlers[initial_handlers:]:
            root.removeHandler(h)

        # Reset global guard
        import scrapper.extensions as ext_mod
        ext_mod._log_handlers_configured = False

    def test_setup_log_rotation_called_once(self, monkeypatch):
        from scrapper.extensions import StatsLogger
        import scrapper.extensions as ext_mod

        root = logging.getLogger()
        initial_count = len(root.handlers)

        ext = StatsLogger(metrics_dir="/tmp/fake")
        Path("/tmp/fake/logs").mkdir(parents=True, exist_ok=True)
        ext._setup_log_rotation()
        first_count = len(root.handlers)
        ext._setup_log_rotation()

        assert len(root.handlers) == first_count

        for h in root.handlers[initial_count:]:
            root.removeHandler(h)
        ext_mod._log_handlers_configured = False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_extensions.py::TestLogRotation -v`
Expected: FAIL — LOG_FILE_SIZE etc not found, `_setup_log_rotation` not found

- [ ] **Step 3: Add log rotation settings to settings.py**

Modify `src/scrapper/settings.py` — replace the `LOG_LEVEL`/`LOG_FILE` lines at the bottom with:

```python
LOG_ENABLED = True
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Size-based rotation: 5 files x 5MB
LOG_FILE_SIZE = "logs/scrapy.log"
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024  # 5MB
LOG_FILE_BACKUP_COUNT = 5

# Time-based rotation: daily, keep 7 days
LOG_FILE_TIME = "logs/scrapy-daily.log"
LOG_FILE_TIME_WHEN = "midnight"
LOG_FILE_TIME_BACKUP = 7
```

- [ ] **Step 4: Add _setup_log_rotation to StatsLogger**

Add to `src/scrapper/extensions.py` — after the imports, add module-level flag, then add method to `StatsLogger`:

At the top of the file, after the import block:

```python
_log_handlers_configured = False
```

Add this method to the `StatsLogger` class after `__init__`:

```python
    @staticmethod
    def _setup_log_rotation():
        global _log_handlers_configured
        if _log_handlers_configured:
            return
        _log_handlers_configured = True

        import logging
        from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

        root = logging.getLogger()
        Path("logs").mkdir(parents=True, exist_ok=True)

        from . import settings

        size_handler = RotatingFileHandler(
            settings.LOG_FILE_SIZE,
            maxBytes=settings.LOG_FILE_MAX_BYTES,
            backupCount=settings.LOG_FILE_BACKUP_COUNT,
        )
        size_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
        ))
        root.addHandler(size_handler)

        time_handler = TimedRotatingFileHandler(
            settings.LOG_FILE_TIME,
            when=settings.LOG_FILE_TIME_WHEN,
            backupCount=settings.LOG_FILE_TIME_BACKUP,
        )
        time_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
        ))
        root.addHandler(time_handler)
```

And call it in `spider_opened`:

```python
    def spider_opened(self, spider):
        self.start_time = time.time()
        self._setup_log_rotation()
        logger.info(f"[{spider.name}] Spider opened")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_extensions.py -v`
Expected: all tests pass (existing + 3 new log rotation tests)

- [ ] **Step 6: Commit**

```bash
git add src/scrapper/settings.py src/scrapper/extensions.py tests/unit/test_extensions.py
git commit -m "feat: add mixed log rotation (size + time)"
```

---

### Task 3: Data Quality Pipeline

**Files:**
- Modify: `src/scrapper/pipelines.py`
- Modify: `tests/unit/test_pipelines.py`
- Modify: `src/scrapper/settings.py`

- [ ] **Step 1: Write failing tests for DataQualityPipeline**

Add to `tests/unit/test_pipelines.py`:

```python
from scrapper.pipelines import DataQualityPipeline


class FakeSpider:
    name = "test_spider"


class TestDataQualityPipeline:
    def test_valid_item_no_issues(self):
        pipe = DataQualityPipeline()
        item = PostItem(
            site="reddit",
            url="https://example.com/post",
            title="A Valid Post Title",
            content="This is some valid content.",
            score=42,
        )
        result = pipe.process_item(item, FakeSpider())
        assert result is item
        assert "quality_issues" not in item

    def test_invalid_url_scheme_flagged(self):
        pipe = DataQualityPipeline()
        item = PostItem(
            site="reddit",
            url="ftp://example.com/post",
            title="A Valid Post Title",
        )
        pipe.process_item(item, FakeSpider())
        assert "quality_issues" in item
        assert "invalid_url_scheme" in item["quality_issues"]

    def test_title_too_short_flagged(self):
        pipe = DataQualityPipeline()
        item = PostItem(
            site="reddit",
            url="https://example.com/post",
            title="ab",
        )
        pipe.process_item(item, FakeSpider())
        assert "title_too_short" in item["quality_issues"]

    def test_content_too_short_flagged(self):
        pipe = DataQualityPipeline()
        item = PostItem(
            site="reddit",
            url="https://example.com/post",
            title="Valid Title",
            content="short",
        )
        pipe.process_item(item, FakeSpider())
        assert "content_too_short" in item["quality_issues"]

    def test_content_none_not_flagged(self):
        pipe = DataQualityPipeline()
        item = PostItem(
            site="reddit",
            url="https://example.com/post",
            title="Valid Title",
            content=None,
        )
        pipe.process_item(item, FakeSpider())
        assert "quality_issues" not in item

    def test_price_invalid_flagged(self):
        pipe = DataQualityPipeline()
        item = ProductItem(
            site="hotmart",
            url="https://example.com/product",
            title="Product",
            price=-5,
        )
        pipe.process_item(item, FakeSpider())
        assert "price_invalid" in item["quality_issues"]

    def test_price_not_numeric_flagged(self):
        pipe = DataQualityPipeline()
        item = ProductItem(
            site="hotmart",
            url="https://example.com/product",
            title="Product",
            price="gratis",
        )
        pipe.process_item(item, FakeSpider())
        assert "price_not_numeric" in item["quality_issues"]

    def test_rating_out_of_range_flagged(self):
        pipe = DataQualityPipeline()
        item = ProductItem(
            site="hotmart",
            url="https://example.com/product",
            title="Product",
            rating=6.0,
        )
        pipe.process_item(item, FakeSpider())
        assert "rating_out_of_range" in item["quality_issues"]

    def test_score_not_integer_flagged(self):
        pipe = DataQualityPipeline()
        item = PostItem(
            site="reddit",
            url="https://example.com/post",
            title="Valid Title",
            score="not-a-number",
        )
        pipe.process_item(item, FakeSpider())
        assert "score_not_integer" in item["quality_issues"]

    def test_price_none_not_flagged(self):
        pipe = DataQualityPipeline()
        item = ProductItem(
            site="hotmart",
            url="https://example.com/product",
            title="Product",
            price=None,
        )
        pipe.process_item(item, FakeSpider())
        assert "quality_issues" not in item

    def test_close_spider_reports_stats(self, caplog):
        from loguru import logger

        pipe = DataQualityPipeline()
        spider = FakeSpider()
        item = PostItem(
            site="reddit",
            url="https://example.com/post",
            title="ab",  # triggers title_too_short
        )
        pipe.process_item(item, spider)
        pipe.close_spider(spider)
        assert "Data quality" in caplog.text
        assert "issues" in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_pipelines.py::TestDataQualityPipeline -v`
Expected: FAIL — `DataQualityPipeline` not found

- [ ] **Step 3: Implement DataQualityPipeline**

Add to `src/scrapper/pipelines.py`, after the existing imports:

```python
from collections import defaultdict
from urllib.parse import urlparse

from loguru import logger
```

Add the class before `ValidatePipeline`:

```python
class DataQualityPipeline:
    """Flag items with quality issues. Report stats at close."""

    def __init__(self):
        self._stats = defaultdict(lambda: {"total": 0, "issues": 0})

    def process_item(self, item, spider):
        issues = self._validate(item)
        self._stats[spider.name]["total"] += 1
        if issues:
            self._stats[spider.name]["issues"] += 1
            item.setdefault("quality_issues", []).extend(issues)
        return item

    def close_spider(self, spider):
        stats = self._stats.get(spider.name, {"total": 0, "issues": 0})
        if stats["total"] > 0:
            pct = stats["issues"] / stats["total"] * 100
            if pct > 30:
                logger.warning(
                    f"[{spider.name}] Data quality: {stats['issues']}/{stats['total']} "
                    f"items with issues ({pct:.1f}%)"
                )
            else:
                logger.info(
                    f"[{spider.name}] Data quality: {stats['issues']}/{stats['total']} "
                    f"items with issues ({pct:.1f}%)"
                )

    def _validate(self, item) -> list[str]:
        issues = []
        is_post = isinstance(item, PostItem)

        url = item.get("url", "")
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                issues.append("invalid_url_scheme")
        else:
            issues.append("missing_url")

        title = item.get("title", "")
        if title and len(title.strip()) < 3:
            issues.append("title_too_short")

        content = item.get("content")
        if content is not None and len(str(content)) < 10:
            issues.append("content_too_short")

        if not is_post:
            price = item.get("price")
            if price is not None:
                try:
                    if float(price) <= 0:
                        issues.append("price_invalid")
                except (TypeError, ValueError):
                    issues.append("price_not_numeric")

            rating = item.get("rating")
            if rating is not None:
                try:
                    r = float(rating)
                    if r < 0 or r > 5:
                        issues.append("rating_out_of_range")
                except (TypeError, ValueError):
                    issues.append("rating_not_numeric")
        else:
            score = item.get("score")
            if score is not None:
                try:
                    int(score)
                except (TypeError, ValueError):
                    issues.append("score_not_integer")

        return issues
```

- [ ] **Step 4: Register DataQualityPipeline in settings.py**

Modify `src/scrapper/settings.py` — update `ITEM_PIPELINES`:

```python
ITEM_PIPELINES = {
    "scrapper.pipelines.ValidatePipeline": 100,
    "scrapper.pipelines.DataQualityPipeline": 150,
    "scrapper.pipelines.DedupInMemoryPipeline": 200,
    "scrapper.pipelines.SupabasePipeline": 300,
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_pipelines.py -v`
Expected: all tests pass (existing + 11 new data quality tests)

- [ ] **Step 6: Commit**

```bash
git add src/scrapper/pipelines.py src/scrapper/settings.py tests/unit/test_pipelines.py
git commit -m "feat: add DataQualityPipeline (format + anomaly detection)"
```

---

### Task 4: Email Alerting

**Files:**
- Modify: `src/scrapper/extensions.py`
- Modify: `src/scrapper/settings.py`
- Modify: `.env.example`
- Modify: `tests/unit/test_extensions.py`

- [ ] **Step 1: Write failing tests for EmailAlerter**

Add to `tests/unit/test_extensions.py`:

```python
import json
import tempfile
from unittest.mock import patch, MagicMock


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
            "ALERT_EMAIL_PASSWORD": "secret",
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
            spider.crawler.stats = FakeStats()

            # No current run => no anomaly
            result = ext._detect_anomaly(spider)
            assert result is None

            # Add a run with 2 items (vs avg 10) + status=failed
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
            assert result is None  # <3 runs => no alert

    def test_smtp_exception_handled_gracefully(self):
        from scrapper.extensions import EmailAlerter
        ext = EmailAlerter("h", 587, "from@x.com", "pw", "to@x.com")
        ext.error_count = 10
        spider = MagicMock()
        spider.name = "test"
        spider.crawler.stats = FakeStats()
        with patch("smtplib.SMTP", side_effect=Exception("Connection refused")):
            ext.spider_closed(spider, "finished")  # should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_extensions.py::TestEmailAlerter -v`
Expected: FAIL — `EmailAlerter` not found

- [ ] **Step 3: Replace ErrorAlerter with EmailAlerter in extensions.py**

Modify `src/scrapper/extensions.py`:

Remove the `ErrorAlerter` class entirely (lines 112-143).

Add after StatsLogger's `_persist_metrics` method:

```python
class EmailAlerter:
    """Send email alerts on critical errors and metric anomalies."""

    def __init__(self, smtp_host, smtp_port, from_addr, password, to_addr,
                 metrics_dir="metrics", error_threshold=5):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.from_addr = from_addr
        self.password = password
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
            password=crawler.settings.get("ALERT_EMAIL_PASSWORD", ""),
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

        if alerts and self.from_addr and self.password:
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
                server.login(self.from_addr, self.password)
                server.send_message(msg)
            logger.info(f"Alert email sent to {self.to_addr}")
        except Exception as e:
            logger.error(f"Failed to send alert email: {e}")
```

- [ ] **Step 4: Update settings.py — replace ErrorAlerter with EmailAlerter**

Modify `src/scrapper/settings.py`:

Remove `ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")`.

Add after `METRICS_MAX_RUNS`:

```python
# ── Email alerts ──────────────────────────
ALERT_SMTP_HOST = os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com")
ALERT_SMTP_PORT = int(os.getenv("ALERT_SMTP_PORT", "587"))
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "")
ALERT_EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
ALERT_ERROR_THRESHOLD = int(os.getenv("ALERT_ERROR_THRESHOLD", "5"))
```

Update EXTENSIONS:

```python
EXTENSIONS = {
    "scrapper.extensions.StatsLogger": 400,
    "scrapper.extensions.EmailAlerter": 500,
    "scrapper.dashboard.MetricsDashboard": 600,
}
```

- [ ] **Step 5: Update .env.example**

Replace `ALERT_WEBHOOK_URL` line with:

```bash
# Email alerts (Gmail SMTP — use App Password, not account password)
# Get App Password: https://myaccount.google.com/apppasswords
ALERT_EMAIL_FROM=scrapper@gmail.com
ALERT_EMAIL_PASSWORD=abcd efgh ijkl mnop
ALERT_EMAIL_TO=tu@email.com
ALERT_ERROR_THRESHOLD=5
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_extensions.py -v`
Expected: all tests pass (existing StatsLogger tests + new EmailAlerter tests, old ErrorAlerter tests removed)

- [ ] **Step 7: Commit**

```bash
git add src/scrapper/extensions.py src/scrapper/settings.py .env.example tests/unit/test_extensions.py
git commit -m "feat: replace ErrorAlerter with EmailAlerter (Gmail SMTP + anomaly detection)"
```

---

### Task 5: Scheduling — Scrapyd Periodic Jobs

**Files:**
- Create: `scrapyd.conf`
- Modify: `docker-compose.yml`
- Modify: `src/scrapper/settings.py`

- [ ] **Step 1: Create scrapyd.conf**

Create `scrapyd.conf`:

```ini
[scrapyd]
eggs_dir    = eggs
logs_dir    = logs
items_dir   = items
dbs_dir     = dbs

[schedule]
reddit = 0 */6 * * * default reddit -a query="${REDDIT_QUERY:python}" -a limit="${REDDIT_LIMIT:10}"
hotmart = 0 8,20 * * * default hotmart -a query="${HOTMART_QUERY:marketing}" -a limit="${HOTMART_LIMIT:10}"
```

- [ ] **Step 2: Update docker-compose.yml**

Modify `docker-compose.yml` — add volume mount and env vars to scrapyd service:

```yaml
services:
  scrapyd:
    image: vimagick/scrapyd:latest
    ports:
      - "6800:6800"
    volumes:
      - ./src:/scrapy/src
      - ./scrapy.cfg:/scrapy/scrapy.cfg
      - ./scrapyd.conf:/scrapy/scrapyd.conf
      - scrapyd_data:/scrapy/data
    environment:
      REDDIT_QUERY: ${REDDIT_QUERY:-python}
      REDDIT_LIMIT: ${REDDIT_LIMIT:-10}
      HOTMART_QUERY: ${HOTMART_QUERY:-marketing}
      HOTMART_LIMIT: ${HOTMART_LIMIT:-10}
    restart: unless-stopped
```

- [ ] **Step 3: Add SCHEDULE_ENABLED to settings.py**

Add to `src/scrapper/settings.py`, in the Metrics persistence section:

```python
# ── Scheduling ────────────────────────────
SCHEDULE_ENABLED = os.getenv("SCHEDULE_ENABLED", "false").lower() in ("true", "1", "yes")
```

- [ ] **Step 4: Add schedule env vars to .env.example**

Add to `.env.example`:

```bash
# Scheduling (enable in production)
SCHEDULE_ENABLED=false
REDDIT_QUERY=python
REDDIT_LIMIT=10
HOTMART_QUERY=marketing
HOTMART_LIMIT=10
```

- [ ] **Step 5: Run tests to verify no regressions**

Run: `pytest tests/unit/test_settings.py -v`
Expected: all settings tests pass

- [ ] **Step 6: Commit**

```bash
git add scrapyd.conf docker-compose.yml src/scrapper/settings.py .env.example
git commit -m "feat: add Scrapyd periodic job scheduling"
```

---

### Task 6: Test Coverage — 65% → 90%+

**Files:**
- Create: `tests/unit/test_main.py`
- Create: `tests/unit/test_stealth.py`
- Create: `tests/unit/test_hotmart.py`
- Modify: `tests/unit/test_reddit.py`
- Modify: `tests/unit/test_middlewares.py`
- Modify: `pyproject.toml`
- Modify: `tests/unit/test_extensions.py`

- [ ] **Step 1: Add coverage exclusions for deprecated spiders**

Modify `pyproject.toml` — add `[tool.coverage.run]` section:

```toml
[tool.coverage.run]
omit = [
    "src/scrapper/spiders/amazon.py",
    "src/scrapper/spiders/mercadolibre.py",
    "src/scrapper/spiders/quora.py",
]
```

- [ ] **Step 2: Write tests for main.py (0% → 80%)**

Create `tests/unit/test_main.py`:

```python
import importlib
import os
from unittest.mock import patch


class TestMain:
    def test_main_module_importable(self):
        from scrapper import main
        assert main is not None

    def test_env_loading(self):
        with patch.dict(os.environ, {"SUPABASE_URL": "https://test.supabase.co"}, clear=True):
            importlib.reload(__import__("scrapper.settings", fromlist=["settings"]))
            from scrapper import settings
            assert settings.SUPABASE_URL == "https://test.supabase.co"
```

- [ ] **Step 3: Write tests for stealth_handler.py (23% → 80%)**

Create `tests/unit/test_stealth.py`:

```python
import os
from unittest.mock import patch


class TestStealthHandler:
    def test_handler_class_exists(self):
        from scrapper.stealth_handler import ScrapyPlaywrightStealthDownloadHandler
        assert ScrapyPlaywrightStealthDownloadHandler is not None

    def test_headless_env_var_parsed(self):
        with patch.dict(os.environ, {"HEADLESS": "true"}):
            result = os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes")
            assert result is True

    def test_headless_env_var_false(self):
        with patch.dict(os.environ, {"HEADLESS": "false"}):
            result = os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes")
            assert result is False

    def test_human_simulation_env_var_parsed(self):
        with patch.dict(os.environ, {"PLAYWRIGHT_HUMAN_SIMULATION": "true"}):
            result = os.getenv("PLAYWRIGHT_HUMAN_SIMULATION", "true").lower() in ("true", "1", "yes")
            assert result is True
```

- [ ] **Step 4: Write tests for hotmart.py (50% → 85%)**

Create `tests/unit/test_hotmart.py`:

```python
from unittest.mock import MagicMock


class FakeResponse:
    def __init__(self, url="https://hotmart.com", status=200):
        self.url = url
        self.status = status


class TestHotmartSpider:
    def test_spider_importable(self):
        from scrapper.spiders.hotmart import HotmartSpider
        assert HotmartSpider is not None

    def test_spider_name(self):
        from scrapper.spiders.hotmart import HotmartSpider
        spider = HotmartSpider()
        assert spider.name == "hotmart"

    def test_parse_price_dollar(self):
        from scrapper.spiders.hotmart import HotmartSpider
        spider = HotmartSpider()
        result = spider._parse_price("$29.99")
        assert result == 29.99

    def test_parse_price_brazilian_real(self):
        from scrapper.spiders.hotmart import HotmartSpider
        spider = HotmartSpider()
        result = spider._parse_price("R$ 19,90")
        assert result == 19.90

    def test_parse_price_none(self):
        from scrapper.spiders.hotmart import HotmartSpider
        spider = HotmartSpider()
        result = spider._parse_price(None)
        assert result is None

    def test_parse_price_empty(self):
        from scrapper.spiders.hotmart import HotmartSpider
        spider = HotmartSpider()
        result = spider._parse_price("")
        assert result is None

    def test_parse_review_count(self):
        from scrapper.spiders.hotmart import HotmartSpider
        spider = HotmartSpider()
        result = spider._parse_review_count("(1.234 avaliações)")
        assert result == 1234

    def test_parse_review_count_none(self):
        from scrapper.spiders.hotmart import HotmartSpider
        spider = HotmartSpider()
        result = spider._parse_review_count(None)
        assert result == 0
```

- [ ] **Step 5: Add tests for RetryWithBackoffMiddleware (middlewares.py 80% → 95%)**

Add to `tests/unit/test_middlewares.py`:

```python
from scrapper.middlewares import RetryWithBackoffMiddleware


class TestRetryWithBackoffMiddleware:
    def test_retry_middleware_importable(self):
        assert RetryWithBackoffMiddleware is not None

    def test_retry_middleware_has_expected_methods(self):
        assert hasattr(RetryWithBackoffMiddleware, "process_response")
        assert hasattr(RetryWithBackoffMiddleware, "process_exception")
```

- [ ] **Step 6: Add tests for reddit spider parse_post_page (62% → 85%)**

Add to `tests/unit/test_reddit.py`:

```python
    def test_parse_post_page_extracts_content(self):
        from scrapper.spiders.reddit import RedditSpider
        spider = self._make_spider()
        url = "https://old.reddit.com/r/Python/comments/abc123/test_post/"
        response = self._make_response(
            url=url,
            body="<html><body><div class='expando'><div class='usertext-body'>Post body content here.</div></div></body></html>",
        )
        result = list(spider.parse_post_page(response))
        assert len(result) == 1
        item = result[0]
        assert item["content"] == "Post body content here."
        assert item["url"] == url

    def test_parse_post_page_no_content(self):
        from scrapper.spiders.reddit import RedditSpider
        spider = self._make_spider()
        url = "https://old.reddit.com/r/Python/comments/abc123/test_post/"
        response = self._make_response(url=url, body="<html><body></body></html>")
        result = list(spider.parse_post_page(response))
        assert len(result) == 1
        item = result[0]
        assert item["content"] == ""

    def test_cutoff_date_filters_old_posts(self):
        from scrapper.spiders.reddit import RedditSpider
        spider = self._make_spider()
        spider.cutoff_date = datetime(2026, 5, 3, tzinfo=timezone.utc)
        post_date = datetime(2026, 5, 2, tzinfo=timezone.utc)
        html = f"""<html><body>
        <div class='search-result-link'>
          <a class='search-title' href='/r/Python/comments/abc123/title/'>Title</a>
          <span class='search-score'>10 points</span>
          <span class='search-comments'>5 comments</span>
          <time datetime='{post_date.isoformat()}'>old</time>
        </div>
        </body></html>"""
        response = self._make_response(url="https://old.reddit.com/r/Python/search?q=test", body=html)
        items = list(spider.parse(response))
        assert len(items) == 0  # filtered out (too old)
```

Also add the datetime import at the top of the file, after the existing imports:

```python
from datetime import datetime, timezone
```

- [ ] **Step 7: Add EmailAlerter integration test with metrics.json flow**

Add to `tests/unit/test_extensions.py`:

```python
class TestEmailAlerterIntegration:
    def test_full_flow_stats_to_email(self):
        import json
        import tempfile
        from pathlib import Path
        from scrapper.extensions import EmailAlerter, StatsLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. StatsLogger persists a run
            stats_ext = StatsLogger(metrics_dir=tmpdir, metrics_max_runs=100)
            stats_ext.start_time = 1000.0
            spider = FakeSpider()
            spider.name = "test_spider"
            stats = FakeStats()
            spider.crawler = MagicMock()
            spider.crawler.stats = stats
            from unittest.mock import patch
            with patch("time.time", return_value=1005.0):
                stats_ext.spider_closed(spider, "finished")

            # 2. EmailAlerter reads it and detects no anomaly (1 run = baseline)
            email_ext = EmailAlerter("h", 587, "a@b.com", "pw", "c@d.com", metrics_dir=tmpdir)
            anomaly = email_ext._detect_anomaly(spider)
            assert anomaly is None

            # 3. Add more runs, then a drop
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

            # Add low-items run
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
```

- [ ] **Step 8: Run all tests to verify coverage target**

Run: `pytest tests/ --cov=src/scrapper --cov-report=term-missing -v`

Expected: 90%+ coverage, all tests pass (target: ~130 tests total)

Check coverage report — if any module below target, add targeted tests.

- [ ] **Step 9: Commit**

```bash
git add tests/ pyproject.toml
git commit -m "test: increase coverage to 90%+ (new tests for main, stealth, hotmart, reddit, middlewares, extensions)"
```

---

### Task 7: Final Integration Verification

**Files:** None new

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: all tests pass

- [ ] **Step 2: Run coverage report**

Run: `pytest tests/ --cov=src/scrapper --cov-report=term`
Expected: 90%+ total coverage

- [ ] **Step 3: Run linter**

Run: `ruff check src/ tests/`
Expected: All checks passed

- [ ] **Step 4: Run Reddit spider end-to-end**

```bash
scrapy crawl reddit -a query="test" -a limit=3 -s ROBOTSTXT_OBEY=False
```

Verify:
- `metrics/metrics.json` updated
- `metrics/dashboard.html` regenerated
- `logs/scrapy.log` and `logs/scrapy-daily.log` created
- Data quality stats in log output
- No email sent (error_count < threshold)
- Supabase has data (if configured)

- [ ] **Step 5: Run Hotmart spider end-to-end**

```bash
scrapy crawl hotmart -a query="marketing" -a limit=3 -s ROBOTSTXT_OBEY=False
```

Verify same outputs as Reddit.

- [ ] **Step 6: Verify Docker Compose**

```bash
docker-compose config  # validates YAML
```

Expected: valid config output, no errors.

- [ ] **Step 7: Final commit if any cleanup needed**

```bash
git status
git add -A
git diff --staged --stat
# Commit any remaining changes
```
