from scrapper import settings


class TestSettings:
    def test_bot_name(self):
        assert settings.BOT_NAME == "scrapper"

    def test_spider_modules(self):
        assert "scrapper.spiders" in settings.SPIDER_MODULES

    def test_robotstxt_obey(self):
        assert settings.ROBOTSTXT_OBEY is True

    def test_autothrottle_enabled(self):
        assert settings.AUTOTHROTTLE_ENABLED is True

    def test_retry_enabled(self):
        assert settings.RETRY_ENABLED is True

    def test_concurrent_requests(self):
        assert settings.CONCURRENT_REQUESTS == 2

    def test_download_delay(self):
        assert settings.DOWNLOAD_DELAY == 2

    def test_playwright_enabled(self):
        assert settings.PLAYWRIGHT_BROWSER_TYPE == "chromium"

    def test_item_pipelines(self):
        assert "scrapper.pipelines.ValidatePipeline" in settings.ITEM_PIPELINES

    def test_downloader_middlewares(self):
        assert "scrapper.middlewares.RetryWithBackoffMiddleware" in settings.DOWNLOADER_MIDDLEWARES