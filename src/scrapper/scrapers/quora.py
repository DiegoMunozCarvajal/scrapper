from playwright.async_api import Page

from ..models import Post, ScrapeResult
from .base import TIMEOUT, BaseScraper


class QuoraScraper(BaseScraper):
    site = "quora"

    async def search(self, query: str, limit: int = 10) -> ScrapeResult:
        return await self.run(query, limit)

    async def _do_search(self, page: Page, query: str, limit: int) -> ScrapeResult:
        url = f"https://www.quora.com/search?q={query}&type=question"
        await page.goto(url, timeout=TIMEOUT)
        await page.wait_for_load_state("networkidle")

        posts: list[Post] = []
        cards = await page.query_selector_all('[class*="qu-bg--white"]')
        for card in cards:
            if len(posts) >= limit:
                break
            try:
                question_el = await card.query_selector("span")
                title = await question_el.inner_text() if question_el else ""

                link_el = await card.query_selector("a")
                href = await link_el.get_attribute("href") if link_el else ""
                url = f"https://www.quora.com{href}" if href else ""

                if title:
                    posts.append(Post(title=title, url=url, author="quora"))
            except Exception:
                continue

        return ScrapeResult(source=self.site, query=query, posts=posts[:limit])
