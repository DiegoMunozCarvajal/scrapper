import json
import os
from unittest.mock import MagicMock, patch

from scrapy.http import HtmlResponse, Request

from scrapper.spiders.generic import GenericSpider


def test_spider_has_correct_attributes():
    spider = GenericSpider()
    assert spider.name == "generic"
    assert spider.site == "generic"


def test_start_requests_yields_request_with_url():
    spider = GenericSpider()
    spider.url = "https://example.com/page"
    spider.type = "product"

    requests = list(spider.start_requests())
    assert len(requests) == 1
    req = requests[0]
    assert req.url == "https://example.com/page"
    assert req.meta["task_type"] == "product"
    assert req.meta["site"] == "example.com"
    assert req.meta["task_url"] == "https://example.com/page"


def test_start_requests_without_url_logs_error_and_returns_nothing():
    spider = GenericSpider()
    requests = list(spider.start_requests())
    assert requests == []


def test_start_requests_without_type():
    spider = GenericSpider()
    spider.url = "https://blog.example.com/post-1"
    # spider.type is not set

    requests = list(spider.start_requests())
    assert len(requests) == 1
    assert requests[0].meta["task_type"] is None


def test_parse_extracts_with_llm():
    html = "<html><body><h1>Python Book - $29.99</h1></body></html>"
    request = Request("https://example.com/python-book")
    response = HtmlResponse(url=request.url, body=html.encode(), request=request)
    response.meta["site"] = "example.com"
    response.meta["task_url"] = request.url

    llm_data = {"page_type": "product", "items": [
        {"title": "Python Book", "url": "https://example.com/python-book", "price": 29.99, "rating": 4.5, "review_count": 120}
    ]}

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
            mock_client = mock_openai.return_value

            class FakeChoice:
                def __init__(self, content):
                    self.message = MagicMock()
                    self.message.content = content

            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[FakeChoice(json.dumps(llm_data))],
                usage=MagicMock(),
            )

            spider = GenericSpider()
            items = list(spider.parse(response))

    assert len(items) == 1
    assert items[0]["title"] == "Python Book"
    assert items[0]["site"] == "example.com"
    assert items[0]["price"] == 29.99
    assert items[0]["metadata"]["strategy"] == "llm"


def test_parse_uses_type_hint_prompt():
    html = "<html><body>Article content here</body></html>"
    request = Request("https://blog.example.com/post")
    response = HtmlResponse(url=request.url, body=html.encode(), request=request)
    response.meta["site"] = "blog.example.com"
    response.meta["task_url"] = request.url
    response.meta["task_type"] = "article"

    llm_data = {"page_type": "article", "items": [
        {"title": "My Article", "url": "https://blog.example.com/post", "content": "Article content here", "author": "Jane"}
    ]}

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
            mock_client = mock_openai.return_value

            class FakeChoice:
                def __init__(self, content):
                    self.message = MagicMock()
                    self.message.content = content

            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[FakeChoice(json.dumps(llm_data))],
                usage=MagicMock(),
            )

            spider = GenericSpider()
            original_prompt = spider.LLM_PROMPT
            items = list(spider.parse(response))

    assert len(items) == 1
    assert items[0]["page_type"] == "article"
    # Prompt was modified with type hint
    assert spider.LLM_PROMPT != original_prompt


def test_parse_returns_nothing_when_llm_disabled():
    html = "<html><body>Test</body></html>"
    request = Request("https://example.com/page")
    response = HtmlResponse(url=request.url, body=html.encode(), request=request)
    response.meta["site"] = "example.com"
    response.meta["task_url"] = request.url

    with patch.dict(os.environ, {"LLM_ENABLED": "false", "OPENAI_API_KEY": "test-key"}):
        spider = GenericSpider()
        items = list(spider.parse(response))

    # No items extracted → falls back to Playwright retry
    assert len(items) == 1
    assert items[0].meta["playwright"] is True


def test_parse_falls_back_to_playwright_when_no_items():
    html = "<html><body><h1>Empty page</h1></body></html>"
    request = Request("https://js-heavy.example.com")
    response = HtmlResponse(url=request.url, body=html.encode(), request=request)
    response.meta["site"] = "js-heavy.example.com"
    response.meta["task_url"] = request.url

    llm_data = {"page_type": "other", "items": []}

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
            mock_client = mock_openai.return_value

            class FakeChoice:
                def __init__(self, content):
                    self.message = MagicMock()
                    self.message.content = content

            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[FakeChoice(json.dumps(llm_data))],
                usage=MagicMock(),
            )

            spider = GenericSpider()
            items = list(spider.parse(response))

    # Should yield a Playwright retry request
    assert len(items) == 1
    pw_request = items[0]
    assert isinstance(pw_request, Request)
    assert pw_request.meta["playwright"] is True
    assert pw_request.meta["_playwright_retry"] is True
    assert pw_request.dont_filter is True


def test_parse_does_not_retry_playwright_twice():
    html = "<html><body>Still empty</body></html>"
    request = Request("https://js-heavy.example.com")
    response = HtmlResponse(url=request.url, body=html.encode(), request=request)
    response.meta["site"] = "js-heavy.example.com"
    response.meta["task_url"] = request.url
    response.meta["_playwright_retry"] = True  # Already retried

    llm_data = {"page_type": "other", "items": []}

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
            mock_client = mock_openai.return_value

            class FakeChoice:
                def __init__(self, content):
                    self.message = MagicMock()
                    self.message.content = content

            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[FakeChoice(json.dumps(llm_data))],
                usage=MagicMock(),
            )

            spider = GenericSpider()
            items = list(spider.parse(response))

    # Should NOT yield another Playwright request
    assert items == []


def test_handle_error_logs_message():
    spider = GenericSpider()
    failure = MagicMock()
    failure.request.url = "https://broken.example.com"
    failure.value = Exception("Connection refused")

    spider._handle_error(failure)
    # No exception raised, error is logged
