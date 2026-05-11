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
from spiders._common import is_blocked_title
from spiders._stealth import inject_stealth, stealth_context_options

log = logging.getLogger(__name__)

# These two regexes are still re-used by this file's own helpers below, so we keep
# them local. New shared parsing should use spiders._common.
_PRICE_RE = re.compile(r"\$([\d,]+)")
_BED_RE = re.compile(r"(\d+)\s*(?:bed|br)\b", re.IGNORECASE)
_BATH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:bath|ba)\b", re.IGNORECASE)

# StreetEasy listing URLs: /rental/1234, /building/..., /listing/...
_SE_LISTING_RE = re.compile(r"streeteasy\.com/(rental|sale|building|listing)/\d+", re.IGNORECASE)


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
    listing_type: str = "rental",
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

        if settings.spider_max_delay > 0:
            lo = max(0.0, settings.spider_min_delay)
            hi = max(lo, settings.spider_max_delay)
            await asyncio.sleep(random.uniform(lo, hi))

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
        if is_blocked_title(title):
            log.warning("[streeteasy] Blocked (title=%r, status=%s) — skipping %s", title, status, url)
            return

        if _is_search_page(url) or not _is_listing_url(url):
            await _handle_search_page(page, context, settings, on_listing, listing_type)
            return

        await _handle_detail_page(page, context, url, title, settings, on_listing, listing_type)

    async def _handle_search_page(page, context, settings, on_listing, listing_type):
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
                if _save_json_ld_listing(item, settings, on_listing, listing_type):
                    saved_count += 1

        # ── Strategy 2: Extract listing card data via DOM ──
        card_data = await page.evaluate("""() => {
            const cards = document.querySelectorAll(
                '[data-testid="listing-card"], [data-testid*="listing"], [class*="ListingCard"], [class*="listingCard"], [class*="SearchCard"], article[class*="listing"]'
            );
            return Array.from(cards).map(card => {
                const link = card.querySelector('a[href*="streeteasy.com"]') || card.querySelector('a[href^="/"]') || card.querySelector('a[href]');
                const priceEl = card.querySelector('[class*="price" i], [class*="Price"], [data-testid*="price"]');
                const addrEl = card.querySelector('[class*="address" i], [class*="Address"], [data-testid*="address"]');
                const titleEl = card.querySelector('[class*="title" i], [class*="Title"]');
                const bedsEl = card.querySelector('[class*="bed" i], [class*="Bed"], [data-testid*="bed"]');
                const bathsEl = card.querySelector('[class*="bath" i], [class*="Bath"], [data-testid*="bath"]');
                const imgEl = card.querySelector('img[src]');
                const neighEl = card.querySelector('[class*="neighborhood" i], [class*="area" i], [class*="location" i]');
                const detailsText = card.textContent || '';
                return {
                    url: link ? link.href : null,
                    price: priceEl ? priceEl.textContent : null,
                    address: addrEl ? addrEl.textContent : (titleEl ? titleEl.textContent : null),
                    beds: bedsEl ? bedsEl.textContent : null,
                    baths: bathsEl ? bathsEl.textContent : null,
                    image: imgEl ? imgEl.src : null,
                    neighborhood: neighEl ? neighEl.textContent : null,
                    details: detailsText,
                };
            });
        }""")

        if card_data:
            log.info("[streeteasy] Found %d listing cards via DOM", len(card_data))
            for card in card_data:
                if _save_card_listing(card, settings, on_listing, listing_type):
                    saved_count += 1

        # Pagination — try specific selectors, then fall back to generic page links
        found_next = False
        for sel in [
            'a[aria-label="Next"]',
            'a[aria-label="next"]',
            'a.next',
            '[data-testid="pagination-next"]',
            '[data-testid*="next"] a',
            'a[rel="next"]',
            '[class*="Pagination"] a[href*="page="]',
            '[class*="pagination"] a[href*="page="]',
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
                    found_next = True
                    break
            except Exception:
                continue

        if not found_next:
            try:
                page_links = await page.eval_on_selector_all(
                    '[class*="Pagination"] a[href], nav[class*="pagination" i] a[href]',
                    """els => {
                        const seen = new Set();
                        return els.map(e => e.href).filter(h => {
                            if (!h || seen.has(h)) return false;
                            seen.add(h);
                            return h.includes('page=');
                        });
                    }""",
                )
                if page_links:
                    current_url = page.url
                    cur_match = re.search(r'page=(\d+)', str(current_url))
                    cur_page = int(cur_match.group(1)) if cur_match else 1
                    for link in page_links:
                        link_match = re.search(r'page=(\d+)', link)
                        if link_match and int(link_match.group(1)) == cur_page + 1:
                            log.info("[streeteasy] Pagination fallback: %s", link)
                            await context.add_requests([link])
                            break
            except Exception:
                pass

        log.info("[streeteasy] Search page done: %d listings saved directly from this page", saved_count)

    async def _handle_detail_page(page, context, url, title, settings, on_listing, listing_type):
        log.info("[streeteasy] Processing as listing detail page")

        page.set_default_timeout(5_000)

        try:
            body_text = (await page.text_content("body")) or ""
        except Exception:
            body_text = ""

        price = None
        beds = None
        baths = None
        sqft = None
        neighborhood = None
        address = None
        thumbnail = None
        description = None
        contact_name = None
        contact_phone = None
        no_fee = None
        all_image_urls: list[str] = []

        # JSON-LD
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
            floor_size = json_ld.get("floorSize")
            if isinstance(floor_size, dict):
                try:
                    sqft = int(str(floor_size.get("value", "")).replace(",", ""))
                except (ValueError, TypeError):
                    pass
            elif isinstance(floor_size, (int, float)):
                sqft = int(floor_size)
            address = json_ld.get("name") or json_ld.get("address", {}).get("streetAddress")

            ld_image = json_ld.get("image") or json_ld.get("photo")
            if isinstance(ld_image, list):
                for img_item in ld_image:
                    if isinstance(img_item, str):
                        all_image_urls.append(img_item)
                    elif isinstance(img_item, dict):
                        u = img_item.get("url") or img_item.get("image")
                        if u:
                            all_image_urls.append(u)
                thumbnail = all_image_urls[0] if all_image_urls else None
            elif isinstance(ld_image, dict):
                thumbnail = ld_image.get("image") or ld_image.get("url")
                if thumbnail:
                    all_image_urls.append(thumbnail)
            elif isinstance(ld_image, str):
                thumbnail = ld_image
                all_image_urls.append(ld_image)

        # Regex fallback on body text
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

        # Element queries
        if not neighborhood:
            try:
                neighborhood_el = await page.query_selector('a[href*="/neighborhood/"]')
                neighborhood = (await neighborhood_el.text_content()) if neighborhood_el else None
            except Exception:
                pass
        if not thumbnail:
            try:
                thumbnail = await page.get_attribute('meta[property="og:image"]', "content")
                if thumbnail and thumbnail not in all_image_urls:
                    all_image_urls.insert(0, thumbnail)
            except Exception:
                pass
        if not address:
            address = title.split("|")[0].strip() if title else None

        try:
            gallery_imgs = await page.evaluate("""() => {
                const MIN_SIZE = 200;
                const imgs = document.querySelectorAll(
                    '[class*="carousel"] img, [class*="gallery"] img, ' +
                    '[class*="Carousel"] img, [class*="Gallery"] img, ' +
                    '[data-testid*="photo"] img'
                );
                const results = [];
                for (const img of imgs) {
                    let bestUrl = null;
                    if (img.srcset) {
                        const candidates = img.srcset.split(',').map(s => {
                            const parts = s.trim().split(/\s+/);
                            return { url: parts[0], w: parseInt(parts[1]) || 0 };
                        }).sort((a, b) => b.w - a.w);
                        if (candidates.length && candidates[0].url) bestUrl = candidates[0].url;
                    }
                    if (!bestUrl) {
                        bestUrl = img.dataset.src || img.dataset.original
                            || img.dataset.fullSrc || img.dataset.largeSrc;
                    }
                    if (!bestUrl) {
                        const a = img.closest('a');
                        if (a && /\\.(jpe?g|png|gif|webp)/i.test(a.href)) bestUrl = a.href;
                    }
                    if (!bestUrl && img.src) {
                        if (img.naturalWidth >= MIN_SIZE && img.naturalHeight >= MIN_SIZE) {
                            bestUrl = img.src;
                        }
                    }
                    if (bestUrl && !results.includes(bestUrl)) results.push(bestUrl);
                }
                return results;
            }""")
            for gi in (gallery_imgs or []):
                if gi not in all_image_urls:
                    all_image_urls.append(gi)
        except Exception:
            pass

        # Click thumbnail images to try loading full-size versions
        try:
            thumb_els = await page.query_selector_all(
                '[class*="carousel"] img, [class*="gallery"] img, '
                '[class*="Carousel"] img, [class*="Gallery"] img, '
                '[data-testid*="photo"] img'
            )
            for thumb in thumb_els:
                try:
                    box = await thumb.bounding_box()
                    if not box or box["width"] < 200 or box["height"] < 200:
                        await thumb.click(timeout=2000)
                        await page.wait_for_timeout(800)
                        expanded = await page.evaluate("""() => {
                            const big = document.querySelector(
                                '[class*="lightbox"] img[src], [class*="Lightbox"] img[src], ' +
                                '[class*="modal"] img[src], [class*="Modal"] img[src], ' +
                                '[class*="fullscreen"] img[src], [class*="viewer"] img[src], ' +
                                '[class*="Viewer"] img[src], [class*="enlarged"] img[src]'
                            );
                            return big ? big.src : null;
                        }""")
                        if expanded and expanded not in all_image_urls:
                            all_image_urls.append(expanded)
                except Exception:
                    continue
        except Exception:
            pass

        # Description
        for desc_sel in ['.Description-text', '[data-testid="description"]',
                         '[class*="description"]', '.details-section p']:
            try:
                desc_el = await page.query_selector(desc_sel)
                if desc_el:
                    description = (await desc_el.text_content()) or None
                    if description:
                        description = description.strip()
                        break
            except Exception:
                continue

        # Contact info
        for contact_sel in ['.ContactInfo', '[data-testid="agent"]', '[class*="agentInfo"]',
                            '[class*="contact"]', '.listing-agent']:
            try:
                contact_el = await page.query_selector(contact_sel)
                if contact_el:
                    contact_text = (await contact_el.text_content()) or ""
                    if contact_text:
                        contact_name = contact_text.strip().split("\n")[0].strip()
                        break
            except Exception:
                continue

        # No-fee badge
        try:
            no_fee_el = await page.query_selector('[class*="noFee"], [class*="no-fee"], [data-testid*="noFee"]')
            if no_fee_el:
                no_fee = True
        except Exception:
            pass

        # Amenities from body text
        amenities = scan_amenities(body_text) if body_text else {}

        # Structured amenity list
        try:
            amenity_texts = await page.eval_on_selector_all(
                '.AmenitiesList li, [data-testid*="amenity"], [class*="amenity"] li, .details-info li',
                "els => els.map(e => e.textContent).filter(Boolean)",
            )
            if amenity_texts:
                combined = " ".join(amenity_texts)
                structured = scan_amenities(combined)
                for k, v in structured.items():
                    if v is not None and k not in amenities:
                        amenities[k] = v
        except Exception:
            pass

        # Transit info
        try:
            transit_texts = await page.eval_on_selector_all(
                '.Transportation li, .NearbyTransit li, [data-testid*="transit"] li, [class*="transit"] li',
                "els => els.map(e => e.textContent).filter(Boolean)",
            )
            if transit_texts and not amenities.get("nearest_subway"):
                amenities["nearest_subway"] = transit_texts[0].strip()
                import re as _re
                for t in transit_texts:
                    m_min = _re.search(r"(\d+)\s*min", t)
                    if m_min:
                        amenities["subway_minutes"] = int(m_min.group(1))
                        break
        except Exception:
            pass

        if no_fee is None:
            no_fee = amenities.get("no_fee")

        # Date listed
        date_listed = None
        if json_ld and "datePosted" in json_ld:
            date_listed = str(json_ld["datePosted"])
        if not date_listed:
            try:
                date_texts = await page.eval_on_selector_all(
                    '[class*="Vitals"] li, [class*="detail"] li, .details-info li',
                    "els => els.map(e => e.textContent).filter(Boolean)",
                )
                import re as _re
                for t in (date_texts or []):
                    m = _re.search(r"(?:listed|posted)\s*(?:on\s*)?(\w+ \d{1,2},?\s*\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", t, _re.IGNORECASE)
                    if m:
                        date_listed = m.group(1).strip()
                        break
            except Exception:
                pass

        # Coordinates from JSON-LD geo
        latitude = None
        longitude = None
        if json_ld:
            geo = json_ld.get("geo")
            if isinstance(geo, dict):
                try:
                    latitude = float(geo.get("latitude", 0)) or None
                    longitude = float(geo.get("longitude", 0)) or None
                except (ValueError, TypeError):
                    pass

        log.info("[streeteasy] Parsed: price=%s, beds=%s, baths=%s, addr=%r, sqft=%s",
                 price, beds, baths, address, sqft)

        listing = Listing(
            source="streeteasy",
            url=url,
            listing_type=listing_type,
            price=price,
            beds=beds,
            baths=baths,
            address=address,
            neighborhood=neighborhood.strip() if neighborhood else None,
            thumbnail_url=thumbnail,
            image_urls=list(dict.fromkeys(all_image_urls)),
            sqft=sqft,
            description=description,
            contact_name=contact_name,
            contact_phone=amenities.get("contact_phone") or contact_phone,
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
            no_fee=no_fee,
            available_date=amenities.get("available_date"),
            floor=amenities.get("floor"),
            date_listed=date_listed,
            latitude=latitude,
            longitude=longitude,
            hoa_fee=amenities.get("hoa_fee"),
            year_built=amenities.get("year_built"),
            property_type=amenities.get("property_type"),
            tax_annual=amenities.get("tax_annual"),
        )

        is_sale = listing_type == "sale"
        if listing.matches(
            min_beds=settings.sale_min_beds if is_sale else settings.min_beds,
            min_baths=settings.sale_min_baths if is_sale else settings.min_baths,
            max_price=settings.max_sale_price if is_sale else settings.max_rent,
        ):
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


def _save_json_ld_listing(item: dict, settings: Settings, on_listing: Callable | None, listing_type: str = "rental") -> bool:
    """Parse a JSON-LD ApartmentComplex/Apartment item and save it."""
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

        beds = None
        if "numberOfBedrooms" in item:
            try:
                beds = int(item["numberOfBedrooms"])
            except (ValueError, TypeError):
                pass

        baths = None
        if "numberOfBathroomsTotal" in item:
            try:
                baths = float(item["numberOfBathroomsTotal"])
            except (ValueError, TypeError):
                pass

        sqft = None
        floor_size = item.get("floorSize")
        if isinstance(floor_size, dict):
            try:
                sqft = int(str(floor_size.get("value", "")).replace(",", ""))
            except (ValueError, TypeError):
                pass
        elif isinstance(floor_size, (int, float)):
            sqft = int(floor_size)

        description = item.get("description")

        all_image_urls: list[str] = []
        thumbnail = None
        for img_field in ("photo", "image"):
            raw = item.get(img_field)
            if isinstance(raw, list):
                for img_item in raw:
                    if isinstance(img_item, str) and img_item not in all_image_urls:
                        all_image_urls.append(img_item)
                    elif isinstance(img_item, dict):
                        u = img_item.get("url") or img_item.get("image")
                        if u and u not in all_image_urls:
                            all_image_urls.append(u)
            elif isinstance(raw, dict):
                u = raw.get("image") or raw.get("url")
                if u and u not in all_image_urls:
                    all_image_urls.append(u)
            elif isinstance(raw, str) and raw not in all_image_urls:
                all_image_urls.append(raw)
        thumbnail = all_image_urls[0] if all_image_urls else None

        listing_url = item.get("url") or ""
        if not listing_url:
            listing_url = f"https://streeteasy.com/building/{item.get('name', 'unknown')}"

        date_listed = item.get("datePosted")

        latitude = None
        longitude = None
        geo = item.get("geo")
        if isinstance(geo, dict):
            try:
                latitude = float(geo.get("latitude", 0)) or None
                longitude = float(geo.get("longitude", 0)) or None
            except (ValueError, TypeError):
                pass

        amenities = scan_amenities(description) if description else {}

        listing = Listing(
            source="streeteasy",
            url=listing_url or "https://streeteasy.com",
            listing_type=listing_type,
            price=price,
            beds=beds,
            baths=baths,
            address=address,
            neighborhood=neighborhood,
            thumbnail_url=thumbnail,
            image_urls=all_image_urls,
            sqft=sqft,
            description=description,
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
            date_listed=str(date_listed) if date_listed else None,
            latitude=latitude,
            longitude=longitude,
            hoa_fee=amenities.get("hoa_fee"),
            year_built=amenities.get("year_built"),
            property_type=amenities.get("property_type"),
            tax_annual=amenities.get("tax_annual"),
        )

        is_sale = listing_type == "sale"
        if listing.matches(
            min_beds=settings.sale_min_beds if is_sale else settings.min_beds,
            min_baths=settings.sale_min_baths if is_sale else settings.min_baths,
            max_price=settings.max_sale_price if is_sale else settings.max_rent,
        ):
            upsert_listing(listing)
            if on_listing:
                on_listing()
            log.info("[streeteasy] Saved JSON-LD listing: %s ($%s, %sbd)", address, price, beds)
            return True
    except Exception:
        log.debug("Failed to process JSON-LD listing", exc_info=True)
    return False


def _save_card_listing(card: dict, settings: Settings, on_listing: Callable | None, listing_type: str = "rental") -> bool:
    """Parse a listing card extracted from DOM and save it."""
    try:
        url = card.get("url") or ""
        if not url:
            return False

        full_text = card.get("details") or ""

        price = None
        price_text = card.get("price") or full_text
        m = _PRICE_RE.search(price_text)
        if m:
            price = int(m.group(1).replace(",", ""))

        beds = None
        beds_text = card.get("beds") or full_text
        m_bed = _BED_RE.search(beds_text)
        if m_bed:
            beds = int(m_bed.group(1))

        baths = None
        baths_text = card.get("baths") or full_text
        m_bath = _BATH_RE.search(baths_text)
        if m_bath:
            baths = float(m_bath.group(1))

        sqft = None
        sqft_text = card.get("sqft") or full_text
        m_sqft = _SQFT_RE.search(sqft_text)
        if m_sqft:
            try:
                sqft = int(m_sqft.group(1).replace(",", ""))
            except ValueError:
                pass

        neighborhood = card.get("neighborhood")
        if not neighborhood and full_text:
            m_neigh = re.search(r"(?:Rental\s+unit|For\s+sale|Condo|Co-op|House)\s+in\s+(.+?)(?:\s*$|\s*\d)", full_text, re.IGNORECASE)
            if m_neigh:
                neighborhood = m_neigh.group(1).strip()

        listing = Listing(
            source="streeteasy",
            url=url,
            listing_type=listing_type,
            price=price,
            beds=beds,
            baths=baths,
            address=card.get("address"),
            neighborhood=neighborhood,
            thumbnail_url=card.get("image"),
            sqft=sqft,
        )

        is_sale = listing_type == "sale"
        if listing.matches(
            min_beds=settings.sale_min_beds if is_sale else settings.min_beds,
            min_baths=settings.sale_min_baths if is_sale else settings.min_baths,
            max_price=settings.max_sale_price if is_sale else settings.max_rent,
        ):
            upsert_listing(listing)
            if on_listing:
                on_listing()
            log.info("[streeteasy] Saved card listing: %s ($%s, %sbd)", url, price, beds)
            return True
    except Exception:
        log.debug("Failed to process card listing", exc_info=True)
    return False
