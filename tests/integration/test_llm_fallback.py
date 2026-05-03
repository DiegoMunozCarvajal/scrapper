import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from scrapy.http import HtmlResponse, Request

from scrapper.items import ProductItem
from scrapper.spiders.hotmart import HotmartSpider
from scrapper.spiders.reddit import RedditSpider

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def hotmart_response():
    html = (FIXTURES / "hotmart_search.html").read_text()
    request = Request("https://hotmart.com/search?q=python")
    return HtmlResponse(url=request.url, body=html.encode(), request=request)


@pytest.fixture
def reddit_response():
    html = (FIXTURES / "old_reddit_search.html").read_text()
    request = Request("https://old.reddit.com/search?q=python")
    return HtmlResponse(url=request.url, body=html.encode(), request=request)


class TestHotmartLLMFallback:
    def test_parse_dom_extracts_with_selectors(self, hotmart_response):
        spider = HotmartSpider()
        hotmart_response.meta["query"] = "python"
        hotmart_response.meta["limit"] = 10

        items = [i for i in spider.parse_dom(hotmart_response) if isinstance(i, ProductItem)]
        assert len(items) == 2
        assert items[0]["title"] == "Python Masterclass"
        assert items[1]["title"] == "Django for Beginners"

    def test_parse_dom_falls_back_to_llm_when_no_matches(self):
        html = "<html><body>No matching selectors here</body></html>"
        request = Request("https://hotmart.com/search?q=nonexistent")
        response = HtmlResponse(url=request.url, body=html.encode(), request=request)
        response.meta["query"] = "nonexistent"
        response.meta["limit"] = 5

        llm_response = json.loads(
            (FIXTURES / "llm_hotmart_response.json").read_text()
        )

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
                mock_client = mock_openai.return_value

                class FakeChoice:
                    def __init__(self, content):
                        self.message = MagicMock()
                        self.message.content = content

                mock_client.chat.completions.create.return_value = MagicMock(
                    choices=[FakeChoice(json.dumps(llm_response))],
                    usage=MagicMock(),
                )

                spider = HotmartSpider()
                items = list(spider.parse_dom(response))

        assert len(items) == 1
        assert items[0]["title"] == "Python Masterclass"
        assert items[0]["metadata"]["strategy"] == "llm"


def _make_reddit_spider():
    with patch.object(RedditSpider, "_load_cutoff_date", lambda self: None):
        return RedditSpider()


class TestRedditLLMFallback:
    def test_parse_extracts_with_selectors(self, reddit_response):
        spider = _make_reddit_spider()
        reddit_response.meta["query"] = "python"
        reddit_response.meta["limit"] = 10
        reddit_response.meta["count"] = 0

        items = list(spider.parse(reddit_response))
        assert len(items) >= 2
        from scrapy import Request
        assert all(isinstance(i, Request) for i in items)

    def test_parse_falls_back_to_llm_when_no_matches(self):
        html = "<html><body>No search results found</body></html>"
        request = Request("https://old.reddit.com/search?q=nonexistent")
        response = HtmlResponse(url=request.url, body=html.encode(), request=request)
        response.meta["query"] = "nonexistent"
        response.meta["limit"] = 5
        response.meta["count"] = 0

        llm_response = json.loads(
            (FIXTURES / "llm_reddit_response.json").read_text()
        )

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
                mock_client = mock_openai.return_value

                class FakeChoice:
                    def __init__(self, content):
                        self.message = MagicMock()
                        self.message.content = content

                mock_client.chat.completions.create.return_value = MagicMock(
                    choices=[FakeChoice(json.dumps(llm_response))],
                    usage=MagicMock(),
                )

                spider = _make_reddit_spider()
                items = list(spider.parse(response))

        assert len(items) == 1
        assert items[0]["title"] == "Best Python libraries in 2026"
        assert items[0]["metadata"]["strategy"] == "llm"
