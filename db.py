from __future__ import annotations

import sqlite3
from pathlib import Path
from models import Listing

DB_PATH = Path(__file__).resolve().parent / "rent_lobster.db"

_DDL = """
CREATE TABLE IF NOT EXISTS listings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT    NOT NULL,
    url            TEXT    NOT NULL UNIQUE,
    price          INTEGER,
    beds           INTEGER,
    baths          REAL,
    address        TEXT,
    neighborhood   TEXT,
    thumbnail_url  TEXT,
    thumbnail_path TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_MIGRATIONS: list[tuple[str, str]] = [
    ("thumbnail_url", "TEXT"),
    ("thumbnail_path", "TEXT"),
    # Apartment detail fields
    ("sqft", "INTEGER"),
    ("description", "TEXT"),
    ("contact_name", "TEXT"),
    ("contact_phone", "TEXT"),
    ("contact_email", "TEXT"),
    ("subway_minutes", "INTEGER"),
    ("nearest_subway", "TEXT"),
    ("has_dishwasher", "INTEGER"),
    ("has_balcony", "INTEGER"),
    ("laundry", "TEXT"),
    ("has_doorman", "INTEGER"),
    ("has_elevator", "INTEGER"),
    ("has_gym", "INTEGER"),
    ("pets_allowed", "INTEGER"),
    ("no_fee", "INTEGER"),
    ("available_date", "TEXT"),
    ("floor", "TEXT"),
    ("date_listed", "TEXT"),
    ("latitude", "REAL"),
    ("longitude", "REAL"),
    ("geocode_status", "TEXT"),
    # User-managed fields
    ("status", "TEXT DEFAULT 'new'"),
    ("is_favorite", "INTEGER DEFAULT 0"),
    ("notes", "TEXT"),
    # Listing type discriminator
    ("listing_type", "TEXT DEFAULT 'rental'"),
    # Sale-specific fields
    ("hoa_fee", "INTEGER"),
    ("year_built", "INTEGER"),
    ("property_type", "TEXT"),
    ("tax_annual", "INTEGER"),
]

_SCRAPE_FIELDS = [
    "source", "url", "listing_type", "price", "beds", "baths", "address",
    "neighborhood", "thumbnail_url", "sqft", "description", "contact_name",
    "contact_phone", "contact_email", "subway_minutes", "nearest_subway",
    "has_dishwasher", "has_balcony", "laundry", "has_doorman", "has_elevator",
    "has_gym", "pets_allowed", "no_fee", "available_date", "floor",
    "date_listed", "latitude", "longitude",
    "hoa_fee", "year_built", "property_type", "tax_annual",
]

_ALLOWED_UPDATE_FIELDS = {
    "price", "beds", "baths", "address", "neighborhood", "sqft", "description",
    "contact_name", "contact_phone", "contact_email", "subway_minutes",
    "nearest_subway", "has_dishwasher", "has_balcony", "laundry", "has_doorman",
    "has_elevator", "has_gym", "pets_allowed", "no_fee", "available_date",
    "floor", "date_listed", "latitude", "longitude",
    "status", "is_favorite", "notes",
    "hoa_fee", "year_built", "property_type", "tax_annual",
}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_DDL)
        for col, dtype in _MIGRATIONS:
            try:
                conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {dtype}")
            except sqlite3.OperationalError:
                pass


def _bool_to_int(val: bool | None) -> int | None:
    if val is None:
        return None
    return 1 if val else 0


def upsert_listing(listing: Listing) -> None:
    placeholders = ", ".join("?" for _ in _SCRAPE_FIELDS)
    cols = ", ".join(_SCRAPE_FIELDS)

    update_parts = []
    for f in _SCRAPE_FIELDS:
        if f in ("source", "url", "listing_type"):
            continue
        update_parts.append(f"{f} = COALESCE(excluded.{f}, listings.{f})")
    update_clause = ", ".join(update_parts)

    sql = f"""
        INSERT INTO listings ({cols})
        VALUES ({placeholders})
        ON CONFLICT(url) DO UPDATE SET {update_clause}
    """

    values = (
        listing.source,
        str(listing.url),
        listing.listing_type,
        listing.price,
        listing.beds,
        listing.baths,
        listing.address,
        listing.neighborhood,
        listing.thumbnail_url,
        listing.sqft,
        listing.description,
        listing.contact_name,
        listing.contact_phone,
        listing.contact_email,
        listing.subway_minutes,
        listing.nearest_subway,
        _bool_to_int(listing.has_dishwasher),
        _bool_to_int(listing.has_balcony),
        listing.laundry,
        _bool_to_int(listing.has_doorman),
        _bool_to_int(listing.has_elevator),
        _bool_to_int(listing.has_gym),
        _bool_to_int(listing.pets_allowed),
        _bool_to_int(listing.no_fee),
        listing.available_date,
        listing.floor,
        listing.date_listed,
        listing.latitude,
        listing.longitude,
        listing.hoa_fee,
        listing.year_built,
        listing.property_type,
        listing.tax_annual,
    )

    with _connect() as conn:
        conn.execute(sql, values)


_SORT_OPTIONS = {
    "date_listed": "COALESCE(date_listed, created_at) DESC",
    "created_at": "created_at DESC",
    "price_asc": "price ASC",
    "price_desc": "price DESC",
}


def _build_where(
    source: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    min_beds: int | None = None,
    status: str | None = None,
    is_favorite: bool | None = None,
    listing_type: str = "rental",
) -> tuple[str, list[object]]:
    clauses: list[str] = ["COALESCE(listing_type, 'rental') = ?"]
    params: list[object] = [listing_type]

    if source:
        clauses.append("source = ?")
        params.append(source)
    if min_price is not None:
        clauses.append("price >= ?")
        params.append(min_price)
    if max_price is not None:
        clauses.append("price <= ?")
        params.append(max_price)
    if min_beds is not None:
        clauses.append("beds >= ?")
        params.append(min_beds)
    if status:
        clauses.append("COALESCE(status, 'new') = ?")
        params.append(status)
    if is_favorite is not None and is_favorite:
        clauses.append("is_favorite = 1")

    where = f" WHERE {' AND '.join(clauses)}"
    return where, params


def get_all_listings(
    source: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    min_beds: int | None = None,
    status: str | None = None,
    is_favorite: bool | None = None,
    sort: str | None = None,
    page: int = 1,
    per_page: int = 24,
    listing_type: str = "rental",
) -> dict:
    where, params = _build_where(source, min_price, max_price, min_beds, status, is_favorite, listing_type=listing_type)
    order_by = _SORT_OPTIONS.get(sort or "date_listed", _SORT_OPTIONS["date_listed"])

    with _connect() as conn:
        count_row = conn.execute(
            f"SELECT COUNT(*) AS total FROM listings{where}", params
        ).fetchone()
        total = count_row["total"] if count_row else 0

        offset = (page - 1) * per_page
        sql = f"SELECT * FROM listings{where} ORDER BY {order_by} LIMIT ? OFFSET ?"
        rows = conn.execute(sql, [*params, per_page, offset]).fetchall()

        return {
            "listings": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
        }


def get_map_listings(
    source: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    min_beds: int | None = None,
    status: str | None = None,
    is_favorite: bool | None = None,
    listing_type: str = "rental",
) -> list[dict]:
    where, params = _build_where(source, min_price, max_price, min_beds, status, is_favorite, listing_type=listing_type)
    coord_clause = "latitude IS NOT NULL AND longitude IS NOT NULL"
    if where:
        where += f" AND {coord_clause}"
    else:
        where = f" WHERE {coord_clause}"
    with _connect() as conn:
        sql = (
            "SELECT id, latitude, longitude, price, address, beds, baths, "
            f"thumbnail_path, neighborhood, no_fee, source FROM listings{where}"
        )
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


def get_listing(listing_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
        return dict(row) if row else None


def update_listing(listing_id: int, fields: dict) -> dict | None:
    safe = {k: v for k, v in fields.items() if k in _ALLOWED_UPDATE_FIELDS}
    if not safe:
        return get_listing(listing_id)

    set_parts = [f"{k} = ?" for k in safe]
    values = list(safe.values())
    values.append(listing_id)

    with _connect() as conn:
        conn.execute(
            f"UPDATE listings SET {', '.join(set_parts)} WHERE id = ?",
            values,
        )

    return get_listing(listing_id)


def get_sources(listing_type: str = "rental") -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT source FROM listings WHERE COALESCE(listing_type, 'rental') = ? ORDER BY source",
            (listing_type,),
        ).fetchall()
        return [row["source"] for row in rows]


def get_stats(listing_type: str = "rental") -> dict:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*)               AS total,
                COUNT(DISTINCT source) AS sources,
                AVG(price)             AS avg_price,
                MIN(price)             AS min_price,
                MAX(price)             AS max_price
            FROM listings
            WHERE price IS NOT NULL AND COALESCE(listing_type, 'rental') = ?
            """,
            (listing_type,),
        ).fetchone()
        return dict(row) if row else {}


def get_listings_needing_thumbnails(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, thumbnail_url
            FROM listings
            WHERE thumbnail_url IS NOT NULL AND thumbnail_path IS NULL
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def update_thumbnail_path(listing_id: int, path: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE listings SET thumbnail_path = ? WHERE id = ?",
            (path, listing_id),
        )


def get_listings_needing_geocoding(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, address, neighborhood
            FROM listings
            WHERE address IS NOT NULL
              AND latitude IS NULL
              AND (geocode_status IS NULL OR geocode_status = 'pending')
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def update_coordinates(listing_id: int, lat: float, lng: float) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE listings SET latitude = ?, longitude = ?, geocode_status = 'success' WHERE id = ?",
            (lat, lng, listing_id),
        )


def mark_geocode_failed(listing_id: int, reason: str = "no_result") -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE listings SET geocode_status = ? WHERE id = ?",
            (reason, listing_id),
        )
