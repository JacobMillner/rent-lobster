from __future__ import annotations

import re
from urllib.parse import urlparse

from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext

from config import Settings
from db import upsert_listing
from models import Listing

_PRICE_RE = re.compile(r"\$([\d,]+)")
_BED_RE = re.compile(r"(\d+)\s*(?:bed|br)\b", re.IGNORECASE)
_BATH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:bath|ba)\b", re.IGNORECASE)

_LISTING_PATH_RE = re.compile(r"/rental/\d+")


def _is_listing_page(url: str) -> bool:
    path = urlparse(url).path
    return bool(_LISTING_PATH_RE.search(path))


def build_streeteasy_crawler(settings: Settings) -> PlaywrightCrawler:
    crawler = PlaywrightCrawler(
        headless=settings.headless,
        max_requests_per_crawl=settings.max_requests,
        respect_robots_txt_file=settings.respect_robots,
    )

    @crawler.router.default_handler
    async def handle(context: PlaywrightCrawlingContext) -> None:
        url = context.request.url
        context.log.info(f"[streeteasy] Visiting {url}")

        if not _is_listing_page(url):
            listing_links = await context.page.eval_on_selector_all(
                'a[href*="/rental/"]',
                "els => els.map(e => e.href).filter(Boolean)",
            )
            unique = list(dict.fromkeys(link for link in listing_links if _is_listing_page(link)))
            if unique:
                context.log.info(f"[streeteasy] Found {len(unique)} listing links")
                await context.enqueue_links(urls=unique)

            next_links = await context.page.eval_on_selector_all(
                'a[aria-label="Next"]',
                "els => els.map(e => e.href).filter(Boolean)",
            )
            if next_links:
                await context.enqueue_links(urls=[next_links[0]])
            return

        title = await context.page.title()
        body_text = (await context.page.text_content("body")) or ""

        m = _PRICE_RE.search(body_text)
        price = int(m.group(1).replace(",", "")) if m else None

        m_bed = _BED_RE.search(body_text)
        beds = int(m_bed.group(1)) if m_bed else None

        m_bath = _BATH_RE.search(body_text)
        baths = float(m_bath.group(1)) if m_bath else None

        neighborhood_el = await context.page.query_selector('a[href*="/neighborhood/"]')
        neighborhood = (await neighborhood_el.text_content()) if neighborhood_el else None

        listing = Listing(
            source="streeteasy",
            url=url,
            price=price,
            beds=beds,
            baths=baths,
            address=title.split("|")[0].strip() if title else None,
            neighborhood=neighborhood.strip() if neighborhood else None,
        )

        if listing.matches(min_beds=settings.min_beds, min_baths=settings.min_baths, max_rent=settings.max_rent):
            upsert_listing(listing)
            await context.push_data(listing.model_dump())
        else:
            context.log.info(
                f"[streeteasy] Filtered out: {listing.url} "
                f"(${listing.price}, {listing.beds}br, {listing.baths}ba)"
            )

    return crawler
