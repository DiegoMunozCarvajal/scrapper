#!/usr/bin/env python3
"""Generate crontab from queries.json to trigger spiders via Scrapyd API.

Scrapyd 1.6.0 ignores the [schedule] section in scrapyd.conf,
so we use system cron to POST to /schedule.json.

Supports two spider configurations:
  - "queries" key: {"query": "...", "limit": N} → reddit, hotmart
  - "tasks" key:   {"url": "...", "type": "..."} → generic
"""

import json
import os
from pathlib import Path

QUERIES_FILE = Path(__file__).parent / "queries.json"
CRONTAB_FILE = Path(__file__).parent / "crontab.txt"
PROJECT = "scrapper"
API_URL = os.getenv("SCRAPYD_API_URL", "http://localhost:6800/schedule.json")


def _crontab_curl(spider, cron, params, log_file="/app/logs/cron.log"):
    """Build a crontab line with curl POST to Scrapyd."""
    args = " ".join(
        f'--data-urlencode "{k}={v}"'
        for k, v in params.items()
    )
    return (
        f'{cron} curl -s -X POST "{API_URL}" '
        f'{args} '
        f">> {log_file} 2>&1"
    )


def main():
    queries = json.loads(QUERIES_FILE.read_text())

    crontab_lines = []

    for spider, config in queries.items():
        cron = config["schedule"]

        items = config.get("queries") or config.get("tasks") or []
        for i, item in enumerate(items, 1):
            if "query" in item:
                # Standard spider (reddit, hotmart)
                query = item["query"]
                limit = item.get("limit", 10)
                params = {
                    "project": PROJECT,
                    "spider": spider,
                    "query": query,
                    "limit": str(limit),
                    "setting": "ROBOTSTXT_OBEY=False",
                }
                print(f"  [{spider}] {cron} query={query!r} limit={limit}")
            else:
                # Generic spider (url + type)
                url = item["url"]
                task_type = item.get("type", "article")
                params = {
                    "project": PROJECT,
                    "spider": spider,
                    "url": url,
                    "type": task_type,
                    "setting": "ROBOTSTXT_OBEY=False",
                }
                print(f"  [{spider}] {cron} url={url!r} type={task_type!r}")

            crontab_lines.append(_crontab_curl(spider, cron, params))

    CRONTAB_FILE.write_text("\n".join(crontab_lines) + "\n")
    print(f"[generator] Wrote {len(crontab_lines)} cron jobs to crontab.txt")


if __name__ == "__main__":
    main()
