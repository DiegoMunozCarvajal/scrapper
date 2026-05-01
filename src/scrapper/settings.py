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
    "http": "scrapper.stealth_handler.ScrapyPlaywrightStealthDownloadHandler",
    "https": "scrapper.stealth_handler.ScrapyPlaywrightStealthDownloadHandler",
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

ITEM_PIPELINES = {
    "scrapper.pipelines.ValidatePipeline": 100,
    "scrapper.pipelines.DedupInMemoryPipeline": 200,
    "scrapper.pipelines.SupabasePipeline": 300,
}

DOWNLOADER_MIDDLEWARES = {
    "scrapper.middlewares.RetryWithBackoffMiddleware": 550,
    "scrapper.middlewares.ProxyRotationMiddleware": 750,
    "scrapper.middlewares.UARotationMiddleware": 850,
}

EXTENSIONS = {
    "scrapper.extensions.StatsLogger": 400,
    "scrapper.extensions.ErrorAlerter": 500,
}

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

PROXY_LIST = os.getenv("PROXY_LIST", "")

ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")

LOG_LEVEL = "INFO"
LOG_FILE = "scrapy.log"

# ── Cookie persistence (for login sites) ──────
COOKIE_SAVE_ENABLED = True
COOKIE_LOAD_ENABLED = True
COOKIE_DB_PATH = "cookies/".strip("/")

DOWNLOAD_TIMEOUT = 30
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 30000