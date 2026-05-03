import logging
import os

from scrapy.http import HtmlResponse
from scrapy_playwright.handler import ScrapyPlaywrightDownloadHandler

logger = logging.getLogger(__name__)


class CurlCffiDownloadHandler(ScrapyPlaywrightDownloadHandler):
    IMPERSONATE_FALLBACK = "chrome124"

    def _download_request(self, request, spider):
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
        from twisted.internet import reactor, threads
        from twisted.internet.defer import Deferred

        def _do_request():
            try:
                resp = curl_requests.get(
                    request.url,
                    headers=dict(request.headers),
                    impersonate=impersonate,
                    timeout=30,
                )
                return HtmlResponse(
                    url=str(resp.url),
                    status=resp.status_code,
                    headers=dict(resp.headers),
                    body=resp.content,
                    request=request,
                )
            except Exception as e:
                spider.logger.warning(
                    f"curl_cffi request failed: {e}, falling back to parent handler"
                )
                deferred = Deferred()
                reactor.callFromThread(lambda: deferred.callback(
                    super(CurlCffiDownloadHandler, self)._download_request(request, spider)
                ))
                return deferred

        return threads.deferToThread(_do_request)
