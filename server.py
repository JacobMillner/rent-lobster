from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from db import get_all_listings, get_sources, get_stats, init_db

STATIC_DIR = Path(__file__).resolve().parent / "frontend" / "out"

app = FastAPI(title="Rent Lobster")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/api/listings")
def api_listings(
    source: str | None = Query(None),
    min_price: int | None = Query(None),
    max_price: int | None = Query(None),
    min_beds: int | None = Query(None),
) -> list[dict]:
    return get_all_listings(
        source=source,
        min_price=min_price,
        max_price=max_price,
        min_beds=min_beds,
    )


@app.get("/api/sources")
def api_sources() -> list[str]:
    return get_sources()


@app.get("/api/stats")
def api_stats() -> dict:
    return get_stats()


if STATIC_DIR.is_dir():
    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/", StaticFiles(directory=str(STATIC_DIR)), name="static")
