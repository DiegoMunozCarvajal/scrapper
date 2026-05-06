"""Custom Scrapy downloader middlewares for reliability and anti-bot."""

import random

from loguru import logger
from scrapy.downloadermiddlewares.retry import RetryMiddleware

from .utils import USER_AGENTS


class RetryWithBackoffMiddleware(RetryMiddleware):
    """Retry on transient errors with exponential backoff via download latency: 1s, 2s, 4s, 8s."""

    @staticmethod
    def _delay_for_retry_times(retry_times: int) -> int:
        return min(2 ** max(retry_times - 1, 0), 16)

    def _retry(self, request, reason):
        retries = request.meta.get("retry_times", 0) + 1
        delay = self._delay_for_retry_times(retries)
        logger.info(f"Retrying {request.url} (attempt {retries}) after {delay}s delay")
        retry_request = super()._retry(request, reason)
        if retry_request is not None:
            retry_request.meta["retry_delay"] = delay
            retry_request.meta["download_latency"] = delay
        return retry_request

    def process_response(self, request, response, spider):
        from scrapy.utils.response import response_status_message

        if request.meta.get("dont_retry", False):
            return response
        if response.status in self.retry_http_codes:
            reason = response_status_message(response.status)
            retry_request = self._retry(request, reason)
            if retry_request is not None:
                return retry_request
        return response

    def process_exception(self, request, exception, spider):
        if isinstance(exception, self.exceptions_to_retry) and not request.meta.get("dont_retry", False):
            retry_request = self._retry(request, exception)
            if retry_request is not None:
                return retry_request
        return None


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

        logger.debug(
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
