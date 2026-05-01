import os
from pathlib import Path

BOT_NAME = "scrapper"

SPIDER_MODULES = ["src.scrapper.spiders"]
NEWSPIDER_MODULE = "src.scrapper.spiders"

ROBOTSTXT_OBEY = False

CONCURRENT_REQUESTS = 8
DOWNLOAD_DELAY = 1

TELNETCONSOLE_ENABLED = False

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
PROXY_LIST = os.getenv("PROXY_LIST", "")

SPIDER_MIDDLEWARES = {}

DOWNLOADER_MIDDLEWARES = {}

CONTAINER_PIPELINES = {}