from __future__ import annotations

import json
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

CREATE TABLE IF NOT EXISTS listing_images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id  INTEGER NOT NULL REFERENCES listings(id),
    image_url   TEXT    NOT NULL,
    image_path  TEXT,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(listing_id, image_url)
);

CREATE TABLE IF NOT EXISTS saved_searches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    listing_type  TEXT    NOT NULL DEFAULT 'rental',
    filters_json  TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    last_used_at  TEXT
);

CREATE TABLE IF NOT EXISTS price_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id   INTEGER NOT NULL REFERENCES listings(id),
    price        INTEGER NOT NULL,
    recorded_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_listings_type_price ON listings(listing_type, price)",
    "CREATE INDEX IF NOT EXISTS idx_listings_type_neighborhood ON listings(listing_type, neighborhood)",
    "CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_listings_last_seen ON listings(last_seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_price_history_listing ON price_history(listing_id, recorded_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_saved_searches_type ON saved_searches(listing_type)",
]

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
    # Freshness tracking — bumped on every upsert so we can infer active vs stale.
    ("last_seen_at", "TEXT"),
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
        for stmt in _INDEXES:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass


def _bool_to_int(val: bool | None) -> int | None:
    if val is None:
        return None
    return 1 if val else 0


def upsert_listing(listing: Listing) -> int:
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

    url_str = str(listing.url)

    with _connect() as conn:
        # Capture previous price (if any) so we can detect changes after the upsert.
        prev_row = conn.execute(
            "SELECT id, price FROM listings WHERE url = ?", (url_str,)
        ).fetchone()
        prev_price = prev_row["price"] if prev_row else None
        was_new = prev_row is None

        cursor = conn.execute(sql, values)
        listing_id = cursor.lastrowid
        if not listing_id:
            row = conn.execute(
                "SELECT id FROM listings WHERE url = ?", (url_str,)
            ).fetchone()
            listing_id = row["id"] if row else 0

        # Bump freshness marker so trend queries can compute active counts.
        conn.execute(
            "UPDATE listings SET last_seen_at = datetime('now') WHERE id = ?",
            (listing_id,),
        )

        # Record an initial price-history row for brand new listings, and a delta row
        # whenever the price actually changed. Skip NULL prices so the table stays clean.
        new_price = listing.price
        if listing_id and new_price is not None:
            if was_new:
                conn.execute(
                    "INSERT INTO price_history (listing_id, price) VALUES (?, ?)",
                    (listing_id, new_price),
                )
            elif prev_price is not None and prev_price != new_price:
                conn.execute(
                    "INSERT INTO price_history (listing_id, price) VALUES (?, ?)",
                    (listing_id, new_price),
                )
            elif prev_price is None:
                # Previously had no price; treat as initial observation.
                conn.execute(
                    "INSERT INTO price_history (listing_id, price) VALUES (?, ?)",
                    (listing_id, new_price),
                )

        if listing.image_urls:
            save_listing_image_urls(listing_id, listing.image_urls, conn=conn)

    return listing_id


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


# ---------------------------------------------------------------------------
# Listing images
# ---------------------------------------------------------------------------

def save_listing_image_urls(
    listing_id: int,
    urls: list[str],
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    if not urls:
        return
    def _do(c: sqlite3.Connection) -> None:
        for pos, url in enumerate(urls):
            c.execute(
                """
                INSERT INTO listing_images (listing_id, image_url, position)
                VALUES (?, ?, ?)
                ON CONFLICT(listing_id, image_url) DO NOTHING
                """,
                (listing_id, url, pos),
            )
    if conn is not None:
        _do(conn)
    else:
        with _connect() as c:
            _do(c)


def get_images_needing_download(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, listing_id, image_url, position
            FROM listing_images
            WHERE image_url IS NOT NULL AND image_path IS NULL
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def update_image_path(image_id: int, path: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE listing_images SET image_path = ? WHERE id = ?",
            (path, image_id),
        )


def get_listing_images(listing_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, image_path, position
            FROM listing_images
            WHERE listing_id = ? AND image_path IS NOT NULL
            ORDER BY position
            """,
            (listing_id,),
        ).fetchall()
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Saved searches
# ---------------------------------------------------------------------------

def _saved_search_row_to_dict(row: sqlite3.Row) -> dict:
    out = dict(row)
    raw = out.pop("filters_json", None) or "{}"
    try:
        out["filters"] = json.loads(raw)
    except (TypeError, ValueError):
        out["filters"] = {}
    return out


def list_saved_searches(listing_type: str = "rental") -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, listing_type, filters_json, created_at, last_used_at
            FROM saved_searches
            WHERE listing_type = ?
            ORDER BY COALESCE(last_used_at, created_at) DESC
            """,
            (listing_type,),
        ).fetchall()
        return [_saved_search_row_to_dict(r) for r in rows]


def create_saved_search(name: str, listing_type: str, filters: dict) -> dict:
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO saved_searches (name, listing_type, filters_json)
            VALUES (?, ?, ?)
            """,
            (name.strip(), listing_type, json.dumps(filters or {})),
        )
        new_id = cursor.lastrowid
        row = conn.execute(
            "SELECT * FROM saved_searches WHERE id = ?", (new_id,)
        ).fetchone()
        return _saved_search_row_to_dict(row) if row else {}


def delete_saved_search(saved_search_id: int) -> bool:
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM saved_searches WHERE id = ?", (saved_search_id,)
        )
        return cursor.rowcount > 0


def touch_saved_search(saved_search_id: int) -> dict | None:
    with _connect() as conn:
        conn.execute(
            "UPDATE saved_searches SET last_used_at = datetime('now') WHERE id = ?",
            (saved_search_id,),
        )
        row = conn.execute(
            "SELECT * FROM saved_searches WHERE id = ?", (saved_search_id,)
        ).fetchone()
        return _saved_search_row_to_dict(row) if row else None


# ---------------------------------------------------------------------------
# Trends — snapshot stats, price history, listing volume, price drops
# ---------------------------------------------------------------------------

def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return float((s[mid - 1] + s[mid]) / 2)


def get_trend_summary(listing_type: str = "sale") -> dict:
    with _connect() as conn:
        prices_rows = conn.execute(
            """
            SELECT price FROM listings
            WHERE COALESCE(listing_type, 'rental') = ? AND price IS NOT NULL
            """,
            (listing_type,),
        ).fetchall()
        prices = [r["price"] for r in prices_rows if r["price"] is not None]

        ppsf_rows = conn.execute(
            """
            SELECT price, sqft FROM listings
            WHERE COALESCE(listing_type, 'rental') = ?
              AND price IS NOT NULL AND sqft IS NOT NULL AND sqft > 0
            """,
            (listing_type,),
        ).fetchall()
        ppsf = [r["price"] / r["sqft"] for r in ppsf_rows]

        agg_row = conn.execute(
            """
            SELECT
                COUNT(*)        AS total,
                AVG(price)      AS avg_price,
                MIN(price)      AS min_price,
                MAX(price)      AS max_price,
                AVG(hoa_fee)    AS avg_hoa,
                AVG(tax_annual) AS avg_tax
            FROM listings
            WHERE COALESCE(listing_type, 'rental') = ?
              AND price IS NOT NULL
            """,
            (listing_type,),
        ).fetchone()

        beds_rows = conn.execute(
            """
            SELECT COALESCE(beds, -1) AS beds, COUNT(*) AS n
            FROM listings
            WHERE COALESCE(listing_type, 'rental') = ?
            GROUP BY COALESCE(beds, -1)
            ORDER BY beds
            """,
            (listing_type,),
        ).fetchall()
        beds_breakdown = [
            {"beds": None if r["beds"] == -1 else int(r["beds"]), "count": r["n"]}
            for r in beds_rows
        ]

        ptype_rows = conn.execute(
            """
            SELECT property_type, COUNT(*) AS n
            FROM listings
            WHERE COALESCE(listing_type, 'rental') = ? AND property_type IS NOT NULL
            GROUP BY property_type
            ORDER BY n DESC
            """,
            (listing_type,),
        ).fetchall()
        property_type_breakdown = [
            {"property_type": r["property_type"], "count": r["n"]} for r in ptype_rows
        ]

        distribution: list[dict] = []
        if prices:
            lo = min(prices)
            hi = max(prices)
            if hi == lo:
                distribution = [{"bin_start": lo, "bin_end": hi, "count": len(prices)}]
            else:
                bins = 10
                step = (hi - lo) / bins
                counts = [0] * bins
                for p in prices:
                    idx = int((p - lo) / step)
                    if idx >= bins:
                        idx = bins - 1
                    counts[idx] += 1
                distribution = [
                    {
                        "bin_start": int(lo + i * step),
                        "bin_end": int(lo + (i + 1) * step),
                        "count": counts[i],
                    }
                    for i in range(bins)
                ]

        return {
            "listing_type": listing_type,
            "total": int(agg_row["total"]) if agg_row and agg_row["total"] else 0,
            "avg_price": float(agg_row["avg_price"]) if agg_row and agg_row["avg_price"] is not None else None,
            "median_price": _median(prices),
            "min_price": int(agg_row["min_price"]) if agg_row and agg_row["min_price"] is not None else None,
            "max_price": int(agg_row["max_price"]) if agg_row and agg_row["max_price"] is not None else None,
            "median_price_per_sqft": _median(ppsf),
            "avg_price_per_sqft": (sum(ppsf) / len(ppsf)) if ppsf else None,
            "avg_hoa": float(agg_row["avg_hoa"]) if agg_row and agg_row["avg_hoa"] is not None else None,
            "avg_tax": float(agg_row["avg_tax"]) if agg_row and agg_row["avg_tax"] is not None else None,
            "beds_breakdown": beds_breakdown,
            "property_type_breakdown": property_type_breakdown,
            "price_distribution": distribution,
        }


def get_trend_neighborhoods(listing_type: str = "sale", limit: int = 50) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, neighborhood, price, sqft
            FROM listings
            WHERE COALESCE(listing_type, 'rental') = ?
              AND neighborhood IS NOT NULL
              AND price IS NOT NULL
            """,
            (listing_type,),
        ).fetchall()

    grouped: dict[str, dict] = {}
    for r in rows:
        nb = (r["neighborhood"] or "").strip()
        if not nb:
            continue
        bucket = grouped.setdefault(
            nb,
            {"neighborhood": nb, "prices": [], "ppsf": []},
        )
        bucket["prices"].append(r["price"])
        if r["sqft"] and r["sqft"] > 0:
            bucket["ppsf"].append(r["price"] / r["sqft"])

    results: list[dict] = []
    for nb, bucket in grouped.items():
        prices = bucket["prices"]
        ppsf = bucket["ppsf"]
        results.append({
            "neighborhood": nb,
            "count": len(prices),
            "median_price": _median(prices),
            "avg_price": sum(prices) / len(prices) if prices else None,
            "min_price": min(prices) if prices else None,
            "max_price": max(prices) if prices else None,
            "median_price_per_sqft": _median(ppsf),
        })
    results.sort(key=lambda r: r["count"], reverse=True)
    return results[:limit]


def get_trend_price_history(
    listing_type: str = "sale",
    weeks: int = 12,
    neighborhood: str | None = None,
) -> list[dict]:
    weeks = max(1, min(weeks, 104))
    params: list[object] = [listing_type, f"-{weeks * 7} days"]
    neigh_clause = ""
    if neighborhood:
        neigh_clause = " AND l.neighborhood = ?"
        params.append(neighborhood)

    with _connect() as conn:
        # For each listing, find the most recent price recorded at or before each week
        # boundary. Approximate by averaging all recorded prices that fall inside the week.
        rows = conn.execute(
            f"""
            SELECT
                strftime('%Y-%W', ph.recorded_at) AS week,
                AVG(ph.price)                     AS avg_price,
                COUNT(DISTINCT ph.listing_id)     AS sample_size
            FROM price_history ph
            JOIN listings l ON l.id = ph.listing_id
            WHERE COALESCE(l.listing_type, 'rental') = ?
              AND ph.recorded_at >= datetime('now', ?)
              {neigh_clause}
            GROUP BY week
            ORDER BY week
            """,
            params,
        ).fetchall()
        return [
            {
                "week": r["week"],
                "avg_price": float(r["avg_price"]) if r["avg_price"] is not None else None,
                "sample_size": int(r["sample_size"]),
            }
            for r in rows
        ]


def get_trend_listing_volume(listing_type: str = "sale", weeks: int = 12) -> list[dict]:
    weeks = max(1, min(weeks, 104))
    with _connect() as conn:
        new_rows = conn.execute(
            """
            SELECT
                strftime('%Y-%W', created_at) AS week,
                COUNT(*)                       AS n
            FROM listings
            WHERE COALESCE(listing_type, 'rental') = ?
              AND created_at >= datetime('now', ?)
            GROUP BY week
            ORDER BY week
            """,
            (listing_type, f"-{weeks * 7} days"),
        ).fetchall()
        active_rows = conn.execute(
            """
            SELECT
                strftime('%Y-%W', last_seen_at) AS week,
                COUNT(*)                         AS n
            FROM listings
            WHERE COALESCE(listing_type, 'rental') = ?
              AND last_seen_at IS NOT NULL
              AND last_seen_at >= datetime('now', ?)
            GROUP BY week
            ORDER BY week
            """,
            (listing_type, f"-{weeks * 7} days"),
        ).fetchall()

    by_week: dict[str, dict] = {}
    for r in new_rows:
        by_week.setdefault(r["week"], {"week": r["week"], "new_count": 0, "active_count": 0})
        by_week[r["week"]]["new_count"] = int(r["n"])
    for r in active_rows:
        by_week.setdefault(r["week"], {"week": r["week"], "new_count": 0, "active_count": 0})
        by_week[r["week"]]["active_count"] = int(r["n"])
    return sorted(by_week.values(), key=lambda r: r["week"])


def get_price_drops(listing_type: str = "sale", limit: int = 20) -> list[dict]:
    limit = max(1, min(limit, 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            WITH ranked AS (
                SELECT
                    ph.listing_id,
                    ph.price,
                    ph.recorded_at,
                    ROW_NUMBER() OVER (PARTITION BY ph.listing_id ORDER BY ph.recorded_at DESC) AS rn
                FROM price_history ph
            ),
            latest AS (SELECT listing_id, price AS latest_price, recorded_at AS latest_at FROM ranked WHERE rn = 1),
            prev   AS (SELECT listing_id, price AS prev_price,   recorded_at AS prev_at   FROM ranked WHERE rn = 2)
            SELECT
                l.id, l.url, l.source, l.address, l.neighborhood, l.beds, l.baths,
                l.thumbnail_path,
                latest.latest_price, latest.latest_at,
                prev.prev_price, prev.prev_at
            FROM latest
            JOIN prev ON prev.listing_id = latest.listing_id
            JOIN listings l ON l.id = latest.listing_id
            WHERE COALESCE(l.listing_type, 'rental') = ?
              AND latest.latest_price < prev.prev_price
            ORDER BY latest.latest_at DESC
            LIMIT ?
            """,
            (listing_type, limit),
        ).fetchall()
        return [dict(r) for r in rows]
