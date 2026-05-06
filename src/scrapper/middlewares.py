"""Custom Scrapy downloader middlewares for reliability and anti-bot."""

import os
import random
from urllib.parse import urlparse

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
    """Rotate through proxy list on each request, including Playwright.

    Supports Decodo residential proxies natively. If *PROXY_LIST* is empty
    but Decodo credentials are present, a single Decodo gateway URL is built
    automatically and used for every request.
    """

    MAX_FAILS = 3

    def __init__(
        self,
        proxy_list: str,
        decodo_user: str = "",
        decodo_password: str = "",
        decodo_endpoint: str = "gate.decodo.com",
        decodo_port: str = "7000",
    ):
        self.proxies = [p.strip() for p in proxy_list.split(",") if p.strip()]

        # Decodo fallback: build gateway URL when no explicit proxy list is given
        if not self.proxies and decodo_user and decodo_password:
            self.proxies = [
                f"http://{decodo_user}:{decodo_password}@{decodo_endpoint}:{decodo_port}"
            ]

        self.failed_proxies: dict[str, int] = {}

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        return cls(
            proxy_list=settings.get("PROXY_LIST", ""),
            decodo_user=settings.get("DECODO_USER", ""),
            decodo_password=settings.get("DECODO_PASSWORD", ""),
            decodo_endpoint=settings.get("DECODO_ENDPOINT", "gate.decodo.com"),
            decodo_port=settings.get("DECODO_PORT", "7000"),
        )

    @staticmethod
    def _safe_proxy_log(proxy: str) -> str:
        parsed = urlparse(proxy)
        if parsed.port:
            return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        return f"{parsed.scheme}://{parsed.hostname}"

    def _pick_proxy(self) -> str | None:
        healthy = [
            p for p in self.proxies if self.failed_proxies.get(p, 0) < self.MAX_FAILS
        ]
        if healthy:
            return random.choice(healthy)
        # If every proxy is marked failed, reset and try again
        if self.proxies:
            self.failed_proxies.clear()
            return random.choice(self.proxies)
        return None

    def process_request(self, request, spider):
        proxy = self._pick_proxy()
        if proxy is None:
            return None

        if request.meta.get("playwright"):
            context_kwargs = request.meta.setdefault("playwright_context_kwargs", {})
            context_kwargs["proxy"] = {"server": proxy}
        else:
            request.meta["proxy"] = proxy

        # Keep the chosen proxy in meta so process_exception can track it
        request.meta["_proxy_rotation"] = proxy

        logger.debug(f"Using proxy: {self._safe_proxy_log(proxy)}")
        return None

    def process_exception(self, request, exception, spider):
        proxy = request.meta.get("_proxy_rotation")
        if proxy:
            self.failed_proxies[proxy] = self.failed_proxies.get(proxy, 0) + 1
            logger.warning(
                f"Proxy {self._safe_proxy_log(proxy)} failed "
                f"({self.failed_proxies[proxy]}/{self.MAX_FAILS}): {exception}"
            )


class UARotationMiddleware:
    """Rotate user agent on each request."""

    def process_request(self, request, spider):
        ua = random.choice(USER_AGENTS)
        request.headers["User-Agent"] = ua

        if request.meta.get("playwright"):
            context_kwargs = request.meta.setdefault("playwright_context_kwargs", {})
            context_kwargs["user_agent"] = ua

        return None
