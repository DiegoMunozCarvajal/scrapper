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


class OddsItem(scrapy.Item):
    """Cuotas de apuestas deportivas scrapeadas de sportsbooks."""

    site = scrapy.Field()  # "stake", "pinnacle", etc.
    sport = scrapy.Field()  # "tennis", "football", "basketball"
    league = scrapy.Field()  # "ATP", "WTA", "Challenger"
    tournament = scrapy.Field()  # "Wimbledon", "US Open"
    match_date = scrapy.Field()  # Fecha programada del partido
    commence_time = scrapy.Field()  # ISO datetime de inicio (Kambi: date_start)
    title = scrapy.Field()  # "Jugador A vs Jugador B" — requerido por ValidatePipeline
    player_a = scrapy.Field()  # Jugador/Equipo A
    player_b = scrapy.Field()  # Jugador/Equipo B
    odds_a = scrapy.Field()  # Cuota decimal jugador A
    odds_b = scrapy.Field()  # Cuota decimal jugador B
    surface = scrapy.Field()  # clay, hard, grass, carpet
    market_type = scrapy.Field()  # "moneyline", "spread", "totals"
    url = scrapy.Field()  # URL única por partido para dedup
    metadata = scrapy.Field()  # Datos extra (live, in_play, etc.)
    quality_issues = scrapy.Field()
    scraped_at = scrapy.Field()

    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            defaults = {
                "surface": "hard",
                "market_type": "moneyline",
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
