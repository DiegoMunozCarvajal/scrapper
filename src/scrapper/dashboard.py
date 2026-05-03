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
        Path(self.metrics_dir).mkdir(parents=True, exist_ok=True)
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
