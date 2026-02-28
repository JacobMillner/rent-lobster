from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import urlparse

from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext

from config import Settings
from db import upsert_listing
from models import Listing, scan_amenities, _SQFT_RE

_PRICE_RE = re.compile(r"\$([\d,]+)")
_BED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*br\b", re.IGNORECASE)
_BATH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*ba\b", re.IGNORECASE)

_LISTING_RE = re.compile(r"/\d+\.html$")


def _same_site(url: str, seed_host: str) -> bool:
    try:
        host = urlparse(url).netloc
    except Exception:
        return False
    return host == seed_host


def _looks_like_listing_url(url: str) -> bool:
    """True for URLs like /brk/apa/d/some-title/7890123456.html"""
    return bool(_LISTING_RE.search(urlparse(url).path))


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
            beds = int(float(m_bed.group(1)))
        except Exception:
            pass

    m_bath = _BATH_RE.search(text)
    if m_bath:
        try:
            baths = float(m_bath.group(1))
        except Exception:
            pass

    return beds, baths


def build_craigslist_crawler(
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
        max_requests_per_crawl=max_pages or settings.max_requests,
        respect_robots_txt_file=settings.respect_robots,
    )
    if configuration is not None:
        kwargs["configuration"] = configuration
    crawler = PlaywrightCrawler(**kwargs)

    @crawler.router.default_handler
    async def handle(context: PlaywrightCrawlingContext) -> None:
        url = context.request.url
        context.log.info(f"[craigslist] Visiting {url}")
        if on_page:
            on_page()

        seed_host = context.request.user_data.get("seed_host") or urlparse(url).netloc
        is_listing = _looks_like_listing_url(url)

        if not is_listing:
            # --- SEARCH RESULTS PAGE ---
            # Wait for dynamic content to load
            try:
                await context.page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass

            # Try several selectors (CL has changed layouts multiple times)
            links: list[str] = []
            for selector in [
                "a.posting-title",              # 2024+ gallery view
                "a.titlestring",                # alternate layout
                "a.result-title",               # classic layout
                "li.cl-static-search-result a", # static search
                "li.cl-search-result a",        # older dynamic search
                "a.result-title.hdrlnk",        # legacy
            ]:
                links = await context.page.eval_on_selector_all(
                    selector,
                    "els => els.map(e => e.href).filter(Boolean)",
                )
                if links:
                    context.log.info(f"[craigslist] Matched selector '{selector}' → {len(links)} links")
                    break

            # Broadest fallback: any <a> whose href ends in a CL listing pattern
            if not links:
                links = await context.page.eval_on_selector_all(
                    "a[href]",
                    """els => els.map(e => e.href)
                              .filter(h => h && /\\/\\d+\\.html$/.test(new URL(h).pathname))""",
                )
                if links:
                    context.log.info(f"[craigslist] Broad fallback found {len(links)} listing links")

            to_enqueue = [
                u for u in dict.fromkeys(links)
                if _looks_like_listing_url(u) and _same_site(u, seed_host)
            ]
            if to_enqueue:
                context.log.info(f"[craigslist] Enqueuing {len(to_enqueue)} listing pages")
                from crawlee import Request as CrawleeRequest
                await context.add_requests(
                    [CrawleeRequest(url=u, unique_key=u, user_data={"seed_host": seed_host}) for u in to_enqueue],
                )
            else:
                context.log.warning("[craigslist] No listing links found on search page")

            # Pagination
            for next_sel in ["a.button.next", "button.bd-button.cl-next-page", "a[title='next page']"]:
                next_links = await context.page.eval_on_selector_all(
                    next_sel,
                    "els => els.map(e => e.href).filter(Boolean)",
                )
                if next_links and _same_site(next_links[0], seed_host):
                    from crawlee import Request as CrawleeRequest
                    await context.add_requests(
                        [CrawleeRequest(url=next_links[0], unique_key=next_links[0], user_data={"seed_host": seed_host})],
                    )
                    break
            return

        # --- LISTING PAGE ---
        title = (await context.page.text_content("span#titletextonly")) or (await context.page.title()) or ""
        price_text = (await context.page.text_content("span.price")) or ""
        price = _parse_int_price(price_text) or _parse_int_price(title)

        housing = (await context.page.text_content("span.housing")) or ""
        beds, baths = _parse_beds_baths(housing)

        sqft = None
        m_sqft = _SQFT_RE.search(housing)
        if m_sqft:
            try:
                sqft = int(m_sqft.group(1).replace(",", ""))
            except ValueError:
                pass

        neighborhood = (await context.page.text_content("small")) or None
        if neighborhood:
            neighborhood = neighborhood.strip("() \n\t") or None

        all_image_urls: list[str] = []

        imgs = await context.page.eval_on_selector_all(
            'img[src*="images.craigslist.org"]',
            "els => els.map(e => e.src).filter(Boolean)",
        )
        if imgs:
            all_image_urls = list(dict.fromkeys(imgs))

        thumb_links = await context.page.eval_on_selector_all(
            '#thumbs a[href*="images.craigslist.org"]',
            "els => els.map(e => e.href).filter(Boolean)",
        )
        if thumb_links:
            for tl in thumb_links:
                if tl not in all_image_urls:
                    all_image_urls.append(tl)

        thumbnail = await context.page.get_attribute('meta[property="og:image"]', "content")
        if not thumbnail and all_image_urls:
            thumbnail = all_image_urls[0]

        description = None
        try:
            body_el = await context.page.query_selector("section#postingbody")
            if body_el:
                description = (await body_el.text_content()) or None
                if description:
                    description = re.sub(r"QR Code Link to This Post", "", description).strip()
        except Exception:
            pass

        body_text = description or ""
        if not body_text:
            try:
                body_text = (await context.page.text_content("body")) or ""
            except Exception:
                body_text = ""

        if not sqft and body_text:
            m_sqft = _SQFT_RE.search(body_text)
            if m_sqft:
                try:
                    sqft = int(m_sqft.group(1).replace(",", ""))
                except ValueError:
                    pass

        amenities = scan_amenities(body_text) if body_text else {}

        attrs_text = ""
        try:
            attr_groups = await context.page.eval_on_selector_all(
                "p.attrgroup span",
                "els => els.map(e => e.textContent).filter(Boolean)",
            )
            if attr_groups:
                attrs_text = " ".join(attr_groups)
                attr_amenities = scan_amenities(attrs_text)
                for k, v in attr_amenities.items():
                    if v is not None and k not in amenities:
                        amenities[k] = v
        except Exception:
            pass

        # Date listed from <time> element
        date_listed = None
        try:
            date_listed = await context.page.eval_on_selector_all(
                "time.date[datetime], time.timeago[datetime]",
                "els => els.map(e => e.getAttribute('datetime')).filter(Boolean)",
            )
            date_listed = date_listed[0] if date_listed else None
        except Exception:
            pass

        # Coordinates from the map
        latitude = None
        longitude = None
        try:
            map_el = await context.page.query_selector("#map[data-latitude][data-longitude]")
            if map_el:
                lat_str = await map_el.get_attribute("data-latitude")
                lng_str = await map_el.get_attribute("data-longitude")
                if lat_str and lng_str:
                    latitude = float(lat_str)
                    longitude = float(lng_str)
        except Exception:
            pass

        listing = Listing(
            source="craigslist",
            url=url,
            listing_type=listing_type,
            price=price,
            beds=beds,
            baths=baths,
            neighborhood=neighborhood,
            address=title.strip() or None,
            thumbnail_url=thumbnail,
            image_urls=all_image_urls,
            sqft=sqft,
            description=description,
            contact_name=amenities.get("contact_name"),
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
        else:
            context.log.info(f"[craigslist] Filtered out: {listing.url} (${listing.price}, {listing.beds}br, {listing.baths}ba)")

    return crawler
