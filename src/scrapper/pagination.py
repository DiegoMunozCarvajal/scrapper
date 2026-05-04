from urllib.parse import urljoin

from scrapy import Selector


class PaginationDetector:
    """Detect next page URLs and pagination type from HTML."""

    NEXT_LINK_SELECTORS = [
        'link[rel="next"]::attr(href)',
        'a[rel="next"]::attr(href)',
        '.pagination .next::attr(href)',
        '.pagination a.next::attr(href)',
        'a.pagination-next::attr(href)',
        'a[aria-label="Next"]::attr(href)',
        'a[aria-label="Next page"]::attr(href)',
        'a.next::attr(href)',
        '.pager .next a::attr(href)',
        '.pager .next::attr(href)',
    ]

    LOAD_MORE_CSS_SELECTORS = [
        '.load-more',
        '.show-more',
        '.load-more-btn',
        '.show-more-btn',
        '[data-action="load-more"]',
    ]

    LOAD_MORE_XPATH_SELECTORS = [
        '//button[contains(text(),"Load more")]',
        '//button[contains(text(),"Show more")]',
        '//a[contains(text(),"Load more")]',
        '//a[contains(text(),"Show more")]',
    ]

    SCROLL_SELECTORS = [
        '.infinite-scroll',
        '.infinite-scroll-wrapper',
        '[data-infinite-scroll]',
        '.infinite-scroll-container',
    ]

    URL_PAGE_PATTERNS = [
        'a[href*="?page="]',
        'a[href*="&page="]',
        'a[href*="?p="]',
        'a[href*="&p="]',
        'a[href*="/page/"]',
        'a[href*="?offset="]',
        'a[href*="&offset="]',
    ]

    @staticmethod
    def _is_link_text_pagination(text: str) -> bool:
        return any(w in text for w in ("next", "siguiente", "»", ">")) or any(
            c.isdigit() for c in text
        )

    @classmethod
    def find_next_url(cls, html: str, base_url: str) -> str | None:
        if not html.strip():
            return None

        sel = Selector(text=html)

        for css_sel in cls.NEXT_LINK_SELECTORS:
            hrefs = sel.css(css_sel).getall()
            for href in hrefs:
                if href and href.strip() and href.strip() != "#":
                    return urljoin(base_url, href.strip())

        for css_sel in cls.URL_PAGE_PATTERNS:
            links = sel.css(css_sel)
            for link in links:
                href = link.css("::attr(href)").get("")
                text = "".join(link.css("::text").getall()).lower().strip()
                if href and cls._is_link_text_pagination(text):
                    return urljoin(base_url, href)

        return None

    @classmethod
    def detect_pagination_type(cls, html: str) -> str | None:
        if not html.strip():
            return None

        sel = Selector(text=html)

        for selector in cls.LOAD_MORE_XPATH_SELECTORS:
            if sel.xpath(selector).get() is not None:
                return "load_more"

        for selector in cls.LOAD_MORE_CSS_SELECTORS:
            if sel.css(selector).get() is not None:
                return "load_more"

        for selector in cls.SCROLL_SELECTORS:
            if sel.css(selector).get() is not None:
                return "scroll"

        for css_sel in cls.NEXT_LINK_SELECTORS:
            if sel.css(css_sel).get():
                return "link"

        for css_sel in cls.URL_PAGE_PATTERNS:
            links = sel.css(css_sel)
            for link in links:
                text = "".join(link.css("::text").getall()).lower().strip()
                if text and cls._is_link_text_pagination(text):
                    return "link"

        return None
