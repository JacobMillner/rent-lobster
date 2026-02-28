from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import Callable
from urllib.parse import urlparse

from crawlee import ConcurrencySettings
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.proxy_configuration import ProxyConfiguration

from config import Settings
from db import upsert_listing
from models import Listing
from spiders._stealth import inject_stealth, stealth_context_options

log = logging.getLogger(__name__)

_PRICE_RE = re.compile(r"\$([\d,]+)")
_BED_RE = re.compile(r"(\d+)\s*(?:bed|br)\b", re.IGNORECASE)
_BATH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:bath|ba)\b", re.IGNORECASE)

# StreetEasy listing URLs: /rental/1234, /building/..., /listing/...
_SE_LISTING_RE = re.compile(r"streeteasy\.com/(rental|building|listing)/\d+", re.IGNORECASE)


def _is_listing_url(url: str) -> bool:
    return bool(_SE_LISTING_RE.search(url))


def _is_search_page(url: str) -> bool:
    """True for search/browse URLs (not individual listing pages)."""
    path = urlparse(url).path
    return path.startswith("/for-rent/") or path.startswith("/for-sale/")


def build_streeteasy_crawler(
    settings: Settings,
    *,
    max_pages: int | None = None,
    on_page: Callable[[], None] | None = None,
    on_listing: Callable[[], None] | None = None,
    configuration: object | None = None,
) -> PlaywrightCrawler:
    kwargs: dict = dict(
        headless=settings.headless,
        browser_type="firefox",
        browser_new_context_options=stealth_context_options(),
        max_requests_per_crawl=max_pages or settings.max_requests,
        use_session_pool=True,
        max_session_rotations=10,
        ignore_http_error_status_codes=[403, 429],
        concurrency_settings=ConcurrencySettings(min_concurrency=1, max_concurrency=1, desired_concurrency=1),
    )
    if settings.proxy_urls:
        kwargs["proxy_configuration"] = ProxyConfiguration(proxy_urls=list(settings.proxy_urls))
        log.info("[streeteasy] Using %d proxy URLs", len(settings.proxy_urls))
    if configuration is not None:
        kwargs["configuration"] = configuration

    log.info("[streeteasy] Building crawler with options: headless=%s, max_requests=%s",
             settings.headless, max_pages or settings.max_requests)

    crawler = PlaywrightCrawler(**kwargs)

    @crawler.pre_navigation_hook
    async def stealth_hook(context) -> None:
        log.info("[streeteasy] Pre-navigation hook: injecting stealth for %s", context.request.url)
        await inject_stealth(context.page)

    @crawler.router.default_handler
    async def handle(context: PlaywrightCrawlingContext) -> None:
        url = context.request.url
        log.info("[streeteasy] Handler called for %s", url)
        context.log.info(f"[streeteasy] Visiting {url}")
        if on_page:
            on_page()

        page = context.page

        delay = random.uniform(3.0, 8.0)
        await asyncio.sleep(delay)

        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass

        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass

        title = (await page.title()) or ""
        status = context.response.status if context.response else "unknown"
        log.info("[streeteasy] Page loaded: title=%r, status=%s", title, status)

        # Detect block pages — skip immediately instead of wasting time
        blocked = any(kw in title.lower() for kw in (
            "access denied", "blocked", "captcha", "just a moment", "denied",
        ))
        if blocked:
            log.warning("[streeteasy] Blocked (title=%r, status=%s) — skipping %s", title, status, url)
            return

        if _is_search_page(url) or not _is_listing_url(url):
            await _handle_search_page(page, context, settings, on_listing)
            return

        await _handle_detail_page(page, context, url, title, settings, on_listing)

    async def _handle_search_page(page, context, settings, on_listing):
        log.info("[streeteasy] Processing as search results page")

        saved_count = 0

        # ── Strategy 1: Parse JSON-LD @graph from the page ──
        # StreetEasy embeds structured listing data in JSON-LD script tags
        json_ld_listings = await page.evaluate("""() => {
            const results = [];
            const scripts = document.querySelectorAll('script[type="application/ld+json"]');
            for (const s of scripts) {
                try {
                    const d = JSON.parse(s.textContent);
                    // Could be a single object or have @graph array
                    if (d['@graph'] && Array.isArray(d['@graph'])) {
                        for (const item of d['@graph']) {
                            if (item['@type'] === 'ApartmentComplex' || item['@type'] === 'Apartment'
                                || item['@type'] === 'Residence' || item['@type'] === 'RealEstateListing') {
                                results.push(item);
                            }
                        }
                    } else if (d['@type'] === 'ApartmentComplex' || d['@type'] === 'Apartment'
                               || d['@type'] === 'Residence' || d['@type'] === 'RealEstateListing') {
                        results.push(d);
                    }
                } catch {}
            }
            return results;
        }""")

        if json_ld_listings:
            log.info("[streeteasy] Found %d listings in JSON-LD data", len(json_ld_listings))
            for item in json_ld_listings:
                if _save_json_ld_listing(item, settings, on_listing):
                    saved_count += 1

        # ── Strategy 2: Extract listing card data via DOM ──
        card_data = await page.evaluate("""() => {
            const cards = document.querySelectorAll(
                '[data-testid*="listing"], [class*="listingCard"], [class*="SearchCard"], article[class*="listing"]'
            );
            return Array.from(cards).map(card => {
                const link = card.querySelector('a[href]');
                const priceEl = card.querySelector('[class*="price"], [data-testid*="price"]');
                const addrEl = card.querySelector('[class*="address"], [data-testid*="address"]');
                const bedsEl = card.querySelector('[class*="bed"], [data-testid*="bed"]');
                const bathsEl = card.querySelector('[class*="bath"], [data-testid*="bath"]');
                const imgEl = card.querySelector('img[src]');
                return {
                    url: link ? link.href : null,
                    price: priceEl ? priceEl.textContent : null,
                    address: addrEl ? addrEl.textContent : null,
                    beds: bedsEl ? bedsEl.textContent : null,
                    baths: bathsEl ? bathsEl.textContent : null,
                    image: imgEl ? imgEl.src : null,
                };
            });
        }""")

        if card_data:
            log.info("[streeteasy] Found %d listing cards via DOM", len(card_data))
            for card in card_data:
                if _save_card_listing(card, settings, on_listing):
                    saved_count += 1

        # Pagination — try multiple selectors and also look for page=N links
        for sel in [
            'a[aria-label="Next"]',
            'a[aria-label="next"]',
            'a.next',
            '[data-testid="pagination-next"]',
            '[data-testid*="next"] a',
            'a[rel="next"]',
            'nav a[href*="page="]',
            '.pagination a:last-child',
        ]:
            try:
                next_links = await page.eval_on_selector_all(
                    sel, "els => els.map(e => e.href).filter(Boolean)",
                )
                if next_links:
                    log.info("[streeteasy] Pagination via %r: %s", sel, next_links[0])
                    await context.add_requests([next_links[0]])
                    break
            except Exception:
                continue

        log.info("[streeteasy] Search page done: %d listings saved directly from this page", saved_count)

    async def _handle_detail_page(page, context, url, title, settings, on_listing):
        log.info("[streeteasy] Processing as listing detail page")

        # Use a short timeout for all element queries on detail pages
        page.set_default_timeout(5_000)

        try:
            body_text = (await page.text_content("body")) or ""
        except Exception:
            body_text = ""

        price = None
        beds = None
        baths = None
        neighborhood = None
        address = None
        thumbnail = None

        # JSON-LD — fast since it uses page.evaluate (no element wait)
        try:
            json_ld = await page.evaluate("""() => {
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (const s of scripts) {
                    try {
                        const d = JSON.parse(s.textContent);
                        if (['Apartment', 'ApartmentComplex', 'RealEstateListing', 'Residence'].includes(d['@type']))
                            return d;
                    } catch {}
                }
                return null;
            }""")
        except Exception:
            json_ld = None

        if json_ld:
            log.info("[streeteasy] Found JSON-LD: type=%s", json_ld.get("@type"))
            if "offers" in json_ld and "price" in json_ld["offers"]:
                try:
                    price = int(str(json_ld["offers"]["price"]).replace(",", ""))
                except (ValueError, TypeError):
                    pass
            if "numberOfBedrooms" in json_ld:
                try:
                    beds = int(json_ld["numberOfBedrooms"])
                except (ValueError, TypeError):
                    pass
            if "numberOfBathroomsTotal" in json_ld:
                try:
                    baths = float(json_ld["numberOfBathroomsTotal"])
                except (ValueError, TypeError):
                    pass
            address = json_ld.get("name") or json_ld.get("address", {}).get("streetAddress")
            thumbnail = json_ld.get("image") or json_ld.get("photo")
            if isinstance(thumbnail, dict):
                thumbnail = thumbnail.get("image") or thumbnail.get("url")
            if isinstance(thumbnail, list):
                thumbnail = thumbnail[0] if thumbnail else None

        # Regex fallback on body text (no Playwright calls, instant)
        if price is None:
            m = _PRICE_RE.search(body_text)
            price = int(m.group(1).replace(",", "")) if m else None
        if beds is None:
            m_bed = _BED_RE.search(body_text)
            beds = int(m_bed.group(1)) if m_bed else None
        if baths is None:
            m_bath = _BATH_RE.search(body_text)
            baths = float(m_bath.group(1)) if m_bath else None

        # Element queries — each wrapped so a timeout on one doesn't block the rest
        if not neighborhood:
            try:
                neighborhood_el = await page.query_selector('a[href*="/neighborhood/"]')
                neighborhood = (await neighborhood_el.text_content()) if neighborhood_el else None
            except Exception:
                pass
        if not thumbnail:
            try:
                thumbnail = await page.get_attribute('meta[property="og:image"]', "content")
            except Exception:
                pass
        if not address:
            address = title.split("|")[0].strip() if title else None

        log.info("[streeteasy] Parsed: price=%s, beds=%s, baths=%s, addr=%r", price, beds, baths, address)

        listing = Listing(
            source="streeteasy",
            url=url,
            price=price,
            beds=beds,
            baths=baths,
            address=address,
            neighborhood=neighborhood.strip() if neighborhood else None,
            thumbnail_url=thumbnail,
        )

        if listing.matches(min_beds=settings.min_beds, min_baths=settings.min_baths, max_rent=settings.max_rent):
            upsert_listing(listing)
            if on_listing:
                on_listing()
            await context.push_data(listing.model_dump())
            log.info("[streeteasy] Saved listing: %s", listing.url)
        else:
            context.log.info(
                f"[streeteasy] Filtered out: {listing.url} "
                f"(${listing.price}, {listing.beds}br, {listing.baths}ba)"
            )

    return crawler


def _save_json_ld_listing(item: dict, settings: Settings, on_listing: Callable | None) -> bool:
    """Parse a JSON-LD ApartmentComplex/Apartment item and save it."""
    try:
        # Price from additionalProperty or offers
        price = None
        additional = item.get("additionalProperty", {})
        if isinstance(additional, dict) and additional.get("value"):
            m = _PRICE_RE.search(str(additional["value"]))
            if m:
                price = int(m.group(1).replace(",", ""))
        if price is None and "offers" in item:
            offers = item["offers"]
            if isinstance(offers, dict) and "price" in offers:
                try:
                    price = int(str(offers["price"]).replace(",", ""))
                except (ValueError, TypeError):
                    pass

        # Address
        addr_obj = item.get("address", {})
        address = None
        if isinstance(addr_obj, dict):
            address = addr_obj.get("streetAddress")
        neighborhood = None
        if isinstance(addr_obj, dict):
            neighborhood = addr_obj.get("addressLocality")

        # Image
        thumbnail = None
        photo = item.get("photo")
        if isinstance(photo, dict):
            thumbnail = photo.get("image") or photo.get("url")
        elif isinstance(photo, str):
            thumbnail = photo
        if not thumbnail:
            thumbnail = item.get("image")
            if isinstance(thumbnail, list):
                thumbnail = thumbnail[0] if thumbnail else None

        # URL
        listing_url = item.get("url") or ""
        if not listing_url:
            listing_url = f"https://streeteasy.com/building/{item.get('name', 'unknown')}"

        listing = Listing(
            source="streeteasy",
            url=listing_url or "https://streeteasy.com",
            price=price,
            beds=None,
            baths=None,
            address=address,
            neighborhood=neighborhood,
            thumbnail_url=thumbnail,
        )

        if listing.matches(min_beds=settings.min_beds, min_baths=settings.min_baths, max_rent=settings.max_rent):
            upsert_listing(listing)
            if on_listing:
                on_listing()
            log.info("[streeteasy] Saved JSON-LD listing: %s ($%s)", address, price)
            return True
    except Exception:
        log.debug("Failed to process JSON-LD listing", exc_info=True)
    return False


def _save_card_listing(card: dict, settings: Settings, on_listing: Callable | None) -> bool:
    """Parse a listing card extracted from DOM and save it."""
    try:
        url = card.get("url") or ""
        if not url:
            return False

        price = None
        price_text = card.get("price") or ""
        m = _PRICE_RE.search(price_text)
        if m:
            price = int(m.group(1).replace(",", ""))

        beds = None
        beds_text = card.get("beds") or ""
        m_bed = _BED_RE.search(beds_text)
        if m_bed:
            beds = int(m_bed.group(1))

        baths = None
        baths_text = card.get("baths") or ""
        m_bath = _BATH_RE.search(baths_text)
        if m_bath:
            baths = float(m_bath.group(1))

        listing = Listing(
            source="streeteasy",
            url=url,
            price=price,
            beds=beds,
            baths=baths,
            address=card.get("address"),
            thumbnail_url=card.get("image"),
        )

        if listing.matches(min_beds=settings.min_beds, min_baths=settings.min_baths, max_rent=settings.max_rent):
            upsert_listing(listing)
            if on_listing:
                on_listing()
            log.info("[streeteasy] Saved card listing: %s ($%s, %sbd)", url, price, beds)
            return True
    except Exception:
        log.debug("Failed to process card listing", exc_info=True)
    return False
