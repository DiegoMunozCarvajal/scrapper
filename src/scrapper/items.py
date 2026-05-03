import scrapy
from datetime import datetime, timezone


class PostItem(scrapy.Item):
    site = scrapy.Field()
    url = scrapy.Field()
    title = scrapy.Field()
    author = scrapy.Field()
    content = scrapy.Field(default="")
    score = scrapy.Field(default=0)
    comment_count = scrapy.Field(default=0)
    published_at = scrapy.Field()
    metadata = scrapy.Field(default={})
    quality_issues = scrapy.Field()
    scraped_at = scrapy.Field()

    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            defaults = {"content": "", "score": 0, "comment_count": 0, "metadata": {}, "quality_issues": []}
            if key in defaults:
                return defaults[key]
            raise

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "scraped_at" not in self:
            self["scraped_at"] = datetime.now(timezone.utc).isoformat()


class ProductItem(scrapy.Item):
    site = scrapy.Field()
    url = scrapy.Field()
    title = scrapy.Field()
    price = scrapy.Field()
    currency = scrapy.Field(default="USD")
    rating = scrapy.Field()
    review_count = scrapy.Field(default=0)
    seller = scrapy.Field()
    availability = scrapy.Field()
    metadata = scrapy.Field(default={})
    quality_issues = scrapy.Field()
    scraped_at = scrapy.Field()

    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            defaults = {"currency": "USD", "review_count": 0, "metadata": {}, "quality_issues": []}
            if key in defaults:
                return defaults[key]
            raise

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "scraped_at" not in self:
            self["scraped_at"] = datetime.now(timezone.utc).isoformat()