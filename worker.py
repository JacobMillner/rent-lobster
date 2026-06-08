from __future__ import annotations

import asyncio
import logging
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image

from db import get_images_needing_download, get_listings_needing_geocoding, get_listings_needing_thumbnails, mark_geocode_failed, update_coordinates, update_image_path, update_thumbnail_path
from nyc_locations import BOROUGHS_BY_ID, CrawlFilters, CrawlLocation, build_start_urls

MIN_IMAGE_DIMENSION = 200

log = logging.getLogger(__name__)

THUMBNAIL_DIR = Path(__file__).resolve().parent / "thumbnails"
IMAGES_DIR = Path(__file__).resolve().parent / "images"
STORAGE_DIR = Path(__file__).resolve().parent / "storage"

# A bare "Mozilla/5.0" gets rejected by a number of listing-image CDNs
# (StreetEasy and Zillow image hosts in particular). Send a realistic modern
# Chrome UA plus image-friendly Accept headers so the image worker hits a
# similar success rate to a real browser tab.
_IMAGE_DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Crawl job state
# ---------------------------------------------------------------------------

@dataclass
class CrawlJob:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "pending"
    spiders: list[str] = field(default_factory=list)
    max_pages: int = 50
    listing_type: str = "rental"
    location: dict | None = None
    filters: dict | None = None
    pages_crawled: int = 0
    listings_found: int = 0
    current_spider: str | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "status": self.status,
                "spiders": self.spiders,
                "max_pages": self.max_pages,
                "listing_type": self.listing_type,
                "location": self.location,
                "filters": self.filters,
                "pages_crawled": self.pages_crawled,
                "listings_found": self.listings_found,
                "current_spider": self.current_spider,
                "error": self.error,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }

    def inc_pages(self) -> None:
        with self._lock:
            self.pages_crawled += 1

    def inc_listings(self) -> None:
        with self._lock:
            self.listings_found += 1


# ---------------------------------------------------------------------------
# Crawl manager
#
# Uses a single persistent event loop in a daemon thread so that Crawlee's
# internal asyncio.Lock objects stay bound to the same loop across crawl runs.
# The storage directory is wiped before each spider to avoid stale request
# queues making Crawlee think URLs were already visited.
# ---------------------------------------------------------------------------

class CrawlManager:
    def __init__(self) -> None:
        self._current: CrawlJob | None = None
        self._lock = threading.Lock()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    @property
    def current_job(self) -> CrawlJob | None:
        return self._current

    def start(
        self,
        spiders: list[str],
        max_pages: int,
        listing_type: str = "rental",
        location: dict | None = None,
        filters: dict | None = None,
    ) -> CrawlJob:
        # Validate the location eagerly so the API returns a 400 instead of the
        # job silently erroring out in the background.
        if location is not None:
            CrawlLocation(
                borough=location["borough"],
                neighborhood=location.get("neighborhood"),
            ).resolve()
        with self._lock:
            if self._current and self._current.status == "running":
                raise RuntimeError("A crawl is already running")
            job = CrawlJob(
                spiders=list(spiders),
                max_pages=max_pages,
                listing_type=listing_type,
                location=location,
                filters=filters,
            )
            self._current = job
            asyncio.run_coroutine_threadsafe(self._crawl_wrapper(job), self._loop)
            return job

    async def _crawl_wrapper(self, job: CrawlJob) -> None:
        job.status = "running"
        job.started_at = datetime.now(timezone.utc).isoformat()
        try:
            await self._crawl(job)
            job.status = "completed"
        except Exception as exc:
            log.exception("Crawl failed")
            job.status = "error"
            job.error = str(exc)
        finally:
            job.finished_at = datetime.now(timezone.utc).isoformat()
            job.current_spider = None

    @staticmethod
    def _purge_spider_storage(spider_name: str) -> None:
        # Crawlee's ``StorageInstanceManager`` is a process-wide singleton that
        # caches RequestQueue (and KeyValueStore) instances keyed by storage_dir.
        # If we don't drop that cache, the next crawl reuses the previous
        # crawl's in-memory queue — including its ``state.handled_requests`` set
        # and its (now-stale) ``total_request_count`` metadata — even though
        # we've wiped the on-disk storage dir below.
        #
        # The symptom of forgetting this is dramatic: the second crawl's start
        # URL collides with a unique_key already in ``handled_requests`` from
        # the previous crawl (e.g. craigslist's borough-level URL is the same
        # for two different neighborhoods), so the new request is silently
        # dropped as "already handled". Meanwhile ``state.regular_requests``
        # still has every URL the previous crawl ever enqueued, but the actual
        # request JSON files on disk are gone. The crawler then loops forever
        # logging ``Crawled 0/N pages`` because ``is_empty`` says "no, there's
        # unhandled work" while ``fetch_next_request`` can't actually find any
        # request files to dispatch.
        try:
            from crawlee import service_locator
            service_locator.storage_instance_manager.clear_cache()
        except Exception:
            log.debug("Failed to clear crawlee storage instance cache", exc_info=True)

        spider_dir = STORAGE_DIR / spider_name
        for attempt in range(5):
            if not spider_dir.exists():
                break
            try:
                shutil.rmtree(spider_dir)
                break
            except OSError:
                if attempt < 4:
                    import time
                    time.sleep(0.2 * (attempt + 1))
                else:
                    log.warning("Could not fully remove %s, continuing anyway", spider_dir)
        spider_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _spider_config(spider_name: str) -> "CrawleeConfiguration":
        from crawlee.configuration import Configuration as CrawleeConfiguration
        return CrawleeConfiguration(
            storage_dir=str(STORAGE_DIR / spider_name),
            purge_on_start=True,
        )

    async def _crawl(self, job: CrawlJob) -> None:
        from crawlee import Request as CrawleeRequest
        from config import Settings
        import dataclasses

        settings = Settings()
        is_sale = job.listing_type == "sale"

        # If the job has explicit location + filters from the UI, build the
        # search URLs dynamically and override the matches() filter thresholds
        # so the per-listing filter agrees with what the URL asked for.
        built_urls: dict[str, list[str]] = {}
        if job.location is not None:
            location = CrawlLocation(
                borough=job.location["borough"],
                neighborhood=job.location.get("neighborhood"),
            )
            filters = CrawlFilters.from_dict(job.filters)
            built_urls = build_start_urls(
                location,
                listing_type=job.listing_type,
                filters=filters,
                spiders=job.spiders,
            )

            overrides: dict = {}
            if filters.min_beds is not None:
                if is_sale:
                    overrides["sale_min_beds"] = filters.min_beds
                else:
                    overrides["min_beds"] = filters.min_beds
            if filters.min_baths is not None:
                if is_sale:
                    overrides["sale_min_baths"] = int(filters.min_baths)
                else:
                    overrides["min_baths"] = int(filters.min_baths)
            if filters.max_price is not None:
                if is_sale:
                    overrides["max_sale_price"] = filters.max_price
                else:
                    overrides["max_rent"] = filters.max_price
            if filters.min_price is not None:
                if is_sale:
                    overrides["min_sale_price"] = filters.min_price
                else:
                    overrides["min_rent"] = filters.min_price
            if overrides:
                settings = dataclasses.replace(settings, **overrides)

        for spider_name in job.spiders:
            job.current_spider = spider_name
            self._purge_spider_storage(spider_name)
            config = self._spider_config(spider_name)
            log.info("[worker] Starting spider %s (listing_type=%s)", spider_name, job.listing_type)

            # Gate StreetEasy to NYC boroughs only.
            if spider_name == "streeteasy" and job.location is not None:
                if job.location["borough"] not in BOROUGHS_BY_ID:
                    log.info("[worker] Skipping streeteasy: borough %r is not NYC", job.location["borough"])
                    continue

            if spider_name == "craigslist":
                start_urls = built_urls.get("craigslist") or (
                    settings.craigslist_sale_start_urls if is_sale else settings.craigslist_start_urls
                )
                if start_urls:
                    from spiders.craigslist import build_craigslist_crawler

                    c = build_craigslist_crawler(
                        settings,
                        max_pages=job.max_pages,
                        on_page=job.inc_pages,
                        on_listing=job.inc_listings,
                        configuration=config,
                        listing_type=job.listing_type,
                    )
                    requests = [
                        CrawleeRequest(
                            url=u,
                            unique_key=u,
                            user_data={"seed_host": urlparse(u).netloc},
                        )
                        for u in start_urls
                    ]
                    log.info("[worker] craigslist: %d start URLs", len(requests))
                    await c.run(requests)

            elif spider_name == "streeteasy":
                start_urls = built_urls.get("streeteasy") or (
                    settings.streeteasy_sale_start_urls if is_sale else settings.streeteasy_start_urls
                )
                if start_urls:
                    from spiders.streeteasy import build_streeteasy_crawler

                    s = build_streeteasy_crawler(
                        settings,
                        max_pages=job.max_pages,
                        on_page=job.inc_pages,
                        on_listing=job.inc_listings,
                        configuration=config,
                        listing_type=job.listing_type,
                    )
                    requests = [
                        CrawleeRequest(url=u, unique_key=u)
                        for u in start_urls
                    ]
                    log.info("[worker] streeteasy: %d start URLs: %s", len(requests), start_urls)
                    await s.run(requests)

            elif spider_name == "zillow":
                start_urls = built_urls.get("zillow") or (
                    settings.zillow_sale_start_urls if is_sale else settings.zillow_start_urls
                )
                if start_urls:
                    from spiders.zillow import build_zillow_crawler

                    z = build_zillow_crawler(
                        settings,
                        max_pages=job.max_pages,
                        on_page=job.inc_pages,
                        on_listing=job.inc_listings,
                        configuration=config,
                        listing_type=job.listing_type,
                    )
                    requests = [
                        CrawleeRequest(url=u, unique_key=u)
                        for u in start_urls
                    ]
                    log.info("[worker] zillow: %d start URLs: %s", len(requests), start_urls)
                    await z.run(requests)

            log.info("[worker] Spider %s finished", spider_name)


# ---------------------------------------------------------------------------
# Thumbnail worker — downloads images in a background thread
# ---------------------------------------------------------------------------

class ThumbnailWorker:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        THUMBNAIL_DIR.mkdir(exist_ok=True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                rows = get_listings_needing_thumbnails()
                for row in rows:
                    if self._stop.is_set():
                        break
                    self._download_one(row["id"], row["thumbnail_url"])
            except Exception:
                log.exception("Thumbnail worker error")
            self._stop.wait(4)

    def _download_one(self, listing_id: int, url: str) -> None:
        ext = Path(urlparse(url).path).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            ext = ".jpg"
        dest = THUMBNAIL_DIR / f"{listing_id}{ext}"
        if dest.exists():
            update_thumbnail_path(listing_id, dest.name)
            return
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.get(url, headers=_IMAGE_DOWNLOAD_HEADERS)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                try:
                    with Image.open(dest) as img:
                        w, h = img.size
                    if w < MIN_IMAGE_DIMENSION or h < MIN_IMAGE_DIMENSION:
                        log.debug("Thumbnail too small (%dx%d) for listing %s — discarding", w, h, listing_id)
                        dest.unlink(missing_ok=True)
                        return
                except Exception:
                    pass
                update_thumbnail_path(listing_id, dest.name)
        except Exception:
            log.debug("Failed to download thumbnail for listing %s", listing_id)


# ---------------------------------------------------------------------------
# Image worker — downloads all listing images in a background thread
# ---------------------------------------------------------------------------

class ImageWorker:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        IMAGES_DIR.mkdir(exist_ok=True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                rows = get_images_needing_download()
                for row in rows:
                    if self._stop.is_set():
                        break
                    self._download_one(
                        row["id"], row["listing_id"],
                        row["image_url"], row["position"],
                    )
            except Exception:
                log.exception("Image worker error")
            self._stop.wait(4)

    def _download_one(
        self, image_id: int, listing_id: int, url: str, position: int,
    ) -> None:
        ext = Path(urlparse(url).path).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            ext = ".jpg"
        filename = f"{listing_id}_{position}{ext}"
        dest = IMAGES_DIR / filename
        if dest.exists():
            update_image_path(image_id, filename)
            return
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.get(url, headers=_IMAGE_DOWNLOAD_HEADERS)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                try:
                    with Image.open(dest) as img:
                        w, h = img.size
                    if w < MIN_IMAGE_DIMENSION or h < MIN_IMAGE_DIMENSION:
                        log.debug("Image too small (%dx%d) for listing %s pos %d — discarding",
                                  w, h, listing_id, position)
                        dest.unlink(missing_ok=True)
                        return
                except Exception:
                    pass
                update_image_path(image_id, filename)
        except Exception:
            log.debug("Failed to download image %s for listing %s", image_id, listing_id)


# ---------------------------------------------------------------------------
# Geocoding worker — resolves addresses to lat/lng via Nominatim (OSM)
# ---------------------------------------------------------------------------

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


class GeocodingWorker:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                rows = get_listings_needing_geocoding(limit=10)
                if not rows:
                    self._stop.wait(30)
                    continue
                for row in rows:
                    if self._stop.is_set():
                        break
                    if self._geocode_one(row) == "rate_limited":
                        log.warning("[geocoding] Nominatim returned 429 — backing off 60s")
                        self._stop.wait(60)
                        break
                    # Nominatim requires max 1 request/second
                    self._stop.wait(1.1)
            except Exception:
                log.exception("Geocoding worker error")
                self._stop.wait(15)

    @staticmethod
    def _geocode_one(row: dict) -> str | None:
        """Geocode a single row.

        Returns ``"rate_limited"`` so the outer loop can apply a longer back-off
        without marking this listing as permanently failed. Returns ``None`` on
        success or any other terminal outcome.
        """
        listing_id = row["id"]
        query = row["address"] or ""
        if row.get("neighborhood"):
            query = f"{query}, {row['neighborhood']}"
        query = query.strip(", ")
        if not query:
            mark_geocode_failed(listing_id, "no_address")
            return None
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    _NOMINATIM_URL,
                    params={"q": query, "format": "json", "limit": 1},
                    headers={"User-Agent": "RentLobster/1.0 (apartment search tool)"},
                )
                if resp.status_code == 429:
                    # Leave geocode_status alone (still 'pending') so we retry later.
                    return "rate_limited"
                resp.raise_for_status()
                results = resp.json()
                if results and isinstance(results, list) and len(results) > 0:
                    lat = float(results[0]["lat"])
                    lon = float(results[0]["lon"])
                    update_coordinates(listing_id, lat, lon)
                    log.info("[geocoding] Resolved listing %s: %s -> (%s, %s)", listing_id, query, lat, lon)
                else:
                    mark_geocode_failed(listing_id, "no_result")
                    log.info("[geocoding] No results for listing %s: %s", listing_id, query)
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                return "rate_limited"
            mark_geocode_failed(listing_id, "error")
            log.debug("Failed to geocode listing %s: %s", listing_id, query, exc_info=True)
        except Exception:
            mark_geocode_failed(listing_id, "error")
            log.debug("Failed to geocode listing %s: %s", listing_id, query, exc_info=True)
        return None


# Module-level singletons
crawl_manager = CrawlManager()
thumbnail_worker = ThumbnailWorker()
image_worker = ImageWorker()
geocoding_worker = GeocodingWorker()