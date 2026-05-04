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
import re
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


def _scrapyd_conf(spider, cron, i, args_str):
    """Build a scrapyd.conf schedule line."""
    return (
        f"{spider}_{i} = {cron} {PROJECT} {spider} "
        f"{args_str} "
        f"-s ROBOTSTXT_OBEY=False"
    )


def main():
    queries = json.loads(QUERIES_FILE.read_text())

    crontab_lines = []
    conf_lines = []

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
                args_str = f'-a query="{query}" -a limit={limit}'
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
                args_str = f'-a url="{url}" -a type={task_type}'
                print(f"  [{spider}] {cron} url={url!r} type={task_type!r}")

            crontab_lines.append(_crontab_curl(spider, cron, params))
            conf_lines.append(_scrapyd_conf(spider, cron, i, args_str))

    CRONTAB_FILE.write_text("\n".join(crontab_lines) + "\n")
    print(f"[generator] Wrote {len(crontab_lines)} cron jobs to crontab.txt")

    # Also update scrapyd.conf schedule section for visibility (Scrapyd ignores it)
    conf_path = Path(__file__).parent / "scrapyd.conf"
    conf = conf_path.read_text()
    conf = re.sub(
        r"\[schedule\].*",
        "[schedule]\n" + "\n".join(conf_lines) + "\n",
        conf,
        flags=re.DOTALL,
    )
    conf_path.write_text(conf)


if __name__ == "__main__":
    main()
