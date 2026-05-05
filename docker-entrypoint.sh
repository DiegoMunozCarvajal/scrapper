#!/bin/bash
set -e

# ── Signal handling ──────────────────────────────────────────────
cleanup() {
    echo "[entrypoint] Received termination signal, shutting down..."
    kill "$SCRAPYD_PID" 2>/dev/null || true
    kill "$HTTP_PID" 2>/dev/null || true
    kill "$TAIL_PID" 2>/dev/null || true
    kill "$CROND_PID" 2>/dev/null || true
    for i in $(seq 1 10); do
        if ! kill -0 "$SCRAPYD_PID" 2>/dev/null && ! kill -0 "$HTTP_PID" 2>/dev/null && ! kill -0 "$TAIL_PID" 2>/dev/null && ! kill -0 "$CROND_PID" 2>/dev/null; then
            break
        fi
        sleep 1
    done
    kill -9 "$SCRAPYD_PID" 2>/dev/null || true
    kill -9 "$HTTP_PID" 2>/dev/null || true
    kill -9 "$TAIL_PID" 2>/dev/null || true
    kill -9 "$CROND_PID" 2>/dev/null || true
    wait "$SCRAPYD_PID" 2>/dev/null || true
    wait "$HTTP_PID" 2>/dev/null || true
    wait "$TAIL_PID" 2>/dev/null || true
    wait "$CROND_PID" 2>/dev/null || true
    echo "[entrypoint] Shutdown complete."
    exit 0
}
trap cleanup SIGTERM SIGINT

# ── Check bind-mount directory permissions ───────────────────────
check_writable() {
    local dir="$1"
    if [ -d "$dir" ] && [ ! -w "$dir" ]; then
        echo "[entrypoint] WARNING: $dir is not writable (UID $(id -u))." >&2
        echo "[entrypoint] Fix on host: chown -R $(id -u):$(id -g) \$(pwd)/\$(basename "$dir")" >&2
    fi
    mkdir -p "$dir" 2>/dev/null || true
}
check_writable /app/logs
check_writable /app/eggs
check_writable /app/dbs
check_writable /app/items
check_writable /app/metrics
check_writable /app/rag_output
check_writable /app/cookies

# ── Ensure llm_cache.db exists (prevents Docker creating a directory) ─
if [ ! -f /app/llm_cache.db ]; then
    echo "[entrypoint] Creating llm_cache.db..."
    touch /app/llm_cache.db
fi

# ── Validate queries.json ────────────────────────────────────────
echo "[entrypoint] Validating queries.json..."
error=$(python3 -c "import json; json.load(open('/app/queries.json'))" 2>&1) || {
    if [ -d "/app/queries.json" ]; then
        echo "[entrypoint] ERROR: /app/queries.json is a directory — did you forget to create the file on the host?" >&2
    else
        echo "[entrypoint] ERROR: queries.json is not valid JSON: $error" >&2
    fi
    exit 1
}

# ── Generate crontab ─────────────────────────────────────────────
echo "[entrypoint] Generating schedule from queries.json..."
python3 /app/generate_schedule.py

# ── Start cron (busybox crond, works as non-root) ─────────────────
echo "[entrypoint] Starting cron daemon..."
CRON_USER=$(whoami)
mkdir -p /tmp/crontabs
cp /app/crontab.txt "/tmp/crontabs/$CRON_USER"
busybox crond -f -c /tmp/crontabs -L /dev/stdout &
CROND_PID=$!
sleep 1
if ! kill -0 "$CROND_PID" 2>/dev/null; then
    echo "[entrypoint] WARNING: cron failed to start — scheduling disabled" >&2
    CROND_PID=""
fi

# ── Start Scrapyd ────────────────────────────────────────────────
echo "[entrypoint] Starting Scrapyd..."
scrapyd &
SCRAPYD_PID=$!

echo "[entrypoint] Waiting for Scrapyd..."
ready=0
for i in $(seq 1 45); do
    if curl -s http://localhost:6800/daemonstatus.json 2>/dev/null | grep -q '"status": "ok"'; then
        echo "[entrypoint] Scrapyd is ready"
        ready=1
        break
    fi
    sleep 2
done
if [ "$ready" -eq 0 ]; then
    echo "[entrypoint] ERROR: Scrapyd failed to start after 90s" >&2
    exit 1
fi

# ── Deploy project to Scrapyd ────────────────────────────────────
echo "[entrypoint] Deploying project..."
scrapyd-deploy default 2>&1 || echo "[entrypoint] WARNING: scrapyd-deploy failed — check that setup.py and pyproject.toml are correctly configured" >&2

# ── Start metrics HTTP server ────────────────────────────────────
echo "[entrypoint] Starting dashboard on :8080..."
mkdir -p /app/metrics
python3 -m http.server 8080 --directory /app/metrics &
HTTP_PID=$!

# ── Tail logs to stdout for docker logs visibility ───────────────
echo "[entrypoint] Streaming spider + cron logs to stdout..."
touch /app/logs/scrapy.log /app/logs/cron.log 2>/dev/null || true
tail -n 0 -F /app/logs/scrapy.log /app/logs/cron.log 2>/dev/null &
TAIL_PID=$!

echo "[entrypoint] Scrapyd running on :6800"
echo "[entrypoint] Dashboard at http://localhost:8080/dashboard.html"
echo "[entrypoint] Cron schedule:"
cat /app/crontab.txt

wait
