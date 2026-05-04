#!/usr/bin/env python3
"""Generate crontab from queries.json to trigger spiders via Scrapyd API.

Scrapyd 1.6.0 ignores the [schedule] section in scrapyd.conf,
so we use system cron to POST to /schedule.json.
"""

import json
import re
from pathlib import Path

QUERIES_FILE = Path(__file__).parent / "queries.json"
CRONTAB_FILE = Path(__file__).parent / "crontab.txt"
PROJECT = "scrapper"
API_URL = "http://localhost:6800/schedule.json"


def main():
    queries = json.loads(QUERIES_FILE.read_text())

    lines = []
    for spider, config in queries.items():
        cron = config["schedule"]
        for i, q in enumerate(config["queries"], 1):
            query = q["query"]
            limit = q.get("limit", 10)
            # Use --data-urlencode so curl handles encoding (no % in crontab)
            curl_cmd = (
                f'{cron} curl -s -X POST "{API_URL}" '
                f'--data-urlencode "project={PROJECT}" '
                f'--data-urlencode "spider={spider}" '
                f'--data-urlencode "query={query}" '
                f'--data-urlencode "limit={limit}" '
                f'--data-urlencode "setting=ROBOTSTXT_OBEY=False" '
                f">> /app/logs/cron.log 2>&1"
            )
            lines.append(curl_cmd)
            print(f"  [{spider}] {cron} query={query!r} limit={limit}")

    crontab = "\n".join(lines) + "\n"
    CRONTAB_FILE.write_text(crontab)
    print(f"[generator] Wrote {len(lines)} cron jobs to crontab.txt")

    # Also update scrapyd.conf schedule section for visibility (Scrapyd ignores it)
    conf_path = Path(__file__).parent / "scrapyd.conf"
    conf = conf_path.read_text()
    schedule_lines = []
    for spider, config in queries.items():
        cron = config["schedule"]
        for i, q in enumerate(config["queries"], 1):
            job_name = f"{spider}_{i}"
            query = q["query"]
            limit = q.get("limit", 10)
            schedule_lines.append(
                f'{job_name} = {cron} {PROJECT} {spider} '
                f'-a query="{query}" -a limit={limit} '
                f'-s ROBOTSTXT_OBEY=False'
            )
    conf = re.sub(
        r"\[schedule\].*",
        "[schedule]\n" + "\n".join(schedule_lines) + "\n",
        conf,
        flags=re.DOTALL,
    )
    conf_path.write_text(conf)


if __name__ == "__main__":
    main()
