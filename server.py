from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import _get_int
from db import (
    create_saved_search,
    delete_saved_search,
    get_all_listings,
    get_listing,
    get_listing_images,
    get_map_listings,
    get_price_drops,
    get_sources,
    get_stats,
    get_trend_listing_volume,
    get_trend_neighborhoods,
    get_trend_price_history,
    get_trend_summary,
    init_db,
    list_saved_searches,
    touch_saved_search,
    update_listing,
)
from proxy_manager import proxy_manager
from worker import IMAGES_DIR, THUMBNAIL_DIR, crawl_manager, geocoding_worker, image_worker, thumbnail_worker

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "frontend" / "out"

app = FastAPI(title="Rent Lobster")


@app.on_event("startup")
def startup() -> None:
    proxy_count = _get_int("PROXY_COUNT", 5)
    manual_urls = os.getenv("PROXY_URLS", "").strip()
    if not manual_urls and proxy_count > 0:
        urls = proxy_manager.start(proxy_count)
        if urls:
            log.info("Auto-started %d proxies: %s", len(urls), urls)
    elif manual_urls:
        log.info("Using manually configured PROXY_URLS")

    init_db()
    thumbnail_worker.start()
    image_worker.start()
    geocoding_worker.start()


@app.on_event("shutdown")
def shutdown() -> None:
    thumbnail_worker.stop()
    image_worker.stop()
    geocoding_worker.stop()
    proxy_manager.stop()


# ---- Listings API ---------------------------------------------------------

@app.get("/api/listings")
def api_listings(
    source: str | None = Query(None),
    min_price: int | None = Query(None),
    max_price: int | None = Query(None),
    min_beds: int | None = Query(None),
    status: str | None = Query(None),
    is_favorite: bool | None = Query(None),
    sort: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
    listing_type: str = Query("rental"),
) -> dict:
    return get_all_listings(
        source=source,
        min_price=min_price,
        max_price=max_price,
        min_beds=min_beds,
        status=status,
        is_favorite=is_favorite,
        sort=sort,
        page=page,
        per_page=per_page,
        listing_type=listing_type,
    )


@app.get("/api/listings/{listing_id}")
def api_listing_detail(listing_id: int) -> dict:
    row = get_listing(listing_id)
    if row is None:
        raise HTTPException(404, "Listing not found")
    row["images"] = get_listing_images(listing_id)
    return row


@app.patch("/api/listings/{listing_id}")
def api_listing_update(listing_id: int, body: dict[str, Any]) -> dict:
    existing = get_listing(listing_id)
    if existing is None:
        raise HTTPException(404, "Listing not found")
    updated = update_listing(listing_id, body)
    if updated is None:
        raise HTTPException(500, "Failed to update listing")
    return updated


@app.get("/api/listings/map")
def api_listings_map(
    source: str | None = Query(None),
    min_price: int | None = Query(None),
    max_price: int | None = Query(None),
    min_beds: int | None = Query(None),
    status: str | None = Query(None),
    is_favorite: bool | None = Query(None),
    listing_type: str = Query("rental"),
) -> list[dict]:
    return get_map_listings(
        source=source,
        min_price=min_price,
        max_price=max_price,
        min_beds=min_beds,
        status=status,
        is_favorite=is_favorite,
        listing_type=listing_type,
    )


@app.get("/api/sources")
def api_sources(listing_type: str = Query("rental")) -> list[str]:
    return get_sources(listing_type=listing_type)


@app.get("/api/stats")
def api_stats(listing_type: str = Query("rental")) -> dict:
    return get_stats(listing_type=listing_type)


# ---- Crawl control API ----------------------------------------------------

class CrawlRequest(BaseModel):
    spiders: list[str]
    max_pages: int = 50
    listing_type: str = "rental"


@app.post("/api/crawl")
def api_crawl_start(req: CrawlRequest) -> dict:
    valid = {"craigslist", "streeteasy", "zillow"}
    chosen = [s for s in req.spiders if s in valid]
    if not chosen:
        raise HTTPException(400, "No valid spiders selected")
    try:
        job = crawl_manager.start(chosen, req.max_pages, listing_type=req.listing_type)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return job.to_dict()


@app.get("/api/crawl/status")
def api_crawl_status() -> dict:
    job = crawl_manager.current_job
    if job is None:
        return {"status": "idle"}
    return job.to_dict()


# ---- Thumbnail API --------------------------------------------------------

@app.get("/api/thumbnails/{filename:path}")
def api_thumbnail(filename: str) -> FileResponse:
    path = THUMBNAIL_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "Thumbnail not found")
    media = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/jpeg")
    return FileResponse(path, media_type=media)


@app.get("/api/images/{filename:path}")
def api_image(filename: str) -> FileResponse:
    path = IMAGES_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "Image not found")
    media = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/jpeg")
    return FileResponse(path, media_type=media)


# ---- Saved searches API ---------------------------------------------------

class SavedSearchCreate(BaseModel):
    name: str
    listing_type: str = "rental"
    filters: dict[str, Any] = {}


@app.get("/api/saved-searches")
def api_saved_searches_list(listing_type: str = Query("rental")) -> list[dict]:
    return list_saved_searches(listing_type=listing_type)


@app.post("/api/saved-searches")
def api_saved_search_create(body: SavedSearchCreate) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Name is required")
    return create_saved_search(name=name, listing_type=body.listing_type, filters=body.filters)


@app.delete("/api/saved-searches/{saved_search_id}")
def api_saved_search_delete(saved_search_id: int) -> dict:
    ok = delete_saved_search(saved_search_id)
    if not ok:
        raise HTTPException(404, "Saved search not found")
    return {"ok": True}


@app.post("/api/saved-searches/{saved_search_id}/use")
def api_saved_search_touch(saved_search_id: int) -> dict:
    row = touch_saved_search(saved_search_id)
    if row is None:
        raise HTTPException(404, "Saved search not found")
    return row


# ---- Trends API -----------------------------------------------------------

@app.get("/api/trends/summary")
def api_trends_summary(listing_type: str = Query("sale")) -> dict:
    return get_trend_summary(listing_type=listing_type)


@app.get("/api/trends/neighborhoods")
def api_trends_neighborhoods(
    listing_type: str = Query("sale"),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    return get_trend_neighborhoods(listing_type=listing_type, limit=limit)


@app.get("/api/trends/price-history")
def api_trends_price_history(
    listing_type: str = Query("sale"),
    weeks: int = Query(12, ge=1, le=104),
    neighborhood: str | None = Query(None),
) -> list[dict]:
    return get_trend_price_history(
        listing_type=listing_type, weeks=weeks, neighborhood=neighborhood,
    )


@app.get("/api/trends/listing-volume")
def api_trends_listing_volume(
    listing_type: str = Query("sale"),
    weeks: int = Query(12, ge=1, le=104),
) -> list[dict]:
    return get_trend_listing_volume(listing_type=listing_type, weeks=weeks)


@app.get("/api/trends/price-drops")
def api_trends_price_drops(
    listing_type: str = Query("sale"),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict]:
    return get_price_drops(listing_type=listing_type, limit=limit)


# ---- Static frontend (must be registered last) ----------------------------

if STATIC_DIR.is_dir():
    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/buy")
    async def buy_page() -> FileResponse:
        buy_html = STATIC_DIR / "buy.html"
        buy_index = STATIC_DIR / "buy" / "index.html"
        if buy_html.exists():
            return FileResponse(buy_html)
        if buy_index.exists():
            return FileResponse(buy_index)
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/trends")
    async def trends_page() -> FileResponse:
        trends_html = STATIC_DIR / "trends.html"
        trends_index = STATIC_DIR / "trends" / "index.html"
        if trends_html.exists():
            return FileResponse(trends_html)
        if trends_index.exists():
            return FileResponse(trends_index)
        return FileResponse(STATIC_DIR / "index.html")

    next_dir = STATIC_DIR / "_next"
    if next_dir.is_dir():
        app.mount("/_next", StaticFiles(directory=str(next_dir)), name="nextjs")

    app.mount("/", StaticFiles(directory=str(STATIC_DIR)), name="static")
