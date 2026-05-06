#!/usr/bin/env python3
"""Ejecuta spiders localmente desde queries.json sin Docker ni Scrapyd.

Guarda resultados con timestamp para no perder ejecuciones anteriores.
Uso:
    python runner_local.py              # ejecuta todas las queries
    python runner_local.py --spider reddit   # solo reddit
    python runner_local.py --dry-run    # muestra qué ejecutaría
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

QUERIES_FILE = Path(__file__).parent / "queries.json"
OUTPUT_DIR = Path(__file__).parent / "output"


def run_spider(spider: str, args: dict, output_path: Path | None = None):
    """Ejecuta scrapy crawl con los argumentos dados."""
    cmd = [
        sys.executable, "-m", "scrapy", "crawl", spider,
        "-s", "ROBOTSTXT_OBEY=False",
    ]
    for k, v in args.items():
        cmd += ["-a", f"{k}={v}"]

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd += ["-o", str(output_path)]

    print(f"\n[runner] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False, text=True)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Runner local de spiders")
    parser.add_argument("--spider", help="Ejecutar solo este spider (ej: reddit)")
    parser.add_argument("--dry-run", action="store_true", help="No ejecutar, solo mostrar")
    parser.add_argument("--append", action="store_true", help="Usar un solo archivo JSONL acumulativo")
    args_cli = parser.parse_args()

    if not QUERIES_FILE.exists():
        print(f"[runner] ERROR: No encontré {QUERIES_FILE}")
        sys.exit(1)

    queries = json.loads(QUERIES_FILE.read_text())

    # Timestamp de esta sesión
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    total = 0
    ok = 0

    for spider, config in queries.items():
        if args_cli.spider and spider != args_cli.spider:
            continue

        cron = config.get("schedule", "manual")
        items = config.get("queries") or config.get("tasks") or []

        for item in items:
            total += 1

            if "query" in item:
                # reddit / hotmart
                query = item["query"]
                limit = item.get("limit", 10)
                run_args = {"query": query, "limit": str(limit)}
                label = f'{spider} q="{query}" limit={limit}'
            else:
                # generic
                url = item["url"]
                task_type = item.get("type", "article")
                run_args = {"url": url, "type": task_type}
                label = f'{spider} url="{url}" type={task_type}'

            if args_cli.dry_run:
                print(f"[dry-run] {label}  (cron: {cron})")
                continue

            if args_cli.append:
                # Un solo archivo JSONL acumulativo por spider
                out = OUTPUT_DIR / f"{spider}_history.jsonl"
            else:
                # Archivo único por ejecución
                safe_label = query.replace(" ", "_").replace("/", "_") if "query" in item else "task"
                out = OUTPUT_DIR / f"{ts}" / f"{spider}_{safe_label}.json"

            print(f"\n{'='*60}")
            print(f"[runner] Ejecutando {label}")
            print(f"[runner] Output: {out}")
            print(f"{'='*60}")

            success = run_spider(spider, run_args, output_path=out)
            if success:
                ok += 1
                print(f"[runner] OK: {label}")
            else:
                print(f"[runner] FALLÓ: {label}")

    if not args_cli.dry_run:
        print(f"\n[runner] Resumen: {ok}/{total} ejecuciones exitosas")
        print(f"[runner] Resultados en: {OUTPUT_DIR.absolute()}")
    else:
        print(f"\n[dry-run] Se ejecutarían {total} tareas")


if __name__ == "__main__":
    main()
