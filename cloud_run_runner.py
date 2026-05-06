#!/usr/bin/env python3
"""Runner para Google Cloud Run Jobs.

Ejecuta todas las queries de un spider desde queries.json.
Diseñado para entornos SIN disco persistente (Cloud Run Jobs).

Cada query tiene timeout individual y reintentos con backoff.
Usa Supabase como lock distribuido para evitar ejecuciones concurrentes.

Uso:
    python cloud_run_runner.py reddit           # ejecuta solo reddit
    python cloud_run_runner.py hotmart          # ejecuta solo hotmart
    python cloud_run_runner.py reddit --dry-run # muestra sin ejecutar

Variables de entorno requeridas:
    SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

QUERIES_FILE = Path(__file__).parent / "queries.json"

PER_QUERY_TIMEOUT = int(os.getenv("PER_QUERY_TIMEOUT", "600"))
MAX_RETRIES_PER_QUERY = int(os.getenv("MAX_RETRIES_PER_QUERY", "3"))
RETRY_BACKOFF_BASE = float(os.getenv("RETRY_BACKOFF_BASE", "5.0"))
LOCK_TTL_SECONDS = int(os.getenv("LOCK_TTL_SECONDS", "1800"))

_child = None
_terminate = False


def _handle_signal(signum, frame):
    global _terminate
    sig_name = signal.Signals(signum).name
    _log(f"Recibido {sig_name}, propagando a scrapy...")
    _terminate = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def _log(msg: str):
    ts = datetime.now(timezone.utc).isoformat()
    print(f"[{ts}] {msg}", flush=True)


def acquire_lock(spider: str) -> bool:
    """Adquiere un lock distribuido atómico en Supabase.

    Usa la tabla 'spider_locks' con clave primaria sobre 'spider' para evitar
    race conditions. Limpia locks expirados antes de intentar insertar.
    """
    try:
        from supabase import create_client

        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_key = os.getenv("SUPABASE_KEY", "")
        if not supabase_url or not supabase_key:
            _log("WARN: Sin credenciales Supabase, omitiendo lock distribuido.")
            return True

        client = create_client(supabase_url, supabase_key)
        now = datetime.now(timezone.utc)
        expires_at = now.timestamp() + LOCK_TTL_SECONDS
        expires_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()
        now_iso = now.isoformat()

        # 1. Limpiar locks expirados
        try:
            client.table("spider_locks").delete().lt("locked_until", now_iso).execute()
        except Exception:
            pass  # Ignorar errores de limpieza

        # 2. Intentar insertar nuestro lock atómicamente
        try:
            client.table("spider_locks").insert({
                "spider": spider,
                "locked_at": now_iso,
                "locked_until": expires_iso,
                "status": "running",
            }).execute()
            _log(f"Lock adquirido para '{spider}' (expira en {LOCK_TTL_SECONDS}s)")
            return True
        except Exception as e:
            err_msg = str(e).lower()
            # Unique violation (23505) u otro error de duplicado indica que ya hay lock
            if "unique" in err_msg or "duplicate" in err_msg or "23505" in err_msg:
                _log(f"Lock ya está en uso para '{spider}', omitiendo ejecución.")
                return False
            raise

    except Exception as e:
        _log(f"WARN: No se pudo adquirir lock en Supabase ({e}), continuando sin lock.")
        return True


def release_lock(spider: str):
    """Libera el lock distribuido al terminar."""
    try:
        from supabase import create_client

        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_key = os.getenv("SUPABASE_KEY", "")
        if not supabase_url or not supabase_key:
            return

        client = create_client(supabase_url, supabase_key)
        client.table("spider_locks").delete().eq("spider", spider).execute()
        _log(f"Lock liberado para '{spider}'")

    except Exception as e:
        _log(f"WARN: No se pudo liberar lock ({e})")


def run_spider(spider: str, args: dict, dry_run: bool = False) -> bool:
    """Ejecuta scrapy crawl con timeout y reintentos por query."""
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

    for attempt in range(1, MAX_RETRIES_PER_QUERY + 1):
        if attempt > 1:
            backoff = RETRY_BACKOFF_BASE * (2 ** (attempt - 2))
            _log(f"Reintento {attempt}/{MAX_RETRIES_PER_QUERY} tras {backoff:.0f}s...")
            time.sleep(backoff)

        _log(f"Ejecutando (intento {attempt}): {' '.join(cmd)}")
        _child = subprocess.Popen(cmd)
        _terminate = False
        deadline = time.time() + PER_QUERY_TIMEOUT

        try:
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

                if time.time() > deadline:
                    _log(
                        f"Timeout de {PER_QUERY_TIMEOUT}s alcanzado, "
                        "forzando terminación de scrapy..."
                    )
                    _child.terminate()
                    try:
                        _child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        _child.kill()
                        _child.wait()
                    break

                try:
                    _child.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    continue

            if _child.returncode == 0:
                _child = None
                _terminate = False
                return True

            _log(f"Scrapy terminó con código {_child.returncode}")

        except Exception as e:
            _log(f"Error ejecutando scrapy: {e}")
            try:
                _child.terminate()
                _child.wait(timeout=10)
            except Exception:
                try:
                    _child.kill()
                except Exception:
                    pass

        _child = None
        _terminate = False

    _log(f"Agotados {MAX_RETRIES_PER_QUERY} reintentos, query falló definitivamente.")
    return False


def main():
    parser = argparse.ArgumentParser(description="Cloud Run spider runner")
    parser.add_argument("spider", nargs="?", help="Spider a ejecutar (reddit, hotmart, generic)")
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra, no ejecuta")
    parser.add_argument("--no-lock", action="store_true", help="No usar lock distribuido en Supabase")
    args_cli = parser.parse_args()

    if not args_cli.spider:
        _log("ERROR: Debes especificar un spider. Uso: python cloud_run_runner.py <spider>")
        sys.exit(1)

    required = ["SUPABASE_URL", "SUPABASE_KEY", "OPENAI_API_KEY"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        _log(f"ERROR: Faltan variables de entorno: {', '.join(missing)}")
        sys.exit(1)

    if not QUERIES_FILE.exists():
        _log(f"ERROR: No encontré {QUERIES_FILE}")
        sys.exit(1)

    queries = json.loads(QUERIES_FILE.read_text())

    if args_cli.spider not in queries:
        _log(f"ERROR: Spider '{args_cli.spider}' no existe en queries.json")
        sys.exit(1)

    targets = {args_cli.spider: queries[args_cli.spider]}

    # Adquirir lock para evitar ejecuciones concurrentes del mismo spider
    if not args_cli.dry_run and not args_cli.no_lock:
        if not acquire_lock(args_cli.spider):
            _log("No se pudo adquirir lock, otra ejecución está en curso. Saliendo.")
            sys.exit(0)

    total = 0
    ok = 0
    failed_queries = []

    try:
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
                    _log(f"FALLÓ (tras {MAX_RETRIES_PER_QUERY} intentos): {label}")
                    failed_queries.append(label)
    finally:
        if not args_cli.dry_run and not args_cli.no_lock:
            release_lock(args_cli.spider)

    if args_cli.dry_run:
        _log(f"DRY-RUN completado. Se ejecutarían {total} tareas en {len(targets)} spiders.")
        return

    _log(f"Resumen: {ok}/{total} ejecuciones exitosas")
    if failed_queries:
        _log(f"Queries fallidas ({len(failed_queries)}):")
        for fq in failed_queries:
            _log(f"  - {fq}")

    if ok == 0 and total > 0:
        _log("Todas las queries fallaron.")
        sys.exit(1)

    if failed_queries:
        _log("Algunas queries fallaron, pero el job se considera parcialmente exitoso.")
        _log("Las queries exitosas ya fueron guardadas en Supabase.")

    sys.exit(0)


if __name__ == "__main__":
    main()
