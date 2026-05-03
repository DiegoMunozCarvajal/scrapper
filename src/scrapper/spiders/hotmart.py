import json
import re
from typing import Any
from urllib.parse import quote_plus

import scrapy
from scrapy import Request
from scrapy_playwright.page import PageMethod

from ..items import ProductItem
from ..prompts.hotmart import HOTMART_PROMPT
from ..llm_extractor import llm_fallback
from ..utils import FakeFailure


class HotmartSpider(scrapy.Spider):
    name = "hotmart"
    site = "hotmart"
    site_type = "product"
    LLM_PROMPT = HOTMART_PROMPT

    custom_settings = {
        "CONCURRENT_REQUESTS": 2,
        "DOWNLOAD_DELAY": 3,
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._api_endpoint_cache = getattr(self, "_api_endpoint_cache", None)
        self._api_headers_cache = getattr(self, "_api_headers_cache", None)

    def start_requests(self):
        query = getattr(self, "query", "marketing")
        limit = int(getattr(self, "limit", 10))
        url = f"https://hotmart.com/en/marketplace/search?q={quote_plus(query)}"

        if self._api_endpoint_cache:
            page = 1
            api_url = self._api_endpoint_cache + f"?q={quote_plus(query)}&page={page}&size={limit}"
            yield Request(
                api_url,
                callback=self.parse_api,
                meta={"query": query, "limit": limit, "page": page, "strategy": "api"},
                headers=self._api_headers_cache or {},
                errback=lambda f: self._fallback_to_playwright(f, query, limit),
            )
        else:
            yield Request(
                url,
                callback=self.discover_api_callback,
                meta={
                    "playwright": True,
                    "playwright_page_methods": [
                        PageMethod(_intercept_api_calls, query),
                    ],
                    "query": query,
                    "limit": limit,
                },
            )

    def discover_api_callback(self, response):
        """Read intercepted API calls from PageMethod result."""
        query = response.meta["query"]
        limit = response.meta["limit"]

        intercepted = []
        methods = response.meta.get("playwright_page_methods", [])
        if methods and methods[0].result is not None:
            intercepted = methods[0].result

        if intercepted:
            self.logger.info(f"Intercepted {len(intercepted)} API calls")

            best = None
            for call in intercepted:
                url = call["url"]
                if "search" in url.lower():
                    base = re.sub(r"[?&]q=[^&]*", "", url)
                    base = re.sub(r"[?&]page=\d+", "", base)
                    base = re.sub(r"[?&]size=\d+", "", base)
                    best = base
                    self._api_headers_cache = call.get("headers", {})
                    break

            if best:
                self._api_endpoint_cache = best
                self.logger.info(f"Cached API endpoint: {best}")
                page_num = 1
                api_url = f"{best}?q={quote_plus(query)}&page={page_num}&size={limit}"
                yield Request(
                    api_url,
                    callback=self.parse_api,
                    meta={
                        "query": query,
                        "limit": limit,
                        "page": page_num,
                        "strategy": "api",
                    },
                    headers=self._api_headers_cache,
                )
                return

        self.logger.info("No API endpoint found, falling back to DOM scraping")
        yield from self.parse_dom(response)

    def parse_api(self, response):
        """Strategy 1: Parse JSON from internal API."""
        query = response.meta["query"]
        limit = response.meta["limit"]
        page = response.meta["page"]

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            self.logger.warning("API response not valid JSON, falling back to DOM")
            yield from self._fallback_to_playwright(
                FakeFailure(response), query, limit
            )
            return

        products = self._extract_products_from_json(data)
        count = 0

        for product in products:
            if count >= limit:
                return
            count += 1
            product["metadata"]["query"] = query
            yield ProductItem(product)

        if count < limit:
            pagination = data.get("data", {}).get("search", {}).get("pagination", {})
            total_pages = pagination.get("totalPages", 1)
            if page < total_pages:
                next_page = page + 1
                api_url = (
                    self._api_endpoint_cache
                    + f"?q={quote_plus(query)}&page={next_page}&size={limit}"
                )
                yield Request(
                    api_url,
                    callback=self.parse_api,
                    meta={
                        "query": query,
                        "limit": limit,
                        "page": next_page,
                        "strategy": "api",
                    },
                    headers=self._api_headers_cache or {},
                )

    def _extract_products_from_json(self, data):
        """Extract product dicts from JSON structure (tries multiple paths)."""
        products = []

        def _search(obj, depth=0):
            if depth > 10:
                return
            if isinstance(obj, dict):
                if "name" in obj and "url" in obj:
                    price = None
                    price_obj = obj.get("price")
                    if isinstance(price_obj, dict):
                        price = price_obj.get("value")
                    elif isinstance(price_obj, (int, float)):
                        price = float(price_obj)

                    author = obj.get("author", {})
                    if isinstance(author, dict):
                        author = author.get("name", "")
                    elif not isinstance(author, str):
                        author = ""

                    review_count = obj.get("reviewCount", 0) or obj.get(
                        "review_count", 0
                    )

                    products.append({
                        "site": self.site,
                        "url": obj["url"],
                        "title": obj["name"],
                        "price": price,
                        "currency": (
                            obj.get("price", {}).get("currency", "USD")
                            if isinstance(obj.get("price"), dict)
                            else "USD"
                        ),
                        "rating": float(obj.get("rating", 0) or 0) or None,
                        "review_count": int(review_count),
                        "seller": author,
                        "availability": "",
                        "metadata": {},
                    })
                if not products:
                    for v in obj.values():
                        _search(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    _search(item, depth + 1)

        _search(data)
        return products

    def _fallback_to_playwright(self, failure, query, limit):
        """Fallback: use Playwright DOM scraping."""
        url = f"https://hotmart.com/en/marketplace/search?q={quote_plus(query)}"
        yield Request(
            url,
            callback=self.parse_dom,
            meta={
                "playwright": True,
                "query": query,
                "limit": limit,
                "strategy": "playwright",
                "page": 1,
            },
        )

    def parse(self, response):
        """Alias for DOM parsing (Strategy 2 fallback)."""
        return self.parse_dom(response)

    def parse_dom(self, response):
        limit = response.meta["limit"]
        query = response.meta["query"]
        page = response.meta.get("page", 1)

        cards = response.css("div.product-card-alt")
        count = 0

        for card in cards:
            if count >= limit:
                break

            title_el = card.css(".product-card-alt__title")
            title = title_el.css("::text").get("")

            author_el = card.css(".product-card-alt__author")
            author = author_el.css("::text").get("")

            rating_el = card.css(".product-card-alt__rating span::text")
            rating = rating_el.get("")

            price_el = card.css(".product-card-alt__price::text")
            price_text = price_el.get("")

            reviews_el = card.css(".product-card-alt__reviews::text")
            reviews_text = reviews_el.get("")

            url_el = card.css("a.product-link::attr(href)")
            url = url_el.get("")

            title = title.strip() if title else ""
            author = author.strip() if author else ""

            if not title or not url:
                continue

            review_count = _parse_review_count(reviews_text)
            price = _parse_price(price_text)

            count += 1
            yield ProductItem(
                site=self.site,
                url=url,
                title=title,
                price=price,
                currency="USD",
                rating=float(rating) if rating else None,
                review_count=review_count,
                seller=author,
                availability="",
                metadata={"query": query, "strategy": "playwright"},
            )

        if count == 0:
            self.logger.warning("DOM selectors found nothing, trying LLM fallback")
            yield from llm_fallback(self, response, ProductItem)
            return

        if count >= limit:
            return

        next_page = page + 1
        yield Request(
            response.url,
            callback=self.parse_dom,
            meta={
                "playwright": True,
                "playwright_page_methods": [
                    PageMethod("wait_for_timeout", 1000),
                    PageMethod(_click_load_more),
                ],
                "query": query,
                "limit": limit,
                "page": next_page,
                "strategy": "playwright",
            },
            dont_filter=True,
        )


def _parse_price(text):
    """Extract float price from text like '$49.99' or 'R$ 79,90'."""
    if not text:
        return None
    try:
        cleaned = "".join(c for c in text if c.isdigit() or c in ".,")
        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


def _parse_review_count(text):
    """Extract integer review count from text like '234 reviews'."""
    if not text:
        return 0
    try:
        numbers = re.findall(r"\d+", text)
        return int(numbers[0]) if numbers else 0
    except (ValueError, IndexError):
        return 0


async def _intercept_api_calls(page, query):
    """PageMethod callable: intercept API requests and return them."""
    intercepted: list[dict[str, Any]] = []

    async def capture_route(route):
        url = route.request.url
        if any(kw in url.lower() for kw in ["search", "product", "graphql", "/api/"]):
            intercepted.append({
                "url": url,
                "method": route.request.method,
                "headers": dict(route.request.headers),
                "post_data": route.request.post_data,
            })
        await route.continue_()

    await page.route("**/*", capture_route)
    await page.wait_for_timeout(5000)
    return intercepted


async def _click_load_more(page):
    """PageMethod callable: click the load-more button if present."""
    button = page.locator("button.load-more-btn")
    if await button.count() > 0:
        await button.click()
        await page.wait_for_timeout(2000)
        return True
    return False


