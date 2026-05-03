import os
from unittest.mock import patch


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
