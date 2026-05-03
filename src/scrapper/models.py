from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Post:
    title: str
    url: str
    author: str
    content: str = ""
    score: int = 0
    comment_count: int = 0
    published_at: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Product:
    title: str
    url: str
    price: Optional[float] = None
    currency: str = "USD"
    rating: Optional[float] = None
    review_count: int = 0
    seller: str = ""
    availability: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class ScrapeResult:
    source: str
    query: str
    posts: list[Post] = field(default_factory=list)
    products: list[Product] = field(default_factory=list)
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
