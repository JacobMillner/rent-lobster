from __future__ import annotations

import re
from urllib.parse import urlparse

from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext

from config import Settings
from models import Listing

_PRICE_RE = re.compile(r"\$([\d,]+)")
_BED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*br\b", re.IGNORECASE)
_BATH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*ba\b", re.IGNORECASE)

def _same_site(url: str, seed_host: str) -> bool:
    try:
        host = urlparse(url).netloc
    except Exception:
        return False
    return host == seed_host

def _parse_int_price(text: str) -> int | None:
    m = _PRICE_RE.search(text)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))

def _parse_beds_baths(text: str) -> tuple[int | None, float | None]:
    beds = None
    baths = None

    m_bed = _BED_RE.search(text)
    if m_bed:
        try:
            beds_f = float(m_bed.group(1))
            beds = int(beds_f)
        except Exception:
            beds = None

    m_bath = _BATH_RE.search(text)
    if m_bath:
        try:
            baths = float(m_bath.group(1))
        except Exception:
            baths = None

    return beds, baths

def build_craigslist_crawler(settings: Settings) -> PlaywrightCrawler:
    crawler = PlaywrightCrawler(
        headless=settings.headless,
        max_requests_per_crawl=settings.max_requests,
        respect_robots_txt_file=settings.respect_robots,
    )

    @crawler.router.default_handler
    async def handle(context: PlaywrightCrawlingContext) -> None:
        url = context.request.url
        context.log.info(f"[craigslist] Visiting {url}")

        # Determine seed host (to avoid cross-domain enqueues)
        # If this request has a "user_data" seed_host, use it; otherwise derive from current.
        seed_host = context.request.user_data.get("seed_host") or urlparse(url).netloc

        # Heuristic: search/list page vs listing page
        # Search pages often have /search/ or query params, listing pages look like .../apa/d/<slug>/<id>.html
        is_listing = url.endswith(".html")

        if not is_listing:
            # --- SEARCH RESULTS PAGE ---
            # Collect listing links
            links = await context.page.eval_on_selector_all(
                "a.result-title.hdrlnk",
                "els => els.map(e => e.href).filter(Boolean)"
            )

            # Fallback selector (in case CL changes)
            if not links:
                links = await context.page.eval_on_selector_all(
                    "li.cl-search-result a",
                    "els => els.map(e => e.href).filter(Boolean)"
                )

            # Enqueue listing pages only, same host
            to_enqueue = [u for u in links if u.endswith(".html") and _same_site(u, seed_host)]
            if to_enqueue:
                await context.enqueue_links(
                    urls=to_enqueue,
                    user_data={"seed_host": seed_host},
                )

            # Pagination (next page)
            next_links = await context.page.eval_on_selector_all(
                "a.button.next",
                "els => els.map(e => e.href).filter(Boolean)"
            )
            next_url = next_links[0] if next_links else None
            if next_url and _same_site(next_url, seed_host):
                await context.enqueue_links(urls=[next_url], user_data={"seed_host": seed_host})

            return

        # --- LISTING PAGE ---
        title = (await context.page.text_content("span#titletextonly")) or (await context.page.title()) or ""
        price_text = (await context.page.text_content("span.price")) or ""
        price = _parse_int_price(price_text) or _parse_int_price(title)

        # Housing string (often contains "3br - 1ba - 1200ft2")
        housing = (await context.page.text_content("span.housing")) or ""
        beds, baths = _parse_beds_baths(housing)

        # Neighborhood is sometimes in parentheses in the small header
        # e.g. "<small>(Bushwick)</small>"
        neighborhood = (await context.page.text_content("small")) or None
        if neighborhood:
            neighborhood = neighborhood.strip("() \n\t") or None

        listing = Listing(
            source="craigslist",
            url=url,
            price=price,
            beds=beds,
            baths=baths,
            neighborhood=neighborhood,
            address=title.strip() or None,
        )

        # Apply your filters if you want to only store matches:
        if listing.matches(min_beds=settings.min_beds, min_baths=settings.min_baths, max_rent=settings.max_rent):
            await context.push_data(listing.model_dump())
        else:
            context.log.info(f"[craigslist] Filtered out: {listing.url} (${listing.price}, {listing.beds}br, {listing.baths}ba)")

    return crawler