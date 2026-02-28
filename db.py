from __future__ import annotations

import sqlite3
from pathlib import Path
from models import Listing

DB_PATH = Path(__file__).resolve().parent / "rent_lobster.db"

_DDL = """
CREATE TABLE IF NOT EXISTS listings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT    NOT NULL,
    url         TEXT    NOT NULL UNIQUE,
    price       INTEGER,
    beds        INTEGER,
    baths       REAL,
    address     TEXT,
    neighborhood TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_DDL)


def upsert_listing(listing: Listing) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO listings (source, url, price, beds, baths, address, neighborhood)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                price        = excluded.price,
                beds         = excluded.beds,
                baths        = excluded.baths,
                address      = excluded.address,
                neighborhood = excluded.neighborhood
            """,
            (
                listing.source,
                str(listing.url),
                listing.price,
                listing.beds,
                listing.baths,
                listing.address,
                listing.neighborhood,
            ),
        )


def get_all_listings(
    source: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    min_beds: int | None = None,
) -> list[dict]:
    clauses: list[str] = []
    params: list[object] = []

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

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM listings{where} ORDER BY created_at DESC"

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


def get_sources() -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT source FROM listings ORDER BY source"
        ).fetchall()
        return [row["source"] for row in rows]


def get_stats() -> dict:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*)           AS total,
                COUNT(DISTINCT source) AS sources,
                AVG(price)         AS avg_price,
                MIN(price)         AS min_price,
                MAX(price)         AS max_price
            FROM listings
            WHERE price IS NOT NULL
            """
        ).fetchone()
        return dict(row) if row else {}
