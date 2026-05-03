# Production Hardening Design

> **Goal:** Complete the scrapper platform for production: scheduling, alerts, data quality, log rotation, Supabase verification, and test coverage.

**Architecture:** Six independent workstreams. No new dependencies — all changes use stdlib or existing packages. Each stream touches distinct files with minimal overlap.

**Tech Stack:** Python 3.12+, Scrapy, smtplib (stdlib), logging.handlers (stdlib), Supabase, Docker/Scrapyd

---

## 1. Scheduling — Scrapyd Periodic Jobs

**Files:**
- Create: `scrapyd.conf`
- Modify: `docker-compose.yml`

### Config

`scrapyd.conf` mounted as volume into Scrapyd container. Cron-style scheduling:

```ini
[scrapyd]
eggs_dir    = eggs
logs_dir    = logs
items_dir   = items
dbs_dir     = dbs

[schedule]
# Read from env vars: REDDIT_SCHEDULE, REDDIT_QUERY, REDDIT_LIMIT
# Reddit: every 6 hours
reddit = 0 */6 * * * default reddit -a query="${REDDIT_QUERY:python}" -a limit="${REDDIT_LIMIT:10}"

# Hotmart: 8am and 8pm
hotmart = 0 8,20 * * * default hotmart -a query="${HOTMART_QUERY:marketing}" -a limit="${HOTMART_LIMIT:10}"
```

### Docker changes

`docker-compose.yml` updated to mount `scrapyd.conf` and inject env vars:

```yaml
services:
  scrapyd:
    volumes:
      - ./scrapyd.conf:/scrapy/scrapyd.conf
    environment:
      REDDIT_QUERY: ${REDDIT_QUERY:-python}
      REDDIT_LIMIT: ${REDDIT_LIMIT:-10}
      HOTMART_QUERY: ${HOTMART_QUERY:-marketing}
      HOTMART_LIMIT: ${HOTMART_LIMIT:-10}
```

### Disable in dev

```bash
# .env.example addition
SCHEDULE_ENABLED=true
```

Scrapy settings check `SCHEDULE_ENABLED` to conditionally load schedule.

### Verification

```bash
docker-compose up -d
curl http://localhost:6800/listjobs.json?project=default
# Should show scheduled jobs
```

---

## 2. Alerting — Email via Gmail SMTP

**Files:**
- Modify: `src/scrapper/extensions.py`
- Modify: `.env.example`
- Modify: `tests/unit/test_extensions.py`

### Replace ErrorAlerter with EmailAlerter

Remove `ErrorAlerter` (Discord webhook). New `EmailAlerter` uses only `smtplib` (stdlib):

```python
import smtplib
from email.mime.text import MIMEText

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
        return cls(
            smtp_host=crawler.settings.get("ALERT_SMTP_HOST", "smtp.gmail.com"),
            smtp_port=int(crawler.settings.get("ALERT_SMTP_PORT", 587)),
            from_addr=crawler.settings.get("ALERT_EMAIL_FROM", ""),
            password=crawler.settings.get("ALERT_EMAIL_PASSWORD", ""),
            to_addr=crawler.settings.get("ALERT_EMAIL_TO", ""),
            metrics_dir=crawler.settings.get("METRICS_DIR", "metrics"),
            error_threshold=int(crawler.settings.get("ALERT_ERROR_THRESHOLD", 5)),
        )

    def spider_error(self, failure, response, spider):
        self.error_count += 1

    def spider_closed(self, spider, reason):
        alerts = []

        # 1. Critical errors
        if self.error_count > self.error_threshold:
            alerts.append(
                ("CRITICAL", f"{spider.name}: {self.error_count} errors. Reason: {reason}")
            )

        # 2. Anomaly detection vs historical
        anomaly = self._detect_anomaly(spider)
        if anomaly:
            alerts.append(("WARNING", anomaly))

        if alerts and self.from_addr and self.password:
            self._send_email(spider.name, alerts)

    def _detect_anomaly(self, spider) -> str | None:
        """Compare current run vs last 10 runs for this spider."""
        metrics_path = Path(self.metrics_dir) / "metrics.json"
        if not metrics_path.exists():
            return None

        data = json.loads(metrics_path.read_text())
        runs = [r for r in data["runs"] if r["spider"] == spider.name]
        if len(runs) < 3:
            return None

        current = runs[-1]
        historical = runs[-11:-1]  # exclude current run

        avg_items = sum(r["items"] for r in historical) / len(historical)
        avg_errors = sum(r["errors"] for r in historical) / len(historical)
        current_items = current.get("items", 0)
        current_errors = current.get("errors", 0)

        issues = []

        if avg_items > 0 and current_items < avg_items * 0.5:
            issues.append(f"items {current_items} vs avg {avg_items:.0f} (-{100 - int(current_items/avg_items*100)}%)")

        if avg_errors > 0 and current_errors > avg_errors * 1.3:
            # Only flag if increases from non-zero baseline
            pass
        elif current_errors > 5:
            issues.append(f"errors {current_errors}")

        if current.get("status") != "finished":
            issues.append(f"status={current.get('status')}")

        if issues:
            return f"{spider.name}: {', '.join(issues)}"
        return None

    def _send_email(self, spider_name, alerts):
        subject = f"[Scrapper] {spider_name} — {'CRITICAL' if any(a[0]=='CRITICAL' for a in alerts) else 'Warning'}"
        body = "\n".join(f"[{level}] {msg}" for level, msg in alerts)
        body += f"\n\nDashboard: metrics/dashboard.html"

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

### Settings

```python
# src/scrapper/settings.py
ALERT_SMTP_HOST = os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com")
ALERT_SMTP_PORT = int(os.getenv("ALERT_SMTP_PORT", "587"))
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "")
ALERT_EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
ALERT_ERROR_THRESHOLD = int(os.getenv("ALERT_ERROR_THRESHOLD", "5"))

EXTENSIONS = {
    "scrapper.extensions.StatsLogger": 400,
    "scrapper.extensions.EmailAlerter": 500,
    "scrapper.dashboard.MetricsDashboard": 600,
}
```

### .env additions

```bash
ALERT_EMAIL_FROM=scrapper@gmail.com
ALERT_EMAIL_PASSWORD=abcd efgh ijkl mnop
ALERT_EMAIL_TO=tu@email.com
```

---

## 3. Supabase Verification

**Files:**
- Create: `tests/integration/test_supabase.py`
- Possibly create: `scripts/verify_supabase.py`

### What to verify

1. `SUPABASE_URL` and `SUPABASE_KEY` are set and valid
2. Connection succeeds: `create_client(url, key).table("posts").select("*", count="exact").execute()`
3. Tables exist: `posts`, `products`
4. Pipeline works end-to-end: run spider, check data in Supabase

### Test file

```python
# tests/integration/test_supabase.py
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
        assert hasattr(result, 'count') or hasattr(result, 'data')

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
```

---

## 4. Data Quality Pipeline

**Files:**
- Modify: `src/scrapper/pipelines.py`
- Modify: `tests/unit/test_pipelines.py`
- Modify: `src/scrapper/settings.py`

### DataQualityPipeline

New pipeline at priority 150 (between Validate=100 and Dedup=200):

```python
from collections import defaultdict
from urllib.parse import urlparse

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
            level = "WARNING" if pct > 30 else "INFO"
            getattr(logger, level.lower())(
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

### Settings registration

```python
ITEM_PIPELINES = {
    "scrapper.pipelines.ValidatePipeline": 100,
    "scrapper.pipelines.DataQualityPipeline": 150,
    "scrapper.pipelines.DedupInMemoryPipeline": 200,
    "scrapper.pipelines.SupabasePipeline": 300,
}

if RAG_EXPORT_ENABLED:
    ITEM_PIPELINES["scrapper.rag_export.MarkdownExportPipeline"] = 400
    ITEM_PIPELINES["scrapper.rag_export.ChunkedJSONPipeline"] = 450
```

---

## 5. Log Rotation — Mixta (tamaño + tiempo)

**Files:**
- Modify: `src/scrapper/settings.py`
- Modify: `src/scrapper/extensions.py`

### Settings

```python
# settings.py
import os
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

LOG_ENABLED = True
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Size-based: 5 files x 5MB for detailed log
LOG_FILE_SIZE = "logs/scrapy.log"
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024  # 5MB
LOG_FILE_BACKUP_COUNT = 5

# Time-based: daily rotation, keep 7 days
LOG_FILE_TIME = "logs/scrapy-daily.log"
LOG_FILE_TIME_WHEN = "midnight"
LOG_FILE_TIME_BACKUP = 7
```

### StatsLogger configures handlers

`StatsLogger.spider_opened` configures both handlers on the root logger, **once only** (guard against duplicates on multiple spider runs):

```python
_log_handlers_configured = False

def _setup_log_rotation(self):
    global _log_handlers_configured
    if _log_handlers_configured:
        return
    _log_handlers_configured = True

    import logging
    from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

    root = logging.getLogger()
    Path("logs").mkdir(exist_ok=True)

    # Size-based rotation
    size_handler = RotatingFileHandler(
        settings.LOG_FILE_SIZE,
        maxBytes=settings.LOG_FILE_MAX_BYTES,
        backupCount=settings.LOG_FILE_BACKUP_COUNT,
    )
    size_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    ))
    root.addHandler(size_handler)

    # Time-based rotation
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

---

## 6. Test Coverage — 65% → 90%+

**Files:**
- Create: `tests/unit/test_main.py`
- Modify: `tests/unit/test_extensions.py`
- Modify: `tests/unit/test_pipelines.py`
- Create: `tests/unit/test_stealth.py`
- Modify: `tests/unit/test_middlewares.py`
- Modify: `tests/unit/test_reddit.py`
- Create: `tests/integration/test_supabase.py`
- Create: `tests/unit/test_hotmart.py`

### Target per module

| Module | Current | Target | Action |
|--------|---------|--------|--------|
| `main.py` | 0% | 80% | Test CLI entry point, env loading |
| `extensions.py` | 91% | 95% | Test EmailAlerter (anomaly detection, email sending) |
| `pipelines.py` | 74% | 95% | Test DataQualityPipeline, SupabasePipeline error paths |
| `stealth_handler.py` | 23% | 80% | Test handler config, headless toggle |
| `middlewares.py` | 80% | 95% | Test RetryWithBackoffMiddleware retry logic |
| `reddit.py` | 62% | 85% | Test parse_post_page, cutoff_date filtering |
| `hotmart.py` | 50% | 85% | Test pagination, API response parsing edge cases |
| `spiders/__init__.py` | 0% | 100% | Trivial: test import |
| Deprecated spiders | 0% | 0% | Skip (explicitly exclude from coverage) |

### Key test cases

**EmailAlerter:**
- `test_anomaly_detects_item_drop` — items <50% avg triggers alert
- `test_anomaly_no_false_positive_on_low_baseline` — <3 runs = no alert
- `test_email_not_sent_without_credentials`
- `test_email_sent_on_critical_error`
- `test_smtp_exception_handled_gracefully`

**DataQualityPipeline:**
- `test_invalid_url_scheme_flagged`
- `test_price_invalid_flagged`
- `test_rating_out_of_range_flagged`
- `test_score_not_integer_flagged`
- `test_valid_item_no_issues`
- `test_close_spider_reports_stats`

**CLI (main.py):**
- `test_main_module_runnable`
- `test_env_loading`

---

## Implementation Order

1. Supabase verification (quick win, verifies existing infra)
2. Log rotation (simple config change)
3. Data quality pipeline (new code, independent)
4. Email alerting (replaces ErrorAlerter)
5. Scheduling (Scrapyd config)
6. Tests (fill coverage gaps for ALL above)

---

## Verification Checklist

- [ ] `scrapy crawl reddit -a query="test" -a limit=1` runs and:
  - [ ] Metrics persist to `metrics/metrics.json`
  - [ ] Dashboard regenerated
  - [ ] Data quality stats appear in log
  - [ ] Email sent if anomalies detected
  - [ ] Logs rotate correctly (check `logs/` dir)
- [ ] Supabase tables populated with test data
- [ ] `docker-compose up -d` starts scrapyd + scrapydweb
- [ ] Scheduled jobs visible in ScrapydWeb UI at `:5000`
- [ ] `pytest tests/ --cov=src/scrapper --cov-report=term` shows 90%+
