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

from db import get_listings_needing_thumbnails, update_thumbnail_path

log = logging.getLogger(__name__)

THUMBNAIL_DIR = Path(__file__).resolve().parent / "thumbnails"
STORAGE_DIR = Path(__file__).resolve().parent / "storage"


# ---------------------------------------------------------------------------
# Crawl job state
# ---------------------------------------------------------------------------

@dataclass
class CrawlJob:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "pending"
    spiders: list[str] = field(default_factory=list)
    max_pages: int = 50
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

    def start(self, spiders: list[str], max_pages: int) -> CrawlJob:
        with self._lock:
            if self._current and self._current.status == "running":
                raise RuntimeError("A crawl is already running")
            job = CrawlJob(spiders=list(spiders), max_pages=max_pages)
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
    def _purge_storage() -> None:
        if STORAGE_DIR.exists():
            shutil.rmtree(STORAGE_DIR, ignore_errors=True)

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

        self._purge_storage()
        settings = Settings()

        for spider_name in job.spiders:
            job.current_spider = spider_name
            config = self._spider_config(spider_name)
            log.info("[worker] Starting spider %s", spider_name)

            if spider_name == "craigslist" and settings.craigslist_start_urls:
                from spiders.craigslist import build_craigslist_crawler

                c = build_craigslist_crawler(
                    settings,
                    max_pages=job.max_pages,
                    on_page=job.inc_pages,
                    on_listing=job.inc_listings,
                    configuration=config,
                )
                requests = [
                    CrawleeRequest(
                        url=u,
                        unique_key=u,
                        user_data={"seed_host": urlparse(u).netloc},
                    )
                    for u in settings.craigslist_start_urls
                ]
                log.info("[worker] craigslist: %d start URLs", len(requests))
                await c.run(requests)

            elif spider_name == "streeteasy" and settings.streeteasy_start_urls:
                from spiders.streeteasy import build_streeteasy_crawler

                s = build_streeteasy_crawler(
                    settings,
                    max_pages=job.max_pages,
                    on_page=job.inc_pages,
                    on_listing=job.inc_listings,
                    configuration=config,
                )
                requests = [
                    CrawleeRequest(url=u, unique_key=u)
                    for u in settings.streeteasy_start_urls
                ]
                log.info("[worker] streeteasy: %d start URLs: %s", len(requests), settings.streeteasy_start_urls)
                await s.run(requests)

            elif spider_name == "zillow" and settings.zillow_start_urls:
                from spiders.zillow import build_zillow_crawler

                z = build_zillow_crawler(
                    settings,
                    max_pages=job.max_pages,
                    on_page=job.inc_pages,
                    on_listing=job.inc_listings,
                    configuration=config,
                )
                requests = [
                    CrawleeRequest(url=u, unique_key=u)
                    for u in settings.zillow_start_urls
                ]
                log.info("[worker] zillow: %d start URLs: %s", len(requests), settings.zillow_start_urls)
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
                resp = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                update_thumbnail_path(listing_id, dest.name)
        except Exception:
            log.debug("Failed to download thumbnail for listing %s", listing_id)


# Module-level singletons
crawl_manager = CrawlManager()
thumbnail_worker = ThumbnailWorker()
