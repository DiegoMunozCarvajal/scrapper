# tests/unit/test_generic_pagination.py

from scrapper.pagination import PaginationDetector


class TestFindNextUrl:
    def test_rel_next_in_link_head(self):
        html = '<html><head><link rel="next" href="https://example.com/?page=2"></head><body></body></html>'
        url = PaginationDetector.find_next_url(html, "https://example.com/")
        assert url == "https://example.com/?page=2"

    def test_a_rel_next_in_body(self):
        html = '<html><body><a rel="next" href="/page/2">Next</a></body></html>'
        url = PaginationDetector.find_next_url(html, "https://example.com/")
        assert url == "https://example.com/page/2"

    def test_pagination_next_class(self):
        html = '<div class="pagination"><a class="next" href="?page=3">Next</a></div>'
        url = PaginationDetector.find_next_url(html, "https://example.com/search")
        assert url == "https://example.com/search?page=3"

    def test_aria_label_next(self):
        html = '<a aria-label="Next" href="/products?offset=20">Next</a>'
        url = PaginationDetector.find_next_url(html, "https://shop.example.com/products")
        assert url == "https://shop.example.com/products?offset=20"

    def test_url_pattern_page_number(self):
        html = '<html><body><a href="?p=2">Page 2</a></body></html>'
        url = PaginationDetector.find_next_url(html, "https://example.com/")
        assert url == "https://example.com/?p=2"

    def test_url_pattern_page_keyword(self):
        html = '<html><body><a href="/blog/page/2/">Next</a></body></html>'
        url = PaginationDetector.find_next_url(html, "https://example.com/blog/")
        assert url == "https://example.com/blog/page/2/"

    def test_no_pagination_returns_none(self):
        html = '<html><body><p>No pagination here</p></body></html>'
        url = PaginationDetector.find_next_url(html, "https://example.com/")
        assert url is None

    def test_relative_url_resolved(self):
        html = '<a rel="next" href="../page/2">Next</a>'
        url = PaginationDetector.find_next_url(html, "https://example.com/catalog/1")
        assert url == "https://example.com/page/2"

    def test_empty_html_returns_none(self):
        assert PaginationDetector.find_next_url("", "https://example.com/") is None

    def test_duplicate_next_links_uses_first(self):
        html = (
            '<a rel="next" href="/page/2">Next</a>'
            '<a rel="next" href="/page/3">Also Next</a>'
        )
        url = PaginationDetector.find_next_url(html, "https://example.com/")
        assert url == "https://example.com/page/2"


class TestDetectLoadMore:
    def test_load_more_button_detected(self):
        html = '<button>Load more</button>'
        assert PaginationDetector.detect_pagination_type(html) == "load_more"

    def test_show_more_button_detected(self):
        html = '<button>Show more results</button>'
        assert PaginationDetector.detect_pagination_type(html) == "load_more"

    def test_load_more_class_detected(self):
        html = '<div class="load-more">Click</div>'
        assert PaginationDetector.detect_pagination_type(html) == "load_more"

    def test_infinite_scroll_detected(self):
        html = '<div class="infinite-scroll"></div>'
        assert PaginationDetector.detect_pagination_type(html) == "scroll"

    def test_no_load_more_returns_link_when_next_present(self):
        html = '<a rel="next" href="/page/2">Next</a>'
        result = PaginationDetector.detect_pagination_type(html)
        assert result == "link"

    def test_no_pagination_returns_none(self):
        html = '<html><body><p>Hello</p></body></html>'
        assert PaginationDetector.detect_pagination_type(html) is None

    def test_empty_html_returns_none_detect(self):
        assert PaginationDetector.detect_pagination_type("") is None

    def test_load_more_overrides_link(self):
        html = '<a rel="next" href="/page/2">Next</a><button class="load-more">Load more</button>'
        assert PaginationDetector.detect_pagination_type(html) == "load_more"

    def test_scroll_overrides_link(self):
        html = '<a rel="next" href="/page/2">Next</a><div class="infinite-scroll"></div>'
        assert PaginationDetector.detect_pagination_type(html) == "scroll"
