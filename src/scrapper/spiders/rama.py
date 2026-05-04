import re
from html import unescape

import scrapy
from scrapy import Request
from scrapy_playwright.page import PageMethod

from ..items import GenericItem


async def _wait_for_load(page):
    """PageMethod: wait for the search page to be ready."""
    await page.wait_for_selector("#searchForm\\:searchButton, [id=\"searchForm:searchButton\"]", timeout=15000)
    return True


class RamaSpider(scrapy.Spider):
    """Spider for Rama Judicial - Corte Suprema de Justicia.

    Uses Playwright to fill search form and click search. Extracts data
    from the PrimeFaces AJAX XML response using page.route() interception.

    Usage:
        scrapy crawl rama -a query="derecho fundamental" -a limit=30
    """

    name = "rama"
    site = "ramajudicial"

    custom_settings = {
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 3,
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
    }

    def start_requests(self):
        query = getattr(self, "query", "derecho fundamental")
        limit = int(getattr(self, "limit", "20"))

        yield Request(
            url="https://consultajurisprudencial.ramajudicial.gov.co/WebRelatoria/csj/index.xhtml",
            callback=self.parse,
            meta={
                "playwright": True,
                "playwright_include_page": True,
                "playwright_page_methods": [
                    PageMethod(_wait_for_load),
                ],
                "query": query,
                "limit": limit,
            },
        )

    async def parse(self, response):
        query = response.meta["query"]
        limit = response.meta["limit"]
        page_obj = response.meta.get("playwright_page")

        if not page_obj:
            return

        xml_text = None

        async def _capture(route):
            nonlocal xml_text
            resp = await route.fetch()
            ct = resp.headers.get("content-type", "")
            if "xml" in ct.lower() and "xhtml" in route.request.url:
                try:
                    xml_text = await resp.text()
                except Exception:
                    pass
            await route.fulfill(response=resp)

        await page_obj.route("**/*", _capture)

        total_yielded = response.meta.get("_total_yielded", 0)
        is_first = "_page" not in response.meta

        if is_first:
            await page_obj.locator('input[name="searchForm:temaInput"]').fill(query)
            await page_obj.locator("#searchForm\\:searchButton").click()
            await page_obj.wait_for_timeout(15000)
        else:
            next_page_num = response.meta["_page"] + 2
            self.logger.info("Clicking page %d (%d items so far)", next_page_num, total_yielded)
            try:
                btn = page_obj.locator(f'.ui-paginator-page:has-text("{next_page_num}")').first
                if await btn.count() == 0:
                    btn = page_obj.locator(".ui-paginator-next").first
                await btn.click()
                await page_obj.wait_for_timeout(10000)
            except Exception as e:
                self.logger.warning("Pagination click failed: %s", e)
                await page_obj.unroute("**/*.xhtml")
                await page_obj.close()
                return

        await page_obj.unroute("**/*.xhtml")

        if not xml_text:
            self.logger.warning("No XML captured")
            await page_obj.close()
            return

        items = self._parse_xml(xml_text, query)
        for item_data in items:
            if total_yielded >= limit:
                break
            total_yielded += 1
            yield GenericItem(
                site=self.site,
                url=item_data.get("url", ""),
                title=item_data.get("title", ""),
                content=item_data.get("content", ""),
                page_type="jurisprudencia",
                metadata={
                    "strategy": "jsf_xml",
                    "query": query,
                    "extras": {k: v for k, v in item_data.items() if k not in ("url", "title", "content")},
                },
            )

        if total_yielded >= limit:
            self.logger.info("Reached limit of %d items", limit)
            await page_obj.close()
            return

        next_page = response.meta.get("_page", 0) + 1
        yield Request(
            url=response.url,
            callback=self.parse,
            meta={
                "playwright": True,
                "playwright_page": page_obj,
                "playwright_include_page": True,
                "query": query,
                "limit": limit,
                "_page": next_page,
                "_total_yielded": total_yielded,
            },
            dont_filter=True,
        )

    @staticmethod
    def _parse_xml(xml_text, query):
        cdatas = re.findall(r"<!\[CDATA\[(.*?)\]\]>", xml_text, re.DOTALL)
        items = []
        seen = set()

        for cdata in cdatas:
            trs = re.findall(r"<tr[^>]*role=\"row\"[^>]*>(.*?)</tr>", cdata, re.DOTALL)
            for tr_html in trs:
                text = re.sub(r"<[^>]+>", " ", tr_html)
                text = re.sub(r"&nbsp;", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
                text = unescape(text)

                if not text or len(text) < 30 or "ui-button" in text:
                    continue

                if text in seen:
                    continue
                seen.add(text)

                item = {"title": "", "url": "", "content": text}

                m = re.search(r"ID:\s*(\d+)", text)
                if m:
                    item["id"] = m.group(1)
                    item["url"] = f"https://consultajurisprudencial.ramajudicial.gov.co/WebRelatoria/csj/index.xhtml?id={m.group(1)}"

                m = re.search(r"PROVIDENCIA:\s*([A-Z]{2,}\d+[-/]\d+)", text)
                if m:
                    item["providencia"] = m.group(1)
                    item["title"] = m.group(1)

                m = re.search(r"PROCESO:\s*([\d-]+)", text)
                if m:
                    item["proceso"] = m.group(1)

                m = re.search(r"CLASE DE ACTUACI[ÓO]N:\s*([^A-Z]+?)(?=[A-Z]{2,})", text)
                if m:
                    item["clase"] = m.group(1).strip()

                m = re.search(r"TIPO DE PROVIDENCIA:\s*(\w+)", text)
                if m:
                    item["tipo"] = m.group(1)

                m = re.search(r"FECHA:\s*(\d{2}/\d{2}/\d{4})", text)
                if m:
                    item["fecha"] = m.group(1)

                m = re.search(r"PONENTE:\s*(.+?)(?=TEMA:|$)", text)
                if m:
                    item["ponente"] = m.group(1).strip()

                m = re.search(r"TEMA:\s*(.+?)$", text)
                if m:
                    item["tema"] = m.group(1).strip()
                    item["content"] = m.group(1).strip()

                m = re.search(r"SALA\s*(DE\s*)?([A-ZÁÉÍÓÚ\s]+)\s+ID:", text)
                if m:
                    item["sala"] = m.group(2).strip()

                if not item["title"]:
                    item["title"] = item.get("providencia") or item.get("id") or text[:80]

                items.append(item)

        return items
