#!/usr/bin/env python3
"""Wrapper que ejecuta el spider Reddit en GitHub Actions.

Lee queries desde la variable de entorno REDDIT_QUERIES (JSON array),
itera cada query con scrapy crawl, reintentos por query.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def parse_queries() -> list[dict]:
    """Lee REDDIT_QUERIES del entorno y valida JSON."""
    raw = os.getenv("REDDIT_QUERIES", "").strip()
    if not raw:
        print("ERROR: REDDIT_QUERIES no definida", file=sys.stderr)
        sys.exit(1)
    try:
        queries = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: REDDIT_QUERIES no es JSON válido: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(queries, list):
        print("ERROR: REDDIT_QUERIES debe ser un array JSON", file=sys.stderr)
        sys.exit(1)
    return queries


def build_scrapy_args(q: dict) -> list[str]:
    """Convierte un dict de query a argumentos -a para scrapy crawl."""
    args = []
    for k in ("subreddit", "query", "limit"):
        if k in q:
            args.extend(["-a", f"{k}={q[k]}"])
    return args


def run_with_retries(cmd: list[str], max_retries: int = 3, timeout: int = 300) -> bool:
    """Ejecuta un comando con reintentos y backoff exponencial."""
    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            backoff = 5 * (2 ** (attempt - 2))  # 5, 10, 20
            print(f"Reintento {attempt}/{max_retries} tras {backoff}s...")
            time.sleep(backoff)

        print(f"Ejecutando (intento {attempt}): {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, timeout=timeout)
            if result.returncode == 0:
                return True
            print(f"Scrapy terminó con código {result.returncode}")
        except subprocess.TimeoutExpired:
            print(f"Timeout de {timeout}s alcanzado")

    return False


def main() -> None:
    # Crear directorios que settings.py espera
    for d in ("logs", "metrics"):
        Path(d).mkdir(parents=True, exist_ok=True)

    queries = parse_queries()
    failed = []

    for q in queries:
        if not isinstance(q, dict):
            print(f"WARNING: saltando query no-dict: {q!r}", file=sys.stderr)
            continue
        scrapy_args = build_scrapy_args(q)
        cmd = [
            sys.executable,
            "-m",
            "scrapy",
            "crawl",
            "reddit",
            "-s",
            "ROBOTSTXT_OBEY=False",
            "-s",
            "CONCURRENT_REQUESTS=4",
            "-s",
            "AUTOTHROTTLE_TARGET_CONCURRENCY=2.0",
        ] + scrapy_args
        success = run_with_retries(cmd, max_retries=4, timeout=300)
        if not success:
            label = q.get("subreddit", "unknown")
            print(f"FALLÓ (tras 4 intentos): r/{label}")
            failed.append(label)

    if failed:
        print(f"Queries fallidas: {failed}")
        sys.exit(1)

    print("Todas las queries completadas exitosamente.")
    sys.exit(0)


if __name__ == "__main__":
    main()
