import json
from unittest.mock import MagicMock, patch

from scrapper.llm_extractor import LLMExtractor


class FakeChoice:
    def __init__(self, content):
        self.message = MagicMock()
        self.message.content = content


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]
        self.usage = MagicMock()
        self.usage.total_tokens = 100


def test_extract_calls_openai_and_returns_items():
    fake_html = "<div>Product: Python Course, Price: $49.99</div>"
    fake_prompt = "Extract products from: {html}"
    expected_response = json.dumps({
        "products": [{"title": "Python Course", "url": "/course", "price": 49.99}]
    })

    with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
        mock_client = mock_openai.return_value
        mock_client.chat.completions.create.return_value = FakeCompletion(expected_response)

        extractor = LLMExtractor(model="gpt-4o-mini", cache_ttl=0)
        result = extractor.extract(
            html=fake_html,
            prompt_template=fake_prompt,
            item_class=None,
            site="hotmart",
            query="python",
        )

        assert len(result) == 1
        assert result[0]["title"] == "Python Course"
        assert result[0]["price"] == 49.99
        mock_client.chat.completions.create.assert_called_once()


def test_extract_cache_hit_skips_openai():
    fake_html = "<div>Product: Test</div>"
    fake_prompt = "Extract: {html}"

    with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
        extractor = LLMExtractor(model="gpt-4o-mini", cache_ttl=86400)
        extractor.cache.set("test_key", [{"title": "Cached"}])

        with patch.object(extractor, "_cache_key", return_value="test_key"):
            result = extractor.extract(
                html=fake_html,
                prompt_template=fake_prompt,
                item_class=None,
                site="hotmart",
                query="python",
            )

        assert len(result) == 1
        assert result[0]["title"] == "Cached"
        mock_openai.return_value.chat.completions.create.assert_not_called()


def test_extract_strips_unknown_fields():
    fake_html = "<div>test</div>"
    fake_prompt = "Extract: {html}"
    expected_response = json.dumps({
        "products": [{"title": "OK", "unknown_field": "should be removed"}]
    })

    class FakeItem:
        fields = {"title": None, "url": None, "price": None}

    with patch("scrapper.llm_extractor.OpenAI") as mock_openai:
        mock_client = mock_openai.return_value
        mock_client.chat.completions.create.return_value = FakeCompletion(expected_response)

        extractor = LLMExtractor(cache_ttl=0)
        result = extractor.extract(
            html=fake_html,
            prompt_template=fake_prompt,
            item_class=FakeItem,
            site="hotmart",
            query="python",
        )

        assert len(result) == 1
        assert "title" in result[0]
        assert "unknown_field" not in result[0]


def test_chunk_html_splits_large_content():
    with patch("scrapper.llm_extractor.OpenAI"):
        extractor = LLMExtractor()
    small_html = "<div>" + "x" * 500 + "</div>"
    chunks = extractor._chunk_html(small_html, max_chars=1000)
    assert len(chunks) == 1

    big_html = "<div>" + "x" * 5000 + "</div>"
    chunks = extractor._chunk_html(big_html, max_chars=2000)
    assert len(chunks) > 1
