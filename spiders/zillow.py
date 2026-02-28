from __future__ import annotations

import re
from typing import Iterable

from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext

from apt_scout.models import Listing
from apt_scout.config import Settings

_PRICE_RE = re.compile(r"\$([\d,]+)")

def build_zillow_crawler(settings: Settings) -> PlaywrightCrawler:
    crawler = PlaywrightCrawler(
        headless=settings.headless,
        max_requests_per_crawl=settings.max_requests,
        respect_robots_txt_file=settings.respect_robots,
    )

    @crawler.router.default_handler
    async def handle(context: PlaywrightCrawlingContext) -> None:
        # NOTE: Zillow is heavily JS + anti-bot. This is just a structure.
        context.log.info(f"Visiting {context.request.url}")

        # You’ll need to inspect DOM for whatever pages you’re *allowed* to crawl.
        title = await context.page.title()
        body_text = (await context.page.text_content("body")) or ""

        # Placeholder extraction: look for a $price in text
        m = _PRICE_RE.search(body_text)
        price = int(m.group(1).replace(",", "")) if m else None

        listing = Listing(source="zillow", url=context.request.url, price=price, address=title)
        await context.push_data(listing.model_dump())

    return crawler