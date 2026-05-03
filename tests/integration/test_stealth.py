class TestStealthHandlerConfig:
    def test_handler_is_importable(self):
        from scrapper.stealth_handler import (
            ScrapyPlaywrightStealthDownloadHandler,
        )
        assert ScrapyPlaywrightStealthDownloadHandler is not None

    def test_settings_reference_correct_handler(self):
        from scrapper import settings

        handler = settings.DOWNLOAD_HANDLERS.get("https", "")
        assert "scrapy_playwright_stealth" in handler
        assert "ScrapyPlaywrightStealthDownloadHandler" in handler

    def test_headless_env_var_defaults_to_true(self):
        from scrapper import settings

        headless_val = settings.PLAYWRIGHT_LAUNCH_OPTIONS.get("headless", None)
        assert headless_val is True

    def test_blink_features_disabled(self):
        from scrapper import settings

        args = settings.PLAYWRIGHT_LAUNCH_OPTIONS.get("args", [])
        assert "--disable-blink-features=AutomationControlled" in args

    def test_human_simulation_defaults_to_true(self):
        from scrapper import settings

        assert settings.PLAYWRIGHT_HUMAN_SIMULATION is True
