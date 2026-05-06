#!/usr/bin/env python3
"""Runner para Google Cloud Run Jobs.

Ejecuta todas las queries de un spider desde queries.json.
Diseñado para entornos SIN disco persistente (Cloud Run Jobs).

Uso:
    python cloud_run_runner.py reddit           # ejecuta solo reddit
    python cloud_run_runner.py hotmart          # ejecuta solo hotmart
    python cloud_run_runner.py                  # ejecuta todos los spiders
    python cloud_run_runner.py reddit --dry-run # muestra sin ejecutar

Variables de entorno requeridas:
    SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
import signal
import time

_child = None
_terminate = False


def _handle_signal(signum, frame):
    """Forward termination signals to the scrapy subprocess and wait for graceful shutdown."""
    global _terminate
    sig_name = signal.Signals(signum).name
    _log(f"Recibido {sig_name}, propagando a scrapy...")
    _terminate = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

QUERIES_FILE = Path(__file__).parent / "queries.json"


def _log(msg: str):
    ts = datetime.now(timezone.utc).isoformat()
    print(f"[{ts}] {msg}", flush=True)


def run_spider(spider: str, args: dict, dry_run: bool = False) -> bool:
    """Ejecuta scrapy crawl con los argumentos dados."""
    global _child, _terminate

    if dry_run:
        arg_str = " ".join(f"{k}={v}" for k, v in args.items())
        _log(f"[DRY-RUN] scrapy crawl {spider} {arg_str}")
        return True

    cmd = [
        sys.executable, "-m", "scrapy", "crawl", spider,
        "-s", "ROBOTSTXT_OBEY=False",
        "-s", "RAG_EXPORT_ENABLED=false",
        "-s", "COOKIE_PERSIST_ENABLED=false",
    ]
    for k, v in args.items():
        cmd += ["-a", f"{k}={v}"]

    _log(f"Ejecutando: {' '.join(cmd)}")
    _child = subprocess.Popen(cmd)
    _terminate = False

    while _child.poll() is None:
        if _terminate:
            _log("Enviando SIGTERM a scrapy...")
            _child.terminate()
            try:
                _child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                _log("Scrapy no terminó en 15s, forzando kill...")
                _child.kill()
                _child.wait()
            break
        time.sleep(0.5)

    success = _child.returncode == 0
    _child = None
    _terminate = False
    return success


def main():
    parser = argparse.ArgumentParser(description="Cloud Run spider runner")
    parser.add_argument("spider", nargs="?", help="Spider a ejecutar (reddit, hotmart, generic)")
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra, no ejecuta")
    args_cli = parser.parse_args()

    # Validar variables requeridas
    required = ["SUPABASE_URL", "SUPABASE_KEY", "OPENAI_API_KEY"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        _log(f"ERROR: Faltan variables de entorno: {', '.join(missing)}")
        sys.exit(1)

    if not QUERIES_FILE.exists():
        _log(f"ERROR: No encontré {QUERIES_FILE}")
        sys.exit(1)

    queries = json.loads(QUERIES_FILE.read_text())

    # Filtrar spiders
    if args_cli.spider:
        if args_cli.spider not in queries:
            _log(f"ERROR: Spider '{args_cli.spider}' no existe en queries.json")
            sys.exit(1)
        targets = {args_cli.spider: queries[args_cli.spider]}
    else:
        targets = queries

    total = 0
    ok = 0

    for spider, config in targets.items():
        items = config.get("queries") or config.get("tasks") or []
        _log(f"Procesando spider '{spider}' ({len(items)} tareas)")

        for item in items:
            total += 1

            if "query" in item:
                query = item["query"]
                limit = item.get("limit", 10)
                run_args = {"query": query, "limit": str(limit)}
                label = f'{spider} q="{query}" limit={limit}'
            else:
                url = item["url"]
                task_type = item.get("type", "article")
                run_args = {"url": url, "type": task_type}
                label = f'{spider} url="{url}" type={task_type}'

            _log(f"Iniciando {label}")
            success = run_spider(spider, run_args, dry_run=args_cli.dry_run)
            if success:
                ok += 1
                _log(f"OK: {label}")
            else:
                _log(f"FALLÓ: {label}")

    if args_cli.dry_run:
        _log(f"DRY-RUN completado. Se ejecutarían {total} tareas en {len(targets)} spiders.")
    else:
        _log(f"Resumen: {ok}/{total} ejecuciones exitosas")

    if ok < total:
        sys.exit(1)  # Cloud Run puede reintentar el job


if __name__ == "__main__":
    main()
