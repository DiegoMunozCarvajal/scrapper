import asyncio
import argparse
import json
from pathlib import Path

from loguru import logger

from .scrapers.amazon import AmazonScraper
from .scrapers.hotmart import HotmartScraper
from .scrapers.instagram import InstagramScraper
from .scrapers.mercadolibre import MercadoLibreScraper
from .scrapers.quora import QuoraScraper
from .scrapers.reddit import RedditScraper

SCRAPERS = {
    "reddit": RedditScraper,
    "quora": QuoraScraper,
    "hotmart": HotmartScraper,
    "mercadolibre": MercadoLibreScraper,
    "amazon": AmazonScraper,
    "instagram": InstagramScraper,
}


async def main():
    parser = argparse.ArgumentParser(description="Multi-site web scraper")
    parser.add_argument("site", choices=list(SCRAPERS.keys()), help="Target site to scrape")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--limit", "-n", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--headless", action="store_true", default=True, help="Run in headless mode")
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    parser.add_argument("--proxy", help="Proxy URL (e.g., http://user:pass@host:port)")
    args = parser.parse_args()

    headless = not args.no_headless
    scraper_cls = SCRAPERS[args.site]
    scraper = scraper_cls(headless=headless, proxy=args.proxy)

    logger.info(f"Scraping {args.site} for '{args.query}'...")
    result = await scraper.run(args.query, limit=args.limit)

    items = [vars(p) for p in result.posts] if result.posts else [vars(p) for p in result.products]
    output = {
        "source": result.source,
        "query": result.query,
        "count": len(items),
        "results": items,
        "scraped_at": result.scraped_at.isoformat(),
    }

    if args.output:
        Path(args.output).write_text(json.dumps(output, indent=2))
        logger.info(f"Saved {len(items)} results to {args.output}")
    else:
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
