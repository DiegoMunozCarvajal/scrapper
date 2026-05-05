import os

from loguru import logger
from scrapy.http import Headers
from scrapy.responsetypes import responsetypes
from .stealth_handler import ScrapyPlaywrightStealthDownloadHandler


class CurlCffiDownloadHandler(ScrapyPlaywrightStealthDownloadHandler):
    IMPERSONATE_FALLBACK = "chrome124"

    def _download_request(self, request, spider=None):
        if spider is None:
            spider = self._crawler.spider

        if request.meta.get("playwright"):
            return super()._download_request(request, spider)

        enabled = os.getenv("CURL_CFFI_ENABLED", "true").lower() in ("true", "1", "yes")
        if not enabled:
            return super()._download_request(request, spider)

        try:
            from curl_cffi import requests as curl_requests
        except ImportError:
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
                    kwargs["data"] = request.body
                if request.meta.get("proxy"):
                    kwargs["proxy"] = request.meta["proxy"]

                resp = curl_requests.request(**kwargs)
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
