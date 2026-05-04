# Monitoring Dashboard & RAG Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add metrics persistence + local HTML dashboard, and RAG-ready Markdown/JSONL export pipelines to the scrapper.

**Architecture:** Two new extensions (`StatsLogger` modified to persist metrics, `MetricsDashboard` to generate HTML) and two new pipelines (`MarkdownExportPipeline`, `ChunkedJSONPipeline`) following existing Scrapy signal/pipeline patterns. No new dependencies.

**Tech Stack:** Python 3.12+, Scrapy, yaml (stdlib), hashlib (stdlib), json (stdlib), pathlib (stdlib)

---

### Task 1: Modify StatsLogger to persist metrics

**Files:**
- Modify: `src/scrapper/extensions.py`
- Modify: `tests/unit/test_extensions.py`

- [ ] **Step 1: Write failing tests for metrics persistence**

Add to `tests/unit/test_extensions.py`:

```python
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_extensions.py::TestStatsLoggerMetrics -v`
Expected: FAIL with errors about unexpected keyword arguments or missing attributes

- [ ] **Step 3: Modify StatsLogger to accept and use metrics params**

Modify `src/scrapper/extensions.py` — replace the `StatsLogger` class:

```python
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

        logger.info(
            f"[{spider.name}] Spider closed: {reason} | "
            f"(items={items}, elapsed={elapsed:.1f}s, "
            f"rate={items/elapsed*60:.1f}/min if elapsed else 0)"
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
            "rate_per_minute": round(items / elapsed * 60, 1) if elapsed else 0,
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_extensions.py -v`
Expected: all 9 tests PASS (3 existing + 6 new)

- [ ] **Step 5: Run existing tests to verify no regressions**

Run: `pytest tests/ -v`
Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add src/scrapper/extensions.py tests/unit/test_extensions.py
git commit -m "feat(extensions): persist crawl metrics to metrics.json"
```

---

### Task 2: Add MetricsDashboard extension

**Files:**
- Create: `src/scrapper/dashboard.py`
- Create: `tests/unit/test_dashboard.py`

- [ ] **Step 1: Write failing test for MetricsDashboard**

Create `tests/unit/test_dashboard.py`:

```python
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

    def test_build_dashboard_no_crash_on_missing_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ext = MetricsDashboard(metrics_dir=tmpdir)
            ext._build_dashboard()

            dashboard = Path(tmpdir) / "dashboard.html"
            assert dashboard.exists()
            content = dashboard.read_text()
            assert "No metrics data yet" in content.lower() or "const METRICS = " in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_dashboard.py -v`
Expected: FAIL with module not found

- [ ] **Step 3: Implement MetricsDashboard**

Create `src/scrapper/dashboard.py`:

```python
"""Generate a local HTML dashboard from persisted crawl metrics."""
import json
from datetime import datetime, timezone
from pathlib import Path

from scrapy import signals
from loguru import logger


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
        metrics_path = Path(self.metrics_dir) / "metrics.json"
        if not metrics_path.exists():
            data = {"runs": [], "generated_at": datetime.now(timezone.utc).isoformat()}
        else:
            data = json.loads(metrics_path.read_text())
            data["generated_at"] = datetime.now(timezone.utc).isoformat()

        html = _render_html(data)
        dashboard_path = Path(self.metrics_dir) / "dashboard.html"
        dashboard_path.write_text(html)
        logger.info(f"Dashboard written to {dashboard_path}")


def _render_html(data: dict) -> str:
    data_json = json.dumps(data, indent=2)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scrapper Dashboard</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'SF Mono', 'Fira Code', monospace; background: #0d1117; color: #c9d1d9; padding: 24px; }}
  h1 {{ font-size: 20px; color: #58a6ff; margin-bottom: 20px; }}
  .cards {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 28px; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px 20px; min-width: 140px; }}
  .card .label {{ font-size: 11px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; }}
  .card .value {{ font-size: 28px; font-weight: 600; color: #f0f6fc; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 28px; }}
  th {{ text-align: left; padding: 8px 12px; font-size: 11px; color: #8b949e; text-transform: uppercase; border-bottom: 1px solid #30363d; cursor: pointer; user-select: none; }}
  th:hover {{ color: #58a6ff; }}
  td {{ padding: 8px 12px; font-size: 13px; border-bottom: 1px solid #21262d; }}
  tr:hover td {{ background: #1c2128; }}
  .status-finished {{ color: #3fb950; }}
  .status-failed {{ color: #f85149; }}
  .status-cancelled {{ color: #d29922; }}
  .chart-section {{ margin-bottom: 28px; }}
  .chart-section h2 {{ font-size: 14px; color: #8b949e; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .bar-row {{ display: flex; align-items: center; margin-bottom: 6px; }}
  .bar-label {{ width: 120px; font-size: 12px; color: #c9d1d9; text-align: right; padding-right: 12px; flex-shrink: 0; }}
  .bar-track {{ flex: 1; background: #21262d; border-radius: 3px; height: 20px; overflow: hidden; }}
  .bar-fill {{ background: #58a6ff; height: 100%; border-radius: 3px; min-width: 2px; transition: width 0.3s; }}
  .bar-value {{ width: 50px; font-size: 11px; color: #8b949e; padding-left: 8px; flex-shrink: 0; }}
  .no-data {{ color: #8b949e; font-style: italic; padding: 40px 0; text-align: center; }}
</style>
</head>
<body>
<h1>&#9670; Scrapper Dashboard</h1>
<div class="cards" id="cards"></div>
<table id="runs-table">
  <thead>
    <tr>
      <th onclick="sortTable(0)">Spider</th>
      <th onclick="sortTable(1)">Date</th>
      <th onclick="sortTable(2)">Items</th>
      <th onclick="sortTable(3)">Responses</th>
      <th onclick="sortTable(4)">Errors</th>
      <th onclick="sortTable(5)">Duration</th>
      <th onclick="sortTable(6)">Status</th>
    </tr>
  </thead>
  <tbody id="runs-body"></tbody>
</table>
<div class="chart-section">
  <h2>Error Rate by Spider</h2>
  <div id="error-chart"></div>
</div>
<div class="no-data" id="no-data" style="display:none">No metrics data yet. Run a spider to populate.</div>
<script>
const METRICS = {data_json};

(function() {{
  if (!METRICS.runs || METRICS.runs.length === 0) {{
    document.getElementById('no-data').style.display = 'block';
    return;
  }}

  var runs = METRICS.runs;
  var totalItems = runs.reduce(function(s, r) {{ return s + (r.items || 0); }}, 0);
  var totalRuns = runs.length;
  var finishedRuns = runs.filter(function(r) {{ return r.status === 'finished'; }}).length;
  var successRate = totalRuns > 0 ? Math.round(finishedRuns / totalRuns * 100) : 0;
  var spiders = [];
  runs.forEach(function(r) {{ if (spiders.indexOf(r.spider) === -1) spiders.push(r.spider); }});

  document.getElementById('cards').innerHTML =
    '<div class="card"><div class="label">Total Runs</div><div class="value">' + totalRuns + '</div></div>' +
    '<div class="card"><div class="label">Items Scraped</div><div class="value">' + totalItems + '</div></div>' +
    '<div class="card"><div class="label">Success Rate</div><div class="value">' + successRate + '%</div></div>' +
    '<div class="card"><div class="label">Spiders</div><div class="value">' + spiders.length + '</div></div>';

  var tbody = document.getElementById('runs-body');
  runs.slice().reverse().forEach(function(r) {{
    var row = '<tr>' +
      '<td>' + r.spider + '</td>' +
      '<td>' + r.finished_at.slice(0, 16).replace('T', ' ') + '</td>' +
      '<td>' + (r.items || 0) + '</td>' +
      '<td>' + (r.responses || 0) + '</td>' +
      '<td>' + (r.errors || 0) + '</td>' +
      '<td>' + (r.elapsed_seconds || 0).toFixed(1) + 's</td>' +
      '<td class="status-' + r.status + '">' + r.status + '</td>' +
      '</tr>';
    tbody.innerHTML += row;
  }});

  var errorBySpider = {{}};
  runs.forEach(function(r) {{
    errorBySpider[r.spider] = errorBySpider[r.spider] || {{ errors: 0, responses: 0 }};
    errorBySpider[r.spider].errors += (r.errors || 0);
    errorBySpider[r.spider].responses += (r.responses || 0);
  }});
  var maxErrorRate = 0;
  Object.keys(errorBySpider).forEach(function(s) {{
    var rate = errorBySpider[s].responses > 0 ? Math.round(errorBySpider[s].errors / errorBySpider[s].responses * 100) : 0;
    errorBySpider[s].rate = rate;
    if (rate > maxErrorRate) maxErrorRate = rate;
  }});
  var chart = document.getElementById('error-chart');
  Object.keys(errorBySpider).forEach(function(s) {{
    var d = errorBySpider[s];
    var w = maxErrorRate > 0 ? Math.round(d.rate / maxErrorRate * 100) : 0;
    chart.innerHTML += '<div class="bar-row"><span class="bar-label">' + s + '</span><div class="bar-track"><div class="bar-fill" style="width:' + w + '%"></div></div><span class="bar-value">' + d.rate + '%</span></div>';
  }});

  window.sortTable = function(col) {{
    var rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort(function(a, b) {{
      var va = a.cells[col].textContent.trim();
      var vb = b.cells[col].textContent.trim();
      var na = parseFloat(va), nb = parseFloat(vb);
      if (!isNaN(na) && !isNaN(nb)) return nb - na;
      return va.localeCompare(vb);
    }});
    rows.forEach(function(r) {{ tbody.appendChild(r); }});
  }};
}})();
</script>
</body>
</html>"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_dashboard.py -v`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/dashboard.py tests/unit/test_dashboard.py
git commit -m "feat(dashboard): add MetricsDashboard extension with HTML output"
```

---

### Task 3: Add MarkdownExportPipeline

**Files:**
- Create: `src/scrapper/rag_export.py`
- Create: `tests/unit/test_rag_export.py`

- [ ] **Step 1: Write failing tests for MarkdownExportPipeline**

Create `tests/unit/test_rag_export.py`:

```python
import json
import tempfile
from pathlib import Path
from scrapper.items import PostItem, ProductItem
from scrapper.rag_export import MarkdownExportPipeline, ChunkedJSONPipeline


class FakeSpider:
    name = "test_spider"


class TestMarkdownExportPipeline:
    def test_open_spider_creates_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = MarkdownExportPipeline(output_dir=tmpdir)
            pipe.open_spider(FakeSpider())
            assert Path(tmpdir, "posts").exists()
            assert Path(tmpdir, "products").exists()

    def test_process_item_writes_markdown_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = MarkdownExportPipeline(output_dir=tmpdir)
            pipe.open_spider(FakeSpider())
            item = PostItem(
                site="reddit",
                url="https://old.reddit.com/r/Python/comments/abc123",
                title="How I Learned Python!",
                author="r/PythonLearning",
                content="This is the post content.",
                score=42,
                comment_count=10,
            )
            result = pipe.process_item(item, FakeSpider())
            assert result is item

            files = list(Path(tmpdir, "posts").glob("*.md"))
            assert len(files) == 1
            content = files[0].read_text()
            assert "---" in content
            assert "site: reddit" in content
            assert "title: \"How I Learned Python!\"" in content
            assert "source_type: social_media" in content
            assert "# How I Learned Python!" in content
            assert "This is the post content." in content

    def test_markdown_content_none_uses_title_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = MarkdownExportPipeline(output_dir=tmpdir)
            pipe.open_spider(FakeSpider())
            item = PostItem(
                site="reddit",
                url="https://example.com/post",
                title="No Content Post",
                content=None,
            )
            pipe.process_item(item, FakeSpider())
            files = list(Path(tmpdir, "posts").glob("*.md"))
            content = files[0].read_text()
            assert "# No Content Post" in content
            # Body should only have title, no extra content
            body = content.split("---\n")[-1]
            assert body.strip() == "# No Content Post"

    def test_markdown_slug_from_title(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = MarkdownExportPipeline(output_dir=tmpdir)
            pipe.open_spider(FakeSpider())
            item = PostItem(
                site="reddit",
                url="https://example.com/1",
                title="How I Learned Python!",
            )
            pipe.process_item(item, FakeSpider())
            files = list(Path(tmpdir, "posts").glob("*.md"))
            assert "how_i_learned_python" in files[0].stem

    def test_markdown_slug_collision_appends_number(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = MarkdownExportPipeline(output_dir=tmpdir)
            pipe.open_spider(FakeSpider())
            post_dir = Path(tmpdir, "posts")
            post_dir.mkdir(parents=True, exist_ok=True)
            (post_dir / "reddit-how_i_learned_python.md").write_text("existing")

            item1 = PostItem(
                site="reddit",
                url="https://example.com/1",
                title="How I Learned Python!",
            )
            item2 = PostItem(
                site="reddit",
                url="https://example.com/2",
                title="How I Learned Python!",
            )
            pipe.process_item(item1, FakeSpider())
            pipe.process_item(item2, FakeSpider())

            files = [f.name for f in post_dir.glob("*.md")]
            assert "reddit-how_i_learned_python.md" in files
            assert "reddit-how_i_learned_python-2.md" in files

    def test_product_item_gets_product_listing_source_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = MarkdownExportPipeline(output_dir=tmpdir)
            pipe.open_spider(FakeSpider())
            item = ProductItem(
                site="hotmart",
                url="https://hotmart.com/product/1",
                title="Test Product",
                price=29.99,
                currency="USD",
                rating=4.5,
                review_count=100,
                seller="Test Seller",
            )
            pipe.process_item(item, FakeSpider())
            files = list(Path(tmpdir, "products").glob("*.md"))
            content = files[0].read_text()
            assert "source_type: product_listing" in content
            assert "price: 29.99" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_rag_export.py::TestMarkdownExportPipeline -v`
Expected: FAIL with module not found

- [ ] **Step 3: Implement MarkdownExportPipeline**

Create `src/scrapper/rag_export.py`:

```python
"""RAG-ready export pipelines: Markdown files and JSONL chunks for vector DB ingestion."""
import hashlib
import json
from pathlib import Path

from loguru import logger

from .items import PostItem
from .utils import slugify


class MarkdownExportPipeline:
    """Convert each scraped item to a Markdown file with YAML frontmatter."""

    def __init__(self, output_dir: str = "rag_output"):
        self.output_dir = Path(output_dir)
        self._collision_counters: dict[str, int] = {}

    def open_spider(self, spider):
        posts_dir = self.output_dir / "posts"
        products_dir = self.output_dir / "products"
        posts_dir.mkdir(parents=True, exist_ok=True)
        products_dir.mkdir(parents=True, exist_ok=True)
        self._collision_counters = {}
        logger.info(f"Markdown export dirs ready: {self.output_dir}")

    def close_spider(self, spider):
        self._collision_counters = {}

    def process_item(self, item, spider):
        is_post = isinstance(item, PostItem)
        site = item.get("site", "unknown")
        folder = "posts" if is_post else "products"
        source_type = "social_media" if is_post else "product_listing"

        title = item.get("title", "untitled")
        raw_slug = slugify(title).replace("_", "-").lower()[:80].strip("-")
        slug = raw_slug or "untitled"

        target_dir = self.output_dir / folder / site
        target_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{site}-{slug}.md"
        filepath = target_dir / filename

        if filepath.exists():
            counter_key = str(filepath)
            count = self._collision_counters.get(counter_key, 1) + 1
            self._collision_counters[counter_key] = count
            filename = f"{site}-{slug}-{count}.md"
            filepath = target_dir / filename

        frontmatter = self._build_frontmatter(item, source_type)
        content = item.get("content") or ""
        body = f"# {title}\n\n{content}" if content else f"# {title}"
        md = f"---\n{frontmatter}---\n\n{body}\n"

        filepath.write_text(md)
        return item

    def _build_frontmatter(self, item, source_type: str) -> str:
        data = dict(item)
        data["source_type"] = source_type

        lines = []
        for key in ("site", "url", "title", "author", "score", "comments",
                     "price", "currency", "rating", "review_count", "seller",
                     "scraped_at", "source_type"):
            val = data.get(key)
            if val is None:
                continue
            if isinstance(val, str) and _needs_quoting(val):
                lines.append(f'{key}: "{val}"')
            else:
                lines.append(f"{key}: {val}")
        return "\n".join(lines) + "\n"


def _needs_quoting(val: str) -> bool:
    return any(c in val for c in ':{}[]&*?|><#%"\'@`\n') or val.startswith(" ") or val.endswith(" ")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_rag_export.py::TestMarkdownExportPipeline -v`
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/rag_export.py tests/unit/test_rag_export.py
git commit -m "feat(rag): add MarkdownExportPipeline for RAG-ready .md files"
```

---

### Task 4: Add ChunkedJSONPipeline

**Files:**
- Modify: `src/scrapper/rag_export.py`
- Modify: `tests/unit/test_rag_export.py`

- [ ] **Step 1: Write failing tests for ChunkedJSONPipeline**

Add to `tests/unit/test_rag_export.py`:

```python
class TestChunkedJSONPipeline:
    def test_open_spider_creates_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = ChunkedJSONPipeline(output_dir=tmpdir)
            pipe.open_spider(FakeSpider())
            assert Path(tmpdir, "chunks.jsonl").exists() is False  # created on first write

    def test_process_item_writes_jsonl_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = ChunkedJSONPipeline(output_dir=tmpdir)
            pipe.open_spider(FakeSpider())
            item = PostItem(
                site="reddit",
                url="https://old.reddit.com/r/Python/comments/abc123",
                title="Test Title",
                content="Test content.",
                score=5,
                comment_count=3,
            )
            result = pipe.process_item(item, FakeSpider())
            pipe.close_spider(FakeSpider())
            assert result is item

            lines = Path(tmpdir, "chunks.jsonl").read_text().strip().split("\n")
            assert len(lines) == 1
            chunk = json.loads(lines[0])
            assert "chunk_id" in chunk
            assert chunk["chunk_id"].startswith("reddit-")
            assert len(chunk["chunk_id"].split("-")[1]) == 8
            assert chunk["text"].startswith("# Test Title")
            assert "Test content." in chunk["text"]
            assert chunk["metadata"]["site"] == "reddit"
            assert chunk["metadata"]["score"] == 5
            assert chunk["metadata"]["source_type"] == "social_media"
            assert "content" not in chunk["metadata"]

    def test_appends_multiple_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = ChunkedJSONPipeline(output_dir=tmpdir)
            pipe.open_spider(FakeSpider())
            pipe.process_item(PostItem(site="reddit", url="https://x.com/1", title="One"))
            pipe.process_item(PostItem(site="reddit", url="https://x.com/2", title="Two"))
            pipe.close_spider(FakeSpider())

            lines = Path(tmpdir, "chunks.jsonl").read_text().strip().split("\n")
            assert len(lines) == 2

    def test_content_none_handled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = ChunkedJSONPipeline(output_dir=tmpdir)
            pipe.open_spider(FakeSpider())
            item = PostItem(
                site="reddit",
                url="https://x.com/1",
                title="No Content",
                content=None,
            )
            pipe.process_item(item, FakeSpider())
            pipe.close_spider(FakeSpider())

            lines = Path(tmpdir, "chunks.jsonl").read_text().strip().split("\n")
            chunk = json.loads(lines[0])
            assert chunk["text"] == "# No Content"
            assert "content" not in chunk["metadata"]

    def test_chunk_id_is_deterministic(self):
        pipe = ChunkedJSONPipeline()
        item = PostItem(site="reddit", url="https://same-url.com", title="Same")
        chunk_id1 = pipe._build_chunk(item)
        chunk_id2 = pipe._build_chunk(item)
        assert chunk_id1 == chunk_id2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_rag_export.py::TestChunkedJSONPipeline -v`
Expected: FAIL with ChunkedJSONPipeline not found or method missing

- [ ] **Step 3: Implement ChunkedJSONPipeline**

Add to `src/scrapper/rag_export.py` (after `MarkdownExportPipeline`):

```python
class ChunkedJSONPipeline:
    """Export items as JSONL chunks optimized for vector DB ingestion."""

    def __init__(self, output_dir: str = "rag_output"):
        self.output_dir = Path(output_dir)
        self._file = None

    def open_spider(self, spider):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"JSONL export ready: {self.output_dir}")

    def close_spider(self, spider):
        if self._file:
            self._file.close()
            self._file = None

    def process_item(self, item, spider):
        chunk = self._build_chunk(item)
        if self._file is None:
            self._file = open(self.output_dir / "chunks.jsonl", "a")
        self._file.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        self._file.flush()
        return item

    def _build_chunk(self, item) -> dict:
        is_post = isinstance(item, PostItem)
        source_type = "social_media" if is_post else "product_listing"
        url = item.get("url", "")
        chunk_id = hashlib.sha256(url.encode()).hexdigest()[:8]
        if not url:
            # Fallback: hash the title
            chunk_id = hashlib.sha256(item.get("title", "").encode()).hexdigest()[:8]

        site = item.get("site", "unknown")
        title = item.get("title", "untitled")
        content = item.get("content") or ""

        text = f"# {title}" + (f"\n\n{content}" if content else "")

        metadata = dict(item)
        metadata["source_type"] = source_type
        metadata.pop("content", None)

        return {
            "chunk_id": f"{site}-{chunk_id}",
            "text": text,
            "metadata": metadata,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_rag_export.py -v`
Expected: 11 tests PASS (6 Markdown + 5 ChunkedJSON)

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/rag_export.py tests/unit/test_rag_export.py
git commit -m "feat(rag): add ChunkedJSONPipeline for vector DB ingestion"
```

---

### Task 5: Update settings.py — register new components

**Files:**
- Modify: `src/scrapper/settings.py`
- Modify: `tests/unit/test_settings.py` (verify new settings exist)

- [ ] **Step 1: Write failing test for new settings**

Add to `tests/unit/test_settings.py`:

```python
def test_metrics_dir_default():
    from scrapper import settings
    assert settings.METRICS_DIR == "metrics"


def test_metrics_max_runs_default():
    from scrapper import settings
    assert settings.METRICS_MAX_RUNS == 100


def test_rag_export_settings_exist():
    from scrapper import settings
    assert hasattr(settings, "RAG_EXPORT_ENABLED")
    assert hasattr(settings, "RAG_OUTPUT_DIR")
    assert settings.RAG_OUTPUT_DIR == "rag_output"


def test_dashboard_extension_registered():
    from scrapper import settings
    assert "scrapper.dashboard.MetricsDashboard" in settings.EXTENSIONS


def test_rag_pipelines_registered():
    from scrapper import settings
    pipelines = settings.ITEM_PIPELINES
    assert "scrapper.rag_export.MarkdownExportPipeline" in pipelines
    assert "scrapper.rag_export.ChunkedJSONPipeline" in pipelines
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_settings.py::test_metrics_dir_default tests/unit/test_settings.py::test_metrics_max_runs_default tests/unit/test_settings.py::test_rag_export_settings_exist tests/unit/test_settings.py::test_dashboard_extension_registered tests/unit/test_settings.py::test_rag_pipelines_registered -v`
Expected: FAIL with AttributeError

- [ ] **Step 3: Update settings.py**

Modify `src/scrapper/settings.py` — add after line 75 (after `ALERT_WEBHOOK_URL`):

```python
# ── Metrics persistence ──────────────────
METRICS_DIR = "metrics"
METRICS_MAX_RUNS = 100

# ── RAG-ready export ─────────────────────
RAG_EXPORT_ENABLED = os.getenv("RAG_EXPORT_ENABLED", "true").lower() in ("true", "1", "yes")
RAG_OUTPUT_DIR = "rag_output"
```

Add `MetricsDashboard` to `EXTENSIONS` dict (after line 68):

```python
EXTENSIONS = {
    "scrapper.extensions.StatsLogger": 400,
    "scrapper.extensions.ErrorAlerter": 500,
    "scrapper.dashboard.MetricsDashboard": 600,
}
```

Add RAG pipelines conditionally (after the `ITEM_PIPELINES` block at line 57):

```python
ITEM_PIPELINES = {
    "scrapper.pipelines.ValidatePipeline": 100,
    "scrapper.pipelines.DedupInMemoryPipeline": 200,
    "scrapper.pipelines.SupabasePipeline": 300,
}

if RAG_EXPORT_ENABLED:
    ITEM_PIPELINES["scrapper.rag_export.MarkdownExportPipeline"] = 400
    ITEM_PIPELINES["scrapper.rag_export.ChunkedJSONPipeline"] = 450
```

Note: `RAG_EXPORT_ENABLED` must be defined before the `ITEM_PIPELINES` conditional block. Move the env var section before the pipeline registration.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_settings.py -v`
Expected: all new settings tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/settings.py tests/unit/test_settings.py
git commit -m "feat(settings): register dashboard extension and RAG pipelines"
```

---

### Task 6: Integration verification and cleanup

**Files:** None new

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: all tests pass, including existing tests unchanged

- [ ] **Step 2: Run Reddit spider to verify end-to-end**

```bash
scrapy crawl reddit -a query="python" -a limit=3 -s ROBOTSTXT_OBEY=False
```

Verify output:
- `metrics/metrics.json` exists with new run entry
- `metrics/dashboard.html` exists and opens in browser
- `rag_output/posts/reddit/` contains `.md` files
- `rag_output/chunks.jsonl` contains lines

- [ ] **Step 3: Run Hotmart spider to verify both spiders work**

```bash
scrapy crawl hotmart -a query="marketing" -a limit=3 -s ROBOTSTXT_OBEY=False
```

Verify:
- `metrics/metrics.json` has entries for both spiders
- `rag_output/products/hotmart/` contains `.md` files

- [ ] **Step 4: Test RAG disable via env var**

```bash
RAG_EXPORT_ENABLED=false scrapy crawl reddit -a query="test" -a limit=1 -s ROBOTSTXT_OBEY=False
```

Verify:
- `rag_output/` not created (or no new files if already exists)
- `metrics/` still updated (metrics are independent of RAG toggle)

- [ ] **Step 5: Final commit if any cleanup needed**

```bash
git status
```
