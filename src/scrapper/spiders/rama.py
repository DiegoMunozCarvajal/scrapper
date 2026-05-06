import asyncio
import re
from html import unescape
from pathlib import Path

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

    Uses Playwright to fill the search form and navigate results via
    PrimeFaces paginator. All pagination happens within a single async
    parse call.

    Usage:
        scrapy crawl rama -a query="derecho fundamental" -a limit=30
        scrapy crawl rama -a query="sucesion" -a limit=10 -a download=1
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
        download = getattr(self, "download", None)
        download_dir = getattr(self, "download_dir", "downloads/rama")

        yield Request(
            url="https://consultajurisprudencial.ramajudicial.gov.co/WebRelatoria/csj/index.xhtml",
            callback=self.parse,
            errback=self._errback_close_page,
            meta={
                "playwright": True,
                "playwright_include_page": True,
                "playwright_page_methods": [
                    PageMethod(_wait_for_load),
                ],
                "query": query,
                "limit": limit,
                "download": download and download not in ("0", "false", "no"),
                "download_dir": download_dir,
            },
        )

    async def parse(self, response):
        query = response.meta["query"]
        limit = response.meta["limit"]
        download = response.meta.get("download", False)
        download_dir = response.meta.get("download_dir", "downloads/rama")
        page_obj = response.meta.get("playwright_page")

        if not page_obj:
            return

        captured_xml = []
        _search_clicked = False

        def _on_response(resp):
            ct = resp.headers.get("content-type", "")
            if "xml" in ct.lower() and "xhtml" in resp.url and _search_clicked:
                captured_xml.append(resp)

        page_obj.on("response", _on_response)

        total_yielded = 0
        seen = set()
        page_num = 0
        max_pages = min(limit * 2, 200)
        download_tasks = []

        try:
            await page_obj.locator('input[name="searchForm:temaInput"]').fill(query)
            _search_clicked = True
            await page_obj.locator("#searchForm\\:searchButton").click()
            await page_obj.wait_for_timeout(15000)

            while total_yielded < limit and page_num < max_pages:
                xml_text = None
                if captured_xml:
                    try:
                        xml_text = await captured_xml[-1].text()
                    except Exception:
                        pass
                    captured_xml.clear()

                if not xml_text:
                    self.logger.warning("No XML on page %d, stopping", page_num + 1)
                    break

                items = self._parse_xml(xml_text)
                for item_data in items:
                    if total_yielded >= limit:
                        break
                    uid = item_data.get("url") or item_data.get("title", "")
                    if uid in seen:
                        continue
                    seen.add(uid)

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
                            "extras": {k: v for k, v in item_data.items()
                                       if k not in ("url", "title", "content")},
                        },
                    )

                    if download and item_data.get("id"):
                        download_tasks.append(
                            asyncio.create_task(
                                self._download_via_page(page_obj, item_data, download_dir)
                            )
                        )

                if total_yielded >= limit:
                    break

                page_num += 1
                self.logger.info("Clicking Next (page %d, %d items)", page_num + 1, total_yielded)

                next_btn = page_obj.locator("#resultForm\\:j_idt217")
                if await next_btn.count() == 0:
                    next_btn = page_obj.locator("#resultForm\\:j_idt218").locator("..").locator("button").nth(2)
                await next_btn.click(timeout=5000)
                await page_obj.wait_for_timeout(10000)

        finally:
            self.logger.info("Finished: %d items from %d pages", total_yielded, page_num)
            if download_tasks:
                await asyncio.wait(download_tasks, timeout=30)
            await page_obj.close()

    def _errback_close_page(self, failure):
        page = failure.request.meta.get("playwright_page")
        if page:
            from twisted.internet import defer
            defer.ensureDeferred(page.close())

    async def _download_via_page(self, page, item_data, download_dir):
        """Download providencia HTML via Playwright page (uses session cookies)."""
        prov_id = item_data.get("id")
        prov = item_data.get("providencia", prov_id)
        if not prov_id:
            return

        dl_dir = Path(download_dir)
        dl_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{prov}.html" if prov else f"{prov_id}.html"
        filepath = dl_dir / filename

        if filepath.exists():
            return

        url = f"https://consultajurisprudencial.ramajudicial.gov.co/WebRelatoria/FileReferenceServlet?corp=csj&ext=html&file={prov_id}"

        try:
            content = await page.evaluate("""
                async (download_url) => {
                    const resp = await fetch(download_url);
                    if (!resp.ok) throw new Error('HTTP ' + resp.status);
                    return await resp.text();
                }
            """, url)
            filepath.write_text(content, encoding="utf-8")
            self.logger.info("Downloaded %s", filename)
        except Exception as e:
            self.logger.warning("Download failed for %s: %s", filename, e)

    @staticmethod
    def _parse_xml(xml_text):
        cdatas = re.findall(r"<!\[CDATA\[(.*?)\]\]>", xml_text, re.DOTALL)
        items = []

        for cdata in cdatas:
            trs = re.findall(r"<tr[^>]*role=\"row\"[^>]*>(.*?)</tr>", cdata, re.DOTALL)
            for tr_html in trs:
                text = re.sub(r"<[^>]+>", " ", tr_html)
                text = re.sub(r"&nbsp;", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
                text = unescape(text)

                if not text or len(text) < 30 or "ui-button" in text:
                    continue

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
