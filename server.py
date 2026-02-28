from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import get_all_listings, get_listing, get_map_listings, get_sources, get_stats, init_db, update_listing
from worker import THUMBNAIL_DIR, crawl_manager, geocoding_worker, thumbnail_worker

STATIC_DIR = Path(__file__).resolve().parent / "frontend" / "out"

app = FastAPI(title="Rent Lobster")


@app.on_event("startup")
def startup() -> None:
    init_db()
    thumbnail_worker.start()
    geocoding_worker.start()


@app.on_event("shutdown")
def shutdown() -> None:
    thumbnail_worker.stop()
    geocoding_worker.stop()


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
    )


@app.get("/api/listings/{listing_id}")
def api_listing_detail(listing_id: int) -> dict:
    row = get_listing(listing_id)
    if row is None:
        raise HTTPException(404, "Listing not found")
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
) -> list[dict]:
    return get_map_listings(
        source=source,
        min_price=min_price,
        max_price=max_price,
        min_beds=min_beds,
        status=status,
        is_favorite=is_favorite,
    )


@app.get("/api/sources")
def api_sources() -> list[str]:
    return get_sources()


@app.get("/api/stats")
def api_stats() -> dict:
    return get_stats()


# ---- Crawl control API ----------------------------------------------------

class CrawlRequest(BaseModel):
    spiders: list[str]
    max_pages: int = 50


@app.post("/api/crawl")
def api_crawl_start(req: CrawlRequest) -> dict:
    valid = {"craigslist", "streeteasy", "zillow"}
    chosen = [s for s in req.spiders if s in valid]
    if not chosen:
        raise HTTPException(400, "No valid spiders selected")
    try:
        job = crawl_manager.start(chosen, req.max_pages)
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


# ---- Static frontend (must be registered last) ----------------------------

if STATIC_DIR.is_dir():
    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    next_dir = STATIC_DIR / "_next"
    if next_dir.is_dir():
        app.mount("/_next", StaticFiles(directory=str(next_dir)), name="nextjs")

    app.mount("/", StaticFiles(directory=str(STATIC_DIR)), name="static")
