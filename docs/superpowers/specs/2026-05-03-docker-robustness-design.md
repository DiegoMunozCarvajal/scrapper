# Docker Robustness — Multi-stage build + signal handling + health checks

## Problem

Current Docker setup is fragile:
- No signal propagation (PID 1 bash script without `trap`/`exec`)
- No health checks
- Single-stage bloated image (~800MB+)
- Runs as root
- No resource limits
- Unpinned `scrapyd`/`scrapyd-client` versions

## Solution

### Dockerfile — Multi-stage

- **Builder**: install build deps, `pip install "."` (non-editable), `playwright install chromium`
- **Runtime**: `python:3.11-slim`, `playwright install-deps chromium`, cron, curl, non-root `appuser`
- Copy venv + playwright browsers from builder

### Entrypoint — Signal handling

- `trap` SIGTERM/SIGINT → graceful shutdown of scrapyd + cron
- Validate `queries.json` before generating crontab
- Background scrapyd, wait for ready, deploy project, start metrics server, wait

### docker-compose.yml

- Health check: `curl daemonstatus.json` (30s interval, 10s timeout, 3 retries, 90s start period)
- `deploy.resources.limits`: 2 CPUs, 2GB RAM
- Logging: `json-file` with 10MB max + 3 rotations
- Volume for `llm_cache.db`

### pyproject.toml

- `[project.optional-dependencies] docker`: `scrapyd>=1.6,<2.1`, `scrapyd-client>=1.3,<2.1`

### .dockerignore

- Add `llm_cache.db`, result JSONs, `graphify-out/`
