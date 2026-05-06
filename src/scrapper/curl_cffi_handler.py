import os

from loguru import logger
from scrapy.http import Headers
from scrapy.responsetypes import responsetypes

from .stealth_handler import ScrapyPlaywrightStealthDownloadHandler


class CurlCffiDownloadHandler(ScrapyPlaywrightStealthDownloadHandler):
    IMPERSONATE_FALLBACK = "chrome124"

    def __init__(self, settings):
        super().__init__(settings)
        self._session = None

    def _get_session(self):
        if not hasattr(self, "_session"):
            self._session = None
        if self._session is None:
            try:
                from curl_cffi import requests as curl_requests
            except ImportError:
                return None
            self._session = curl_requests.Session()
        return self._session

    def _download_request(self, request, spider=None):
        if spider is None:
            spider = self._crawler.spider

        if request.meta.get("playwright"):
            return super()._download_request(request, spider)

        enabled = os.getenv("CURL_CFFI_ENABLED", "true").lower() in ("true", "1", "yes")
        if not enabled:
            return super()._download_request(request, spider)

        session = self._get_session()
        if session is None:
            logger.warning("curl_cffi not available, falling back to default handler")
            return super()._download_request(request, spider)

        impersonate = os.getenv("CURL_CFFI_IMPERSONATE", self.IMPERSONATE_FALLBACK)
        from twisted.internet.threads import deferToThread

        def _do_request():
            try:
                headers = request.headers.to_unicode_dict()
                timeout = request.meta.get(
                    "download_timeout",
                    self._crawler.settings.getfloat("DOWNLOAD_TIMEOUT", 30),
                )
                kwargs = {
                    "method": request.method,
                    "url": request.url,
                    "headers": headers,
                    "impersonate": impersonate,
                    "timeout": timeout,
                }
                if request.body:
                    body = request.body
                    if isinstance(body, memoryview):
                        body = bytes(body)
                    kwargs["data"] = body
                    if "Content-Type" not in headers:
                        body_hint = body[:200].decode("utf-8", errors="replace").strip()
                        if body_hint.startswith("{") or body_hint.startswith("["):
                            kwargs["headers"]["Content-Type"] = "application/json"
                if request.meta.get("proxy"):
                    kwargs["proxy"] = request.meta["proxy"]

                resp = session.request(**kwargs)
                response_headers = Headers(resp.headers)
                respcls = responsetypes.from_args(
                    headers=response_headers,
                    url=str(resp.url),
                    body=resp.content,
                )
                return respcls(
                    url=str(resp.url),
                    status=resp.status_code,
                    headers=response_headers,
                    body=resp.content,
                    request=request,
                )
            except Exception as e:
                spider.logger.warning(
                    f"curl_cffi request failed: {e}, letting Scrapy retry"
                )
                raise

        return deferToThread(_do_request)
