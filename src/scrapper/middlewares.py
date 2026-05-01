"""Custom Scrapy downloader middlewares for reliability and anti-bot."""

import random

from scrapy.downloadermiddlewares.retry import RetryMiddleware

from .utils import USER_AGENTS


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
    """Rotate through proxy list on each request, including Playwright."""

    def __init__(self, proxy_list: str):
        self.proxies = [p.strip() for p in proxy_list.split(",") if p.strip()]

    @classmethod
    def from_crawler(cls, crawler):
        return cls(proxy_list=crawler.settings.get("PROXY_LIST", ""))

    def process_request(self, request, spider):
        if not self.proxies:
            return None
        proxy = random.choice(self.proxies)

        if request.meta.get("playwright"):
            context_kwargs = request.meta.setdefault("playwright_context_kwargs", {})
            context_kwargs["proxy"] = {"server": proxy}
        else:
            request.meta["proxy"] = proxy

        spider.logger.debug(
            f"Using proxy: {proxy.split('@')[-1] if '@' in proxy else proxy}"
        )
        return None


class UARotationMiddleware:
    """Rotate user agent on each request."""

    def process_request(self, request, spider):
        ua = random.choice(USER_AGENTS)
        request.headers["User-Agent"] = ua

        if request.meta.get("playwright"):
            context_kwargs = request.meta.setdefault("playwright_context_kwargs", {})
            context_kwargs["user_agent"] = ua

        return None
