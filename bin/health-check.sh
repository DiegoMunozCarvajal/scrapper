#!/bin/bash
# Health check script - polls Scrapyd /daemonstatus.json
# Run via cron: */5 * * * * /path/to/bin/health-check.sh >> /var/log/scrapyd-health.log 2>&1

SCRAPYD_URL="${SCRAPYD_URL:-http://localhost:6800}"
ALERT_WEBHOOK_URL="${ALERT_WEBHOOK_URL:-}"
LOG_FILE="${LOG_FILE:-/var/log/scrapyd-health.log}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

send_alert() {
    local message="$1"
    log "ALERT: $message"
    if [[ -n "$ALERT_WEBHOOK_URL" ]]; then
        curl -s -X POST "$ALERT_WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"content\": \"[Health Check] $message\"}" \
            || true
    fi
}

check_scrapyd() {
    local status
    status=$(curl -s -w "%{http_code}" -o /dev/null "$SCRAPYD_URL/daemonstatus.json" 2>/dev/null) || status="000"

    if [[ "$status" == "200" ]]; then
        log "OK: Scrapyd responding (HTTP $status)"
        return 0
    else
        send_alert "Scrapyd down! HTTP $status"
        return 1
    fi
}

check_pending() {
    local pending
    pending=$(curl -s "$SCRAPYD_URL/daemonstatus.json" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','pending'))" 2>/dev/null) || pending="?"

    if [[ "$pending" =~ ^[0-9]+$ ]] && (( pending > 100 )); then
        send_alert "High pending jobs: $pending"
        return 1
    fi

    log "Pending jobs: $pending"
    return 0
}

main() {
    log "=== Health check started ==="
    check_scrapyd
    check_pending
    log "=== Health check complete ==="
}

main "$@"