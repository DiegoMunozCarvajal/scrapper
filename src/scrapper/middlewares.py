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
        if isinstance(exception, self.exceptions_to_retry) and not request.meta.get(
            "dont_retry", False
        ):
            retry_request = self._retry(request, exception)
            if retry_request is not None:
                return retry_request
        return None


class ProxyRotationMiddleware:
    """Rotate through proxy list on each request, including Playwright.

    Supports DataImpulse residential proxies natively. If *PROXY_LIST* is empty
    but DataImpulse credentials are present, a single DataImpulse gateway URL is built
    automatically and used for every request.
    """

    MAX_FAILS = 3

    def __init__(
        self,
        proxy_list: str,
        dataimpulse_user: str = "",
        dataimpulse_password: str = "",
        dataimpulse_endpoint: str = "gw.dataimpulse.com",
        dataimpulse_port: str = "823",
    ):
        self.proxies = [p.strip() for p in proxy_list.split(",") if p.strip()]

        # DataImpulse fallback: build gateway URL when no explicit proxy list is given
        if not self.proxies and dataimpulse_user and dataimpulse_password:
            self.proxies = [
                f"http://{dataimpulse_user}:{dataimpulse_password}@{dataimpulse_endpoint}:{dataimpulse_port}"
            ]

        self.failed_proxies: dict[str, int] = {}

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        return cls(
            proxy_list=settings.get("PROXY_LIST", ""),
            dataimpulse_user=settings.get("DATAIMPULSE_USER", ""),
            dataimpulse_password=settings.get("DATAIMPULSE_PASSWORD", ""),
            dataimpulse_endpoint=settings.get("DATAIMPULSE_ENDPOINT", "gw.dataimpulse.com"),
            dataimpulse_port=settings.get("DATAIMPULSE_PORT", "823"),
        )

    @staticmethod
    def _safe_proxy_log(proxy: str) -> str:
        parsed = urlparse(proxy)
        if parsed.port:
            return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        return f"{parsed.scheme}://{parsed.hostname}"

    @staticmethod
    def _parse_proxy_for_playwright(proxy_url: str) -> dict:
        """Parse proxy URL into Playwright's expected dict format.

        Playwright requires username/password as separate keys, not embedded
        in the URL.
        """
        parsed = urlparse(proxy_url)
        result: dict = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
        if parsed.username:
            result["username"] = parsed.username
        if parsed.password:
            result["password"] = parsed.password
        return result

    def _pick_proxy(self) -> str | None:
        healthy = [p for p in self.proxies if self.failed_proxies.get(p, 0) < self.MAX_FAILS]
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
            # Playwright requires username/password as separate keys
            context_kwargs["proxy"] = self._parse_proxy_for_playwright(proxy)
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


class CurlCffiMiddleware:
    """Downloader middleware: replace default download handler with curl_cffi.

    Impersonates Chrome 124 TLS fingerprint to evade anti-bot detection.
    Only activates for configured spiders (default: 'reddit').
    Returns a Response directly, skipping Scrapy's default download handler.
    """

    def __init__(self, enabled_spiders=None):
        self.enabled_spiders = enabled_spiders or ["reddit"]

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            enabled_spiders=crawler.settings.getlist("CURL_CFFI_SPIDERS", ["reddit"]),
        )

    def process_request(self, request, spider):
        if spider.name not in self.enabled_spiders:
            return None
        if not request.url.startswith(("http://", "https://")):
            return None
        # Playwright requests use the browser — skip curl_cffi
        if request.meta.get("playwright"):
            return None

        from curl_cffi import requests as curl_requests
        from scrapy.http import HtmlResponse

        headers = {}
        for k, vals in request.headers.items():
            k_str = k.decode() if isinstance(k, bytes) else k
            v = vals[0] if isinstance(vals, list) else vals
            headers[k_str] = v.decode() if isinstance(v, bytes) else v

        proxy_url = request.meta.get("proxy")
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

        try:
            resp = curl_requests.request(
                method=request.method,
                url=request.url,
                headers=headers,
                proxies=proxies,
                impersonate="chrome124",
                timeout=30,
            )
        except Exception as e:
            logger.warning(f"curl_cffi failed for {request.url}: {e}")
            return None  # Let Scrapy fallback or errback handle

        return HtmlResponse(
            url=str(resp.url),
            status=resp.status_code,
            headers={k.encode(): [str(v).encode()] for k, v in resp.headers.items()},
            body=resp.content,
            request=request,
            encoding="utf-8",
        )
