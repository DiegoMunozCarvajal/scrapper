from scrapper.spiders.reddit import RedditSpider
from scrapper.spiders.amazon import AmazonSpider


class TestRedditSpider:
    def test_has_parse_post_method(self):
        spider = RedditSpider()
        assert hasattr(spider, "parse_post")
        assert callable(spider.parse_post)

    def test_custom_settings(self):
        spider = RedditSpider()
        assert spider.custom_settings["DOWNLOAD_HANDLERS"] == {}
        assert spider.custom_settings["CONCURRENT_REQUESTS"] == 1
        assert spider.custom_settings["DOWNLOAD_DELAY"] == 2


class TestAmazonSpider:
    def test_has_parse_product_method(self):
        spider = AmazonSpider()
        assert hasattr(spider, "parse_product")
        assert callable(spider.parse_product)

    def test_custom_settings(self):
        spider = AmazonSpider()
        assert spider.custom_settings["CONCURRENT_REQUESTS"] == 1
        assert spider.custom_settings["DOWNLOAD_DELAY"] == 5
        assert spider.custom_settings["PLAYWRIGHT_BROWSER_TYPE"] == "chromium"