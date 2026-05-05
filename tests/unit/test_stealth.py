import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from scrapy import Request


class TestStealthHandler:
    def test_handler_class_exists(self):
        from scrapper.stealth_handler import ScrapyPlaywrightStealthDownloadHandler
        assert ScrapyPlaywrightStealthDownloadHandler is not None

    def test_headless_env_var_parsed(self):
        with patch.dict(os.environ, {"HEADLESS": "true"}):
            result = os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes")
            assert result is True

    def test_headless_env_var_false(self):
        with patch.dict(os.environ, {"HEADLESS": "false"}):
            result = os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes")
            assert result is False

    def test_human_simulation_env_var_parsed(self):
        with patch.dict(os.environ, {"PLAYWRIGHT_HUMAN_SIMULATION": "true"}):
            result = os.getenv("PLAYWRIGHT_HUMAN_SIMULATION", "true").lower() in ("true", "1", "yes")
            assert result is True


@pytest.mark.asyncio
async def test_cookie_state_list_is_loaded_as_storage_state(tmp_path):
    from scrapper.stealth_handler import _load_storage_state

    cookie_file = tmp_path / "default.json"
    cookie_file.write_text(json.dumps([{"name": "sid", "value": "1", "domain": "example.com", "path": "/"}]))

    state = _load_storage_state(cookie_file)

    assert state == {
        "cookies": [{"name": "sid", "value": "1", "domain": "example.com", "path": "/"}],
        "origins": [],
    }


def test_playwright_request_gets_init_callback():
    from scrapper.stealth_handler import ScrapyPlaywrightStealthDownloadHandler

    handler = ScrapyPlaywrightStealthDownloadHandler.__new__(ScrapyPlaywrightStealthDownloadHandler)
    request = Request("https://example.com", meta={"playwright": True})

    handler._ensure_page_init_callback(request)

    assert callable(request.meta["playwright_page_init_callback"])


@pytest.mark.asyncio
async def test_save_storage_state_writes_full_state(tmp_path):
    from scrapper.stealth_handler import _save_storage_state

    context = MagicMock()
    context.storage_state = AsyncMock(return_value={"cookies": [{"name": "sid"}], "origins": [{"origin": "https://example.com"}]})
    cookie_file = tmp_path / "default.json"

    await _save_storage_state(context, cookie_file)

    assert json.loads(cookie_file.read_text()) == {"cookies": [{"name": "sid"}], "origins": [{"origin": "https://example.com"}]}
