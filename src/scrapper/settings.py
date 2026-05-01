import os
from dotenv import load_dotenv

load_dotenv()

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

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {"headless": True}
PLAYWRIGHT_MAX_PAGES_PER_CONTEXT = 4

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
    "scrapper.extensions.ErrorAlerter": 500,
}

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

PROXY_LIST = os.getenv("PROXY_LIST", "")

ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")

LOG_LEVEL = "INFO"
LOG_FILE = "scrapy.log"

DOWNLOAD_TIMEOUT = 30
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 30000