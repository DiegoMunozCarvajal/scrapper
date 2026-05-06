# Cloud Run Deployment Fixes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 7 bugs/issues in the Cloud Run deployment pipeline — 2 critical (build fails silently), 3 medium (OOM risk, data loss on timeout, defensive safety), 2 minor (optimization, docs).

**Architecture:** Targeted edits to 5 existing files — no new files created. The `.gcloudignore` and `cloudbuild.yaml` fixes are the build pipeline blockers. The `cloud_run_runner.py` gets a SIGTERM handler to prevent data loss. `queries.json` gets bumped resources. `Dockerfile.cloudrun` and `deploy_cloud_run.sh` get minor cleanups.

**Tech Stack:** gcloud CLI, Cloud Build (cloudbuild.yaml), Scrapy (subprocess), Python signal handling, jq, bash.

---

### Task 1: `.gcloudignore` — Add Dockerfile.cloudrun to whitelist

**Files:**
- Modify: `.gcloudignore:2`

- [ ] **Step 1: Add the line**

```diff
 # Asegura que estos archivos SIEMPRE se incluyan en el build context de Cloud Build
+!Dockerfile.cloudrun
 !queries.json
```

- [ ] **Step 2: Verify file**

```bash
grep 'Dockerfile.cloudrun' /Users/diegocarvajal/Documents/Programming/scrapper/.gcloudignore
```
Expected output: `!Dockerfile.cloudrun`

- [ ] **Step 3: Commit**

```bash
git add .gcloudignore
git commit -m "fix: add Dockerfile.cloudrun to .gcloudignore whitelist"
```

---

### Task 2: `cloudbuild.yaml` — Use substitutions for region/repo/image

**Files:**
- Modify: `cloudbuild.yaml:8,15` (tag string), append `substitutions:` block

- [ ] **Step 1: Replace hardcoded tags and add substitutions block**

```diff
 steps:
   - name: 'gcr.io/cloud-builders/docker'
     args:
       - 'build'
       - '-f'
       - 'Dockerfile.cloudrun'
       - '-t'
-      - 'us-central1-docker.pkg.dev/$PROJECT_ID/scrapper/scraper:latest'
+      - '${_REGION}-docker.pkg.dev/$PROJECT_ID/${_REPO}/${_IMAGE}:latest'
       - '.'
     env:
       - 'DOCKER_BUILDKIT=1'
   - name: 'gcr.io/cloud-builders/docker'
     args:
       - 'push'
-      - 'us-central1-docker.pkg.dev/$PROJECT_ID/scrapper/scraper:latest'
+      - '${_REGION}-docker.pkg.dev/$PROJECT_ID/${_REPO}/${_IMAGE}:latest'
+
+substitutions:
+  _REGION: us-central1
+  _REPO: scrapper
+  _IMAGE: scraper
 options:
   machineType: 'E2_HIGHCPU_8'
```

- [ ] **Step 2: Verify the file is valid YAML**

```bash
python -c "import yaml; yaml.safe_load(open('/Users/diegocarvajal/Documents/Programming/scrapper/cloudbuild.yaml'))"
```
Expected: No output (success).

- [ ] **Step 3: Commit**

```bash
git add cloudbuild.yaml
git commit -m "fix: use Cloud Build substitutions for region, repo, and image in cloudbuild.yaml"
```

---

### Task 3: `queries.json` — Bump memory/timeout for all spiders

**Files:**
- Modify: `queries.json:5-7,19-21,31-33`

- [ ] **Step 1: Update resource blocks for all 3 spiders**

Change each `"cloud_run"` block from:
```json
"cloud_run": {
  "cpu": 1,
  "memory": "1Gi",
  "timeout": "15m"
}
```
To:
```json
"cloud_run": {
  "cpu": 1,
  "memory": "2Gi",
  "timeout": "20m"
}
```

This applies to lines 4-8 (reddit), 18-22 (hotmart), and 30-34 (generic).

- [ ] **Step 2: Verify JSON is valid**

```bash
python -c "import json; json.load(open('/Users/diegocarvajal/Documents/Programming/scrapper/queries.json'))"
```
Expected: No output (success).

- [ ] **Step 3: Commit**

```bash
git add queries.json
git commit -m "fix: increase Cloud Run resources to 2Gi/20min for all spiders"
```

---

### Task 4: `cloud_run_runner.py` — SIGTERM/SIGINT handler with graceful scrapy shutdown

**Files:**
- Modify: `cloud_run_runner.py:1-51` (imports and run_spider function)

- [ ] **Step 1: Add imports and signal handler globals at top of file**

After the existing imports (after `from pathlib import Path`), add:

```python
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
```

- [ ] **Step 2: Replace `run_spider()` implementation**

Replace the existing `run_spider` function (lines 33-51) with:

```python
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
```

- [ ] **Step 3: Verify syntax and imports**

```bash
python -c "import ast; ast.parse(open('/Users/diegocarvajal/Documents/Programming/scrapper/cloud_run_runner.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add cloud_run_runner.py
git commit -m "fix: add SIGTERM handler to cloud_run_runner for graceful scrapy shutdown"
```

---

### Task 5: `cloud_run_runner.py` — Require spider argument (fail fast if missing)

**Files:**
- Modify: `cloud_run_runner.py:56` (in main(), after args parsing)

- [ ] **Step 1: Add guard before the env-var validation**

After `args_cli = parser.parse_args()` (line 58), add:

```python
    if not args_cli.spider:
        _log("ERROR: Debes especificar un spider. Uso: python cloud_run_runner.py <spider>")
        sys.exit(1)
```

- [ ] **Step 2: Verify the guard works**

```bash
cd /Users/diegocarvajal/Documents/Programming/scrapper && python cloud_run_runner.py 2>&1; echo "Exit code: $?"
```
Expected: `ERROR: Debes especificar un spider...` and exit code 1.

- [ ] **Step 3: Commit**

```bash
git add cloud_run_runner.py
git commit -m "fix: require spider argument in cloud_run_runner; fail fast if missing"
```

---

### Task 6: `Dockerfile.cloudrun` — Use `pip install .` instead of editable install

**Files:**
- Modify: `Dockerfile.cloudrun:34`

- [ ] **Step 1: Change one character**

```diff
- RUN pip install -e .
+ RUN pip install .
```

- [ ] **Step 2: Commit**

```bash
git add Dockerfile.cloudrun
git commit -m "chore: use pip install . instead of -e in Dockerfile.cloudrun"
```

---

### Task 7: `deploy_cloud_run.sh` — Add gcloud version check

**Files:**
- Modify: `deploy_cloud_run.sh:37-38` (after jq check)

- [ ] **Step 1: Add version check after the jq validation**

After line 38 (`fi` closing the jq check), add:

```bash
GCLOUD_VER=$(gcloud version 2>/dev/null | head -1 | grep -oE '^[^0-9]*([0-9]+)' | grep -oE '[0-9]+' || echo "0")
if [ "$GCLOUD_VER" -lt 418 ]; then
    log_error "gcloud >= 418.0.0 requerido (soporte para gcloud run jobs). Actual: ${GCLOUD_VER}"
    exit 1
fi
```

- [ ] **Step 2: Verify shell syntax**

```bash
bash -n /Users/diegocarvajal/Documents/Programming/scrapper/deploy_cloud_run.sh
```
Expected: No output (success).

- [ ] **Step 3: Commit**

```bash
git add deploy_cloud_run.sh
git commit -m "chore: add gcloud minimum version check (418+) in deploy_cloud_run.sh"
```
