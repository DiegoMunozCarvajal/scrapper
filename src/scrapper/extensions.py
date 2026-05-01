"""Scrapy extensions for monitoring and alerting."""

import json
import time
from urllib.request import Request, urlopen

from scrapy import signals
from loguru import logger


class StatsLogger:
    """Log scraping stats at spider completion."""

    def __init__(self):
        self.start_time = None

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls()
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_opened(self, spider):
        self.start_time = time.time()
        logger.info(f"[{spider.name}] Spider opened")

    def spider_closed(self, spider, reason):
        stats = spider.crawler.stats
        elapsed = time.time() - self.start_time if self.start_time else 0
        items = stats.get_value("item_scraped_count", 0)

        logger.info(
            f"[{spider.name}] Spider closed: {reason} | "
            f"(items={items}, elapsed={elapsed:.1f}s, "
            f"rate={items/elapsed*60:.1f}/min if elapsed else 0)"
        )

        logger.info(
            f"[{spider.name}] Stats: "
            f"responses={stats.get_value('response_received_count', 0)}, "
            f"errors={stats.get_value('log_count/ERROR', 0)}, "
            f"items={items}"
        )


class ErrorAlerter:
    """POST to a webhook URL when a spider encounters critical errors."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.error_count = 0

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls(webhook_url=crawler.settings.get("ALERT_WEBHOOK_URL", ""))
        crawler.signals.connect(ext.spider_error, signal=signals.spider_error)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_error(self, failure, response, spider):
        self.error_count += 1
        if self.error_count <= 5:
            logger.error(
                f"[{spider.name}] Error on {response.url if response else 'unknown'}: "
                f"{failure.getErrorMessage()}"
            )

    def spider_closed(self, spider, reason):
        if self.error_count > 5 and self.webhook_url:
            payload = json.dumps({
                "content": f":warning: **{spider.name}** closed with **{self.error_count} errors**. Reason: `{reason}`"
            }).encode()
            try:
                req = Request(self.webhook_url, data=payload, headers={"Content-Type": "application/json"})
                urlopen(req, timeout=5)
            except Exception as e:
                logger.error(f"Failed to send alert webhook: {e}")