import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# Python 3.12+ requires an explicit event loop before installing the reactor
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

BOT_NAME = "scrapper"

SPIDER_MODULES = ["scrapper.spiders"]
NEWSPIDER_MODULE = "scrapper.spiders"

ROBOTSTXT_OBEY = True
USER_AGENT = "scrapper/0.2 (research crawler; contact@example.com)"

CONCURRENT_REQUESTS = 2
DOWNLOAD_DELAY = 2
RANDOMIZE_DOWNLOAD_DELAY = True

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

RETRY_ENABLED = True
RETRY_TIMES = 4
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

# Playwright download handler (required for JS rendering)
DOWNLOAD_HANDLERS = {
    "http": "scrapper.curl_cffi_handler.CurlCffiDownloadHandler",
    "https": "scrapper.curl_cffi_handler.CurlCffiDownloadHandler",
}

# Playwright config
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes"),
    "args": ["--disable-blink-features=AutomationControlled"],
}
PLAYWRIGHT_MAX_PAGES_PER_CONTEXT = 4
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 30000
PLAYWRIGHT_ELEM_WAIT_TIMEOUT = 5000
PLAYWRIGHT_HUMAN_SIMULATION = os.getenv(
    "PLAYWRIGHT_HUMAN_SIMULATION", "true"
).lower() in ("true", "1", "yes")

# ── RAG-ready export ─────────────────────
RAG_EXPORT_ENABLED = os.getenv("RAG_EXPORT_ENABLED", "true").lower() in ("true", "1", "yes")
RAG_OUTPUT_DIR = "rag_output"

# ── LLM fallback extraction ─────────────────
LLM_ENABLED = os.getenv("LLM_ENABLED", "true").lower() in ("true", "1", "yes")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_CACHE_TTL = int(os.getenv("LLM_CACHE_TTL", "86400"))
LLM_CACHE_PATH = os.getenv("LLM_CACHE_PATH", "llm_cache.db")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

ITEM_PIPELINES = {
    "scrapper.pipelines.ValidatePipeline": 100,
    "scrapper.pipelines.DataQualityPipeline": 150,
    "scrapper.pipelines.DedupInMemoryPipeline": 200,
    "scrapper.pipelines.SupabasePipeline": 300,
}

if RAG_EXPORT_ENABLED:
    ITEM_PIPELINES["scrapper.rag_export.MarkdownExportPipeline"] = 400
    ITEM_PIPELINES["scrapper.rag_export.ChunkedJSONPipeline"] = 450

DOWNLOADER_MIDDLEWARES = {
    "scrapper.middlewares.RetryWithBackoffMiddleware": 550,
    "scrapper.middlewares.ProxyRotationMiddleware": 750,
    "scrapper.middlewares.UARotationMiddleware": 850,
}

EXTENSIONS = {
    "scrapper.extensions.StatsLogger": 400,
    "scrapper.extensions.EmailAlerter": 500,
    "scrapper.dashboard.MetricsDashboard": 600,
}

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

PROXY_LIST = os.getenv("PROXY_LIST", "")

# ── curl-cffi anti-bot ──────────────────────
CURL_CFFI_ENABLED = os.getenv("CURL_CFFI_ENABLED", "true").lower() in ("true", "1", "yes")
CURL_CFFI_IMPERSONATE = os.getenv("CURL_CFFI_IMPERSONATE", "chrome124")

# ── Email alerts ──────────────────────────
ALERT_SMTP_HOST = os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com")
ALERT_SMTP_PORT = int(os.getenv("ALERT_SMTP_PORT", "587"))
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "")
ALERT_EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
ALERT_ERROR_THRESHOLD = int(os.getenv("ALERT_ERROR_THRESHOLD", "5"))

# ── Metrics persistence ──────────────────
METRICS_DIR = "metrics"
METRICS_MAX_RUNS = 100

# ── Scheduling ────────────────────────────
SCHEDULE_ENABLED = os.getenv("SCHEDULE_ENABLED", "false").lower() in ("true", "1", "yes")

LOG_ENABLED = True
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Size-based rotation: 5 files x 5MB
LOG_FILE_PATH = "logs/scrapy.log"
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024  # 5MB
LOG_FILE_BACKUP_COUNT = 5

# Time-based rotation: daily, keep 7 days
LOG_FILE_TIME = "logs/scrapy-daily.log"
LOG_FILE_TIME_WHEN = "00:00"
LOG_FILE_TIME_BACKUP = 7

# ── Cookie persistence (for login sites) ──────
COOKIE_PERSIST_ENABLED = os.getenv("COOKIE_PERSIST_ENABLED", "true").lower() in ("true", "1", "yes")
COOKIE_SAVE_ENABLED = True
COOKIE_LOAD_ENABLED = True
COOKIE_DB_PATH = "cookies"

DOWNLOAD_TIMEOUT = 30
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 30000