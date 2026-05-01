from playwright.async_api import Page

from ..models import Post, ScrapeResult
from .base import TIMEOUT, BaseScraper


class RedditScraper(BaseScraper):
    site = "reddit"

    async def search(self, query: str, limit: int = 10) -> ScrapeResult:
        return await self.run(query, limit)

    async def _do_search(self, page: Page, query: str, limit: int) -> ScrapeResult:
        url = f"https://old.reddit.com/search?q={query}&sort=relevance&type=link"
        await page.goto(url, timeout=TIMEOUT)
        await page.wait_for_load_state("networkidle")

        posts: list[Post] = []
        while len(posts) < limit:
            articles = await page.query_selector_all("article")
            for el in articles:
                if len(posts) >= limit:
                    break
                try:
                    title_el = await el.query_selector('a[slot="title"]')
                    title = await title_el.inner_text() if title_el else ""
                    href = await title_el.get_attribute("href") if title_el else ""
                    url = f"https://old.reddit.com{href}" if href else ""

                    author_el = await el.query_selector('a[href*="/user/"]')
                    author = await author_el.inner_text() if author_el else ""

                    score_el = await el.query_selector('[data-testid="post-score"]')
                    score_text = await score_el.inner_text() if score_el else "0"
                    score = int(score_text) if score_text.isdigit() else 0

                    posts.append(Post(title=title, url=url, author=author, score=score))
                except Exception:
                    continue

            if len(posts) >= limit:
                break

            next_btn = await page.query_selector('a[rel="nofollow next"]')
            if next_btn:
                await next_btn.click()
                await page.wait_for_load_state("networkidle")
            else:
                break

        return ScrapeResult(source=self.site, query=query, posts=posts[:limit])
