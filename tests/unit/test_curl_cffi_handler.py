import os
from unittest.mock import MagicMock, patch

from scrapy import Request
from twisted.internet.defer import Deferred


def test_handler_class_exists():
    from scrapper.curl_cffi_handler import CurlCffiDownloadHandler
    handler = CurlCffiDownloadHandler.__new__(CurlCffiDownloadHandler)
    assert handler is not None


def test_disabled_falls_back():
    os.environ["CURL_CFFI_ENABLED"] = "false"
    from scrapper.curl_cffi_handler import CurlCffiDownloadHandler  # noqa: F811
    assert CurlCffiDownloadHandler is not None
    del os.environ["CURL_CFFI_ENABLED"]


def test_playwright_request_delegates_to_parent():
    os.environ["CURL_CFFI_ENABLED"] = "true"
    from scrapper.curl_cffi_handler import CurlCffiDownloadHandler  # noqa: F811

    request = Request("https://example.com", meta={"playwright": True})
    spider = MagicMock()
    spider.logger = MagicMock()

    with patch(
        "scrapper.stealth_handler.ScrapyPlaywrightStealthDownloadHandler._download_request"
    ) as mock_parent:
        mock_parent.return_value = Deferred()

        handler = CurlCffiDownloadHandler.__new__(CurlCffiDownloadHandler)
        handler.settings = {}

        deferred = handler._download_request(request, spider)
        assert deferred is not None
        mock_parent.assert_called_once()

    del os.environ["CURL_CFFI_ENABLED"]
