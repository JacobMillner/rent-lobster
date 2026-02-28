from __future__ import annotations

import re
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from models import Listing
from config import Settings

_PRICE_RE = re.compile(r"\$([\d,]+)")


def build_streeteasy_crawler(settings: Settings) -> PlaywrightCrawler:
    crawler = PlaywrightCrawler(
        headless=settings.headless,
        max_requests_per_crawl=settings.max_requests,
        respect_robots_txt_file=settings.respect_robots,
    )

    @crawler.router.default_handler
    async def handle(context: PlaywrightCrawlingContext) -> None:
        context.log.info(f"Visiting {context.request.url}")

        title = await context.page.title()
        body_text = (await context.page.text_content("body")) or ""
        m = _PRICE_RE.search(body_text)
        price = int(m.group(1).replace(",", "")) if m else None

        listing = Listing(
            source="streeteasy", url=context.request.url, price=price, address=title
        )
        await context.push_data(listing.model_dump())

    return crawler
