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
from models import Listing, scan_amenities, _SQFT_RE
from spiders._stealth import inject_stealth, stealth_context_options

log = logging.getLogger(__name__)

_PRICE_RE = re.compile(r"\$([\d,]+)")
_BED_RE = re.compile(r"(\d+)\s*(?:bed|bd|br)\b", re.IGNORECASE)
_BATH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:bath|ba)\b", re.IGNORECASE)

_ZILLOW_LISTING_RE = re.compile(r"zillow\.com/(homedetails/|b/)", re.IGNORECASE)


def _is_listing_url(url: str) -> bool:
    return bool(_ZILLOW_LISTING_RE.search(url))


def _is_search_page(url: str) -> bool:
    path = urlparse(url).path
    return bool(re.search(r"/(apartments|for-rent|rentals|homes)", path, re.IGNORECASE))


def build_zillow_crawler(
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
        log.info("[zillow] Using %d proxy URLs", len(settings.proxy_urls))
    if configuration is not None:
        kwargs["configuration"] = configuration

    log.info("[zillow] Building crawler: headless=%s, max_requests=%s",
             settings.headless, max_pages or settings.max_requests)

    crawler = PlaywrightCrawler(**kwargs)

    @crawler.pre_navigation_hook
    async def stealth_hook(context) -> None:
        log.info("[zillow] Pre-navigation hook: injecting stealth for %s", context.request.url)
        await inject_stealth(context.page)

    @crawler.router.default_handler
    async def handle(context: PlaywrightCrawlingContext) -> None:
        url = context.request.url
        log.info("[zillow] Handler called for %s", url)
        context.log.info(f"[zillow] Visiting {url}")
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
            await page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass

        title = (await page.title()) or ""
        status = context.response.status if context.response else "unknown"
        log.info("[zillow] Page loaded: title=%r, status=%s", title, status)

        # Detect block/challenge pages — skip immediately
        blocked = any(kw in title.lower() for kw in (
            "access denied", "blocked", "captcha", "just a moment", "robot", "denied",
        ))
        if blocked:
            log.warning("[zillow] Blocked (title=%r, status=%s) — skipping %s", title, status, url)
            return

        if _is_search_page(url) or not _is_listing_url(url):
            await _handle_search_page(page, context, settings, on_listing)
            return

        await _handle_detail_page(page, context, url, title, settings, on_listing)

    async def _handle_search_page(page, context, settings, on_listing):
        log.info("[zillow] Processing as search results page")

        body_text = (await page.text_content("body")) or ""
        body_preview = body_text[:500].replace("\n", " ").strip()
        log.info("[zillow] Body preview (%d chars): %s", len(body_text), body_preview)

        saved_count = 0

        # ── Strategy 1: JSON-LD @graph from the page ──
        json_ld_listings = await page.evaluate("""() => {
            const results = [];
            const scripts = document.querySelectorAll('script[type="application/ld+json"]');
            for (const s of scripts) {
                try {
                    const d = JSON.parse(s.textContent);
                    if (d['@graph'] && Array.isArray(d['@graph'])) {
                        for (const item of d['@graph']) {
                            if (['ApartmentComplex', 'Apartment', 'Residence',
                                 'SingleFamilyResidence', 'RealEstateListing',
                                 'Product'].includes(item['@type'])) {
                                results.push(item);
                            }
                        }
                    } else if (['ApartmentComplex', 'Apartment', 'Residence',
                                'SingleFamilyResidence', 'RealEstateListing',
                                'Product'].includes(d['@type'])) {
                        results.push(d);
                    }
                } catch {}
            }
            return results;
        }""")

        if json_ld_listings:
            log.info("[zillow] Found %d listings in JSON-LD data", len(json_ld_listings))
            for item in json_ld_listings:
                if _save_json_ld_listing(item, settings, on_listing):
                    saved_count += 1

        # ── Strategy 2: Preloaded data (__NEXT_DATA__, inline scripts) ──
        preloaded = await page.evaluate("""() => {
            const nextData = document.getElementById('__NEXT_DATA__');
            if (nextData) try { return JSON.parse(nextData.textContent); } catch {}
            for (const key of ['__INITIAL_STATE__', '__SEARCH_RESULTS__']) {
                if (window[key]) return window[key];
            }
            const scripts = document.querySelectorAll('script');
            for (const s of scripts) {
                const txt = s.textContent || '';
                if (txt.includes('listResults') || txt.includes('searchResults')) {
                    try {
                        const match = txt.match(/({.*listResults.*})/s);
                        if (match) return JSON.parse(match[1]);
                    } catch {}
                }
            }
            return null;
        }""")

        if preloaded:
            log.info("[zillow] Found preloaded data on page")
            saved_count += _extract_from_preloaded(preloaded, settings, on_listing)
        else:
            log.info("[zillow] No preloaded data found")

        # ── Strategy 3: DOM card scraping ──
        card_data = await page.evaluate("""() => {
            const cards = document.querySelectorAll(
                '[data-test="property-card"], article[data-test], [class*="ListItem"], [class*="property-card"], [class*="StyledPropertyCard"]'
            );
            return Array.from(cards).map(card => {
                const link = card.querySelector('a[href]');
                const priceEl = card.querySelector('[data-test="property-card-price"], [class*="price"]');
                const addrEl = card.querySelector('[data-test="property-card-addr"], address, [class*="address"]');
                const bedsEl = card.querySelector('[class*="bed"]');
                const bathsEl = card.querySelector('[class*="bath"]');
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
            log.info("[zillow] Found %d listing cards via DOM", len(card_data))
            for card in card_data:
                if _save_card_listing(card, settings, on_listing):
                    saved_count += 1

        if not saved_count:
            log.warning("[zillow] No listings extracted from search page")

        # Pagination
        for sel in [
            'a[aria-label="Next page"]',
            'a[title="Next page"]',
            'a[rel="next"]',
            'a.zsg-pagination-next',
            'li.PaginationJumpItem a[href]:last-child',
            'nav a[href*="currentPage"]',
        ]:
            try:
                next_el = await page.query_selector(sel)
                if next_el:
                    href = await next_el.get_attribute("href")
                    if href:
                        if not href.startswith("http"):
                            href = f"https://www.zillow.com{href}"
                        log.info("[zillow] Pagination via %r: %s", sel, href)
                        await context.add_requests([href])
                        break
            except Exception:
                continue

        log.info("[zillow] Search page done: %d listings saved directly from this page", saved_count)

    async def _handle_detail_page(page, context, url, title, settings, on_listing):
        log.info("[zillow] Processing as listing detail page")

        page.set_default_timeout(5_000)

        try:
            body_text = (await page.text_content("body")) or ""
        except Exception:
            body_text = ""

        price = None
        beds = None
        baths = None
        sqft = None
        address = None
        thumbnail = None
        description = None

        try:
            json_ld = await page.evaluate("""() => {
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (const s of scripts) {
                    try {
                        const d = JSON.parse(s.textContent);
                        if (['Apartment', 'ApartmentComplex', 'SingleFamilyResidence',
                             'Residence', 'RealEstateListing', 'Product'].includes(d['@type']))
                            return d;
                    } catch {}
                }
                return null;
            }""")
        except Exception:
            json_ld = None

        if json_ld:
            log.info("[zillow] Found JSON-LD: type=%s", json_ld.get("@type"))
            if "offers" in json_ld:
                try:
                    price = int(str(json_ld["offers"].get("price", "")).replace(",", ""))
                except (ValueError, TypeError):
                    pass
            address = json_ld.get("name") or json_ld.get("address", {}).get("streetAddress")
            thumbnail = json_ld.get("image")
            if isinstance(thumbnail, dict):
                thumbnail = thumbnail.get("image") or thumbnail.get("url")
            if isinstance(thumbnail, list):
                thumbnail = thumbnail[0] if thumbnail else None
            floor_size = json_ld.get("floorSize")
            if isinstance(floor_size, dict):
                try:
                    sqft = int(str(floor_size.get("value", "")).replace(",", ""))
                except (ValueError, TypeError):
                    pass
            elif isinstance(floor_size, (int, float)):
                sqft = int(floor_size)

        if price is None:
            m = _PRICE_RE.search(body_text)
            price = int(m.group(1).replace(",", "")) if m else None
        if beds is None:
            m_bed = _BED_RE.search(body_text)
            beds = int(m_bed.group(1)) if m_bed else None
        if baths is None:
            m_bath = _BATH_RE.search(body_text)
            baths = float(m_bath.group(1)) if m_bath else None
        if sqft is None:
            m_sqft = _SQFT_RE.search(body_text)
            if m_sqft:
                try:
                    sqft = int(m_sqft.group(1).replace(",", ""))
                except ValueError:
                    pass
        if not thumbnail:
            try:
                thumbnail = await page.get_attribute('meta[property="og:image"]', "content")
            except Exception:
                pass
        if not address:
            address = title.split("|")[0].strip() if title else None

        # Description
        for desc_sel in ['.Text-c11n', '[data-testid="description"]', '[class*="description"]',
                         '.ds-overview-section', '.listing-description']:
            try:
                desc_el = await page.query_selector(desc_sel)
                if desc_el:
                    description = (await desc_el.text_content()) or None
                    if description:
                        description = description.strip()
                        break
            except Exception:
                continue

        # Amenities from body text
        amenities = scan_amenities(body_text) if body_text else {}

        # Facts and features sections
        try:
            fact_texts = await page.eval_on_selector_all(
                '[class*="fact"] li, [data-testid*="fact"] li, .ds-home-fact-list li, '
                '[class*="feature"] li, [class*="amenity"] li',
                "els => els.map(e => e.textContent).filter(Boolean)",
            )
            if fact_texts:
                combined = " ".join(fact_texts)
                structured = scan_amenities(combined)
                for k, v in structured.items():
                    if v is not None and k not in amenities:
                        amenities[k] = v
        except Exception:
            pass

        # Contact / property manager
        contact_name = None
        for contact_sel in ['[class*="listing-agent"]', '[class*="propertyManager"]',
                            '[data-testid*="contact"]', '[class*="contact"]']:
            try:
                contact_el = await page.query_selector(contact_sel)
                if contact_el:
                    ct = (await contact_el.text_content()) or ""
                    if ct:
                        contact_name = ct.strip().split("\n")[0].strip()
                        break
            except Exception:
                continue

        log.info("[zillow] Parsed: price=%s, beds=%s, baths=%s, addr=%r, sqft=%s",
                 price, beds, baths, address, sqft)

        listing = Listing(
            source="zillow",
            url=url,
            price=price,
            beds=beds,
            baths=baths,
            address=address,
            thumbnail_url=thumbnail,
            sqft=sqft,
            description=description,
            contact_name=contact_name,
            contact_phone=amenities.get("contact_phone"),
            contact_email=amenities.get("contact_email"),
            subway_minutes=amenities.get("subway_minutes"),
            nearest_subway=amenities.get("nearest_subway"),
            has_dishwasher=amenities.get("has_dishwasher"),
            has_balcony=amenities.get("has_balcony"),
            laundry=amenities.get("laundry"),
            has_doorman=amenities.get("has_doorman"),
            has_elevator=amenities.get("has_elevator"),
            has_gym=amenities.get("has_gym"),
            pets_allowed=amenities.get("pets_allowed"),
            no_fee=amenities.get("no_fee"),
            available_date=amenities.get("available_date"),
            floor=amenities.get("floor"),
        )

        if listing.matches(min_beds=settings.min_beds, min_baths=settings.min_baths, max_rent=settings.max_rent):
            upsert_listing(listing)
            if on_listing:
                on_listing()
            await context.push_data(listing.model_dump())
            log.info("[zillow] Saved listing: %s", listing.url)
        else:
            context.log.info(
                f"[zillow] Filtered out: {listing.url} "
                f"(${listing.price}, {listing.beds}br, {listing.baths}ba)"
            )

    return crawler


def _save_json_ld_listing(item: dict, settings: Settings, on_listing: Callable | None) -> bool:
    """Parse a JSON-LD listing item and save it."""
    try:
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

        addr_obj = item.get("address", {})
        address = addr_obj.get("streetAddress") if isinstance(addr_obj, dict) else None
        neighborhood = addr_obj.get("addressLocality") if isinstance(addr_obj, dict) else None

        thumbnail = None
        photo = item.get("photo")
        if isinstance(photo, dict):
            thumbnail = photo.get("image") or photo.get("url")
        elif isinstance(photo, str):
            thumbnail = photo
        if not thumbnail:
            img = item.get("image")
            if isinstance(img, list):
                thumbnail = img[0] if img else None
            elif isinstance(img, str):
                thumbnail = img

        listing_url = item.get("url") or "https://www.zillow.com"

        listing = Listing(
            source="zillow",
            url=listing_url,
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
            log.info("[zillow] Saved JSON-LD listing: %s ($%s)", address, price)
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
            source="zillow",
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
            log.info("[zillow] Saved card listing: %s ($%s, %sbd)", url, price, beds)
            return True
    except Exception:
        log.debug("Failed to process card listing", exc_info=True)
    return False


def _extract_from_preloaded(data: dict, settings: Settings, on_listing: Callable | None) -> int:
    """Extract listings from __NEXT_DATA__ or window state. Returns count saved."""
    saved = 0
    try:
        props = data
        if "props" in data:
            props = data["props"].get("pageProps", data.get("props", {}))

        results: list[dict] = []

        def _walk(obj: dict, depth: int = 0) -> None:
            if depth > 8 or not isinstance(obj, dict):
                return
            for key in ("listResults", "searchResults", "mapResults", "cat1", "results"):
                val = obj.get(key)
                if isinstance(val, list):
                    results.extend(val)
                elif isinstance(val, dict):
                    for sub in ("listResults", "searchResults", "mapResults"):
                        if sub in val and isinstance(val[sub], list):
                            results.extend(val[sub])
            for v in obj.values():
                if isinstance(v, dict):
                    _walk(v, depth + 1)

        _walk(props)

        if results:
            log.info("[zillow] Found %d listings in preloaded data", len(results))
            for item in results:
                if isinstance(item, dict):
                    if _process_preloaded_item(item, settings, on_listing):
                        saved += 1
    except Exception:
        log.debug("Failed to extract from preloaded data", exc_info=True)
    return saved


def _process_preloaded_item(item: dict, settings: Settings, on_listing: Callable | None) -> bool:
    """Process a single Zillow listing item from preloaded data."""
    try:
        price = (
            item.get("price")
            or item.get("unformattedPrice")
            or item.get("hdpData", {}).get("homeInfo", {}).get("price")
        )
        if isinstance(price, str):
            price = int(re.sub(r"[^\d]", "", price) or "0") or None

        detail_url = item.get("detailUrl") or item.get("url") or item.get("hdpUrl") or ""
        if detail_url and not detail_url.startswith("http"):
            detail_url = f"https://www.zillow.com{detail_url}"

        beds = item.get("beds") or item.get("bedrooms")
        baths = item.get("baths") or item.get("bathrooms")
        addr = item.get("address") or item.get("streetAddress")
        if isinstance(addr, dict):
            addr = addr.get("streetAddress") or str(addr)

        img = item.get("imgSrc") or item.get("image") or item.get("thumbnailUrl")

        listing = Listing(
            source="zillow",
            url=detail_url or "https://www.zillow.com",
            price=int(price) if price else None,
            beds=int(beds) if beds else None,
            baths=float(baths) if baths else None,
            address=str(addr) if addr else None,
            thumbnail_url=img,
        )

        if listing.matches(min_beds=settings.min_beds, min_baths=settings.min_baths, max_rent=settings.max_rent):
            upsert_listing(listing)
            if on_listing:
                on_listing()
            log.info("[zillow] Saved preloaded listing: %s ($%s, %sbd)", addr, listing.price, listing.beds)
            return True
    except Exception:
        log.debug("Failed to process preloaded item", exc_info=True)
    return False
