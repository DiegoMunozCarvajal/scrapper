from playwright.async_api import Page

from ..models import Post, ScrapeResult
from .base import TIMEOUT, BaseScraper


class InstagramScraper(BaseScraper):
    site = "instagram"

    def __init__(self, headless: bool = True, proxy: str | None = None, username: str = "", password: str = ""):
        super().__init__(headless, proxy)
        self.username = username
        self.password = password

    async def search(self, query: str, limit: int = 10) -> ScrapeResult:
        return await self.run(query, limit)

    async def _do_search(self, page: Page, query: str, limit: int) -> ScrapeResult:
        if self.username and self.password:
            await page.goto("https://www.instagram.com/accounts/login/", timeout=TIMEOUT)
            await page.wait_for_load_state("networkidle")
            try:
                await page.fill('input[name="username"]', self.username)
                await page.fill('input[name="password"]', self.password)
                await page.click('button[type="submit"]')
                await page.wait_for_timeout(5000)
            except Exception:
                pass

        hashtag = query.lstrip("#")
        await page.goto(f"https://www.instagram.com/explore/tags/{hashtag}/", timeout=TIMEOUT)
        await page.wait_for_timeout(3000)

        posts: list[Post] = []
        links = await page.query_selector_all("article a")
        for link in links:
            if len(posts) >= limit:
                break
            href = await link.get_attribute("href")
            if href and "/p/" in href:
                posts.append(Post(
                    title="",
                    url=f"https://www.instagram.com{href}",
                    author="",
                ))
        return ScrapeResult(source=self.site, query=query, posts=posts[:limit])
