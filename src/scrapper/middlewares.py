"""Custom Scrapy downloader middlewares for reliability and anti-bot."""

import random

from scrapy.downloadermiddlewares.retry import RetryMiddleware


class RetryWithBackoffMiddleware(RetryMiddleware):
    """Retry on errors with exponential backoff: 1s, 2s, 4s, 8s."""

    def _retry(self, request, reason, spider):
        retries = request.meta.get("retry_times", 0) + 1
        delay = min(2 ** (retries - 1), 16)
        request.meta["retry_times"] = retries
        request.meta["download_latency"] = delay
        spider.logger.info(
            f"Retrying {request.url} (attempt {retries}) after {delay}s delay"
        )
        return super()._retry(request, reason, spider)


class ProxyRotationMiddleware:
    """Rotate through proxy list on each request."""

    def __init__(self, proxy_list: str):
        self.proxies = [p.strip() for p in proxy_list.split(",") if p.strip()]

    @classmethod
    def from_crawler(cls, crawler):
        return cls(proxy_list=crawler.settings.get("PROXY_LIST", ""))

    def process_request(self, request, spider):
        if not self.proxies:
            return None
        proxy = random.choice(self.proxies)
        request.meta["proxy"] = proxy
        spider.logger.debug(f"Using proxy: {proxy.split('@')[-1] if '@' in proxy else proxy}")
        return None


class UARotationMiddleware:
    """Rotate user agent on each request (for non-Playwright requests)."""

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64 x64; rv:126.0) Gecko/20100101 Firefox/126.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:126.0) Gecko/20100101 Firefox/126.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    ]

    def process_request(self, request, spider):
        if request.meta.get("playwright"):
            return None
        ua = random.choice(self.USER_AGENTS)
        request.headers["User-Agent"] = ua
        return None