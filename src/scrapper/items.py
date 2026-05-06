import scrapy
from datetime import datetime, timezone


class PostItem(scrapy.Item):
    site = scrapy.Field()
    url = scrapy.Field()
    title = scrapy.Field()
    author = scrapy.Field()
    content = scrapy.Field()
    score = scrapy.Field()
    comment_count = scrapy.Field()
    published_at = scrapy.Field()
    thumbnail = scrapy.Field()
    link_flair = scrapy.Field()
    domain = scrapy.Field()
    nsfw = scrapy.Field()
    is_self_post = scrapy.Field()
    permalink = scrapy.Field()
    metadata = scrapy.Field()
    quality_issues = scrapy.Field()
    scraped_at = scrapy.Field()

    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            defaults = {
                "content": "",
                "score": 0,
                "comment_count": 0,
                "metadata": {},
                "quality_issues": [],
                "nsfw": False,
                "is_self_post": False,
            }
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
    currency = scrapy.Field()
    rating = scrapy.Field()
    review_count = scrapy.Field()
    seller = scrapy.Field()
    availability = scrapy.Field()
    metadata = scrapy.Field()
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


class GenericItem(scrapy.Item):
    site = scrapy.Field()
    url = scrapy.Field()
    page_type = scrapy.Field()
    title = scrapy.Field()
    content = scrapy.Field()
    price = scrapy.Field()
    currency = scrapy.Field()
    rating = scrapy.Field()
    review_count = scrapy.Field()
    score = scrapy.Field()
    author = scrapy.Field()
    image_url = scrapy.Field()
    category = scrapy.Field()
    published_at = scrapy.Field()
    metadata = scrapy.Field()
    quality_issues = scrapy.Field()
    scraped_at = scrapy.Field()

    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            defaults = {
                "currency": "USD",
                "review_count": 0,
                "metadata": {},
                "quality_issues": [],
            }
            if key in defaults:
                return defaults[key]
            raise

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "scraped_at" not in self:
            self["scraped_at"] = datetime.now(timezone.utc).isoformat()