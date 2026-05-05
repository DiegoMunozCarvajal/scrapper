import os
from unittest.mock import MagicMock, patch

from scrapy import Request
from scrapy.http import TextResponse
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
        "scrapper.stealth_handler.ScrapyPlaywrightStealthDownloadHandler._download_request",
        new_callable=MagicMock,
    ) as mock_parent:
        mock_parent.return_value = Deferred()

        handler = CurlCffiDownloadHandler.__new__(CurlCffiDownloadHandler)
        handler.settings = {}

        deferred = handler._download_request(request, spider)
        assert deferred is not None
        mock_parent.assert_called_once()

    del os.environ["CURL_CFFI_ENABLED"]


def test_curl_cffi_preserves_method_body_headers_proxy_and_timeout(monkeypatch):
    monkeypatch.setenv("CURL_CFFI_ENABLED", "true")
    from scrapper.curl_cffi_handler import CurlCffiDownloadHandler  # noqa: F811

    request = Request(
        "https://example.com/api",
        method="POST",
        body=b'{"q":"python"}',
        headers={"User-Agent": "UA", "Content-Type": "application/json"},
        meta={"proxy": "http://proxy:8080", "download_timeout": 12},
    )
    spider = MagicMock()
    spider.logger = MagicMock()

    fake_response = MagicMock()
    fake_response.url = "https://example.com/api"
    fake_response.status_code = 201
    fake_response.headers = {"content-type": "application/json"}
    fake_response.content = b'{"ok":true}'

    handler = CurlCffiDownloadHandler.__new__(CurlCffiDownloadHandler)
    handler._crawler = MagicMock()
    handler._crawler.settings.getfloat.return_value = 30.0

    with patch("curl_cffi.requests.request", return_value=fake_response) as request_mock:
        with patch("twisted.internet.threads.deferToThread") as defer_mock:
            handler._download_request(request, spider)

        positional_args = defer_mock.call_args[0]
        assert len(positional_args) == 1

        result = positional_args[0]()

    _, kwargs = request_mock.call_args
    assert kwargs["method"] == "POST"
    assert kwargs["data"] == b'{"q":"python"}'
    assert kwargs["headers"]["User-Agent"] == "UA"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["timeout"] == 12
    assert kwargs["proxy"] == "http://proxy:8080"
    assert isinstance(result, TextResponse)
