"""Live integration tests for each spider.

These tests hit the real Zillow / StreetEasy / Craigslist sites with a small,
forgiving set of filters and assert at least one listing was extracted into a
*temporary* SQLite DB. They double as the smoke test the agent runs after
making scraper changes — see ``AGENTS.md``.

Run them explicitly:

    uv run pytest -m live -s tests/test_scrapers_live.py

They are NOT run by ``make test`` (the default ``addopts`` in ``pyproject.toml``
excludes the ``live`` marker) because:

* They take ~30s+ each (real network + Playwright cold start).
* They may flake when an upstream site is down or aggressively blocking us.

Each test passes if the spider extracts >=1 listing for the targeted source.
A single failing source does not block the others; pytest reports each
independently via parametrization.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from config import Settings
from nyc_locations import CrawlFilters, CrawlLocation, build_start_urls

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the global SQLite DB to a temp path and initialize the schema.

    Spiders call ``db.upsert_listing`` which uses ``db.DB_PATH`` at call time,
    so monkeypatching the module attribute is sufficient.
    """
    import db as db_module

    db_path = tmp_path / "test_rent_lobster.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_path


@pytest.fixture()
def fast_settings() -> Settings:
    """Settings with zero-delay, headless, no proxies — built for speed."""
    s = Settings()
    return dataclasses.replace(
        s,
        headless=True,
        spider_min_delay=0.0,
        spider_max_delay=0.0,
        respect_robots=False,
        # Forgiving filters so the search page actually returns something.
        min_beds=1,
        min_baths=1,
        max_rent=20_000,
        sale_min_beds=1,
        sale_min_baths=1,
        max_sale_price=10_000_000,
        proxy_urls=tuple(),
    )


def _crawlee_config(storage_dir: Path):
    from crawlee.configuration import Configuration as CrawleeConfiguration

    return CrawleeConfiguration(
        storage_dir=str(storage_dir),
        purge_on_start=True,
    )


def _count_listings(db_path: Path, source: str) -> int:
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE source = ?", (source,)
        )
        return int(cur.fetchone()[0])


def _sample_listings(db_path: Path, source: str, n: int = 3) -> list[dict]:
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT url, price, beds, baths, address, neighborhood "
            "FROM listings WHERE source = ? LIMIT ?",
            (source, n),
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Per-spider runners
# ---------------------------------------------------------------------------


async def _run_craigslist(
    url: str, settings: Settings, storage_dir: Path, max_pages: int,
) -> None:
    from urllib.parse import urlparse

    from crawlee import Request as CrawleeRequest

    from spiders.craigslist import build_craigslist_crawler

    crawler = build_craigslist_crawler(
        settings,
        max_pages=max_pages,
        configuration=_crawlee_config(storage_dir),
        listing_type="rental",
    )
    requests = [
        CrawleeRequest(
            url=url,
            unique_key=url,
            user_data={"seed_host": urlparse(url).netloc},
        )
    ]
    await crawler.run(requests)


async def _run_streeteasy(
    url: str, settings: Settings, storage_dir: Path, max_pages: int,
) -> None:
    from crawlee import Request as CrawleeRequest

    from spiders.streeteasy import build_streeteasy_crawler

    crawler = build_streeteasy_crawler(
        settings,
        max_pages=max_pages,
        configuration=_crawlee_config(storage_dir),
        listing_type="rental",
    )
    await crawler.run([CrawleeRequest(url=url, unique_key=url)])


async def _run_zillow(
    url: str, settings: Settings, storage_dir: Path, max_pages: int,
) -> None:
    from crawlee import Request as CrawleeRequest

    from spiders.zillow import build_zillow_crawler

    crawler = build_zillow_crawler(
        settings,
        max_pages=max_pages,
        configuration=_crawlee_config(storage_dir),
        listing_type="rental",
    )
    await crawler.run([CrawleeRequest(url=url, unique_key=url)])


SPIDER_RUNNERS: dict[str, Callable[..., object]] = {
    "craigslist": _run_craigslist,
    "streeteasy": _run_streeteasy,
    "zillow": _run_zillow,
}


# ---------------------------------------------------------------------------
# The actual test
# ---------------------------------------------------------------------------

LOCATION = CrawlLocation(borough="brooklyn")
FILTERS = CrawlFilters(min_beds=1, max_price=10_000)
START_URLS = build_start_urls(LOCATION, listing_type="rental", filters=FILTERS)


@pytest.mark.live
@pytest.mark.parametrize("spider_name", ["craigslist", "streeteasy", "zillow"])
def test_spider_returns_at_least_one_listing(
    spider_name: str,
    temp_db: Path,
    fast_settings: Settings,
    tmp_path: Path,
):
    url = START_URLS[spider_name][0]
    storage_dir = tmp_path / f"crawlee_{spider_name}"
    runner = SPIDER_RUNNERS[spider_name]

    log.info("=== Running %s against %s ===", spider_name, url)
    asyncio.run(runner(url, fast_settings, storage_dir, 8))

    found = _count_listings(temp_db, spider_name)
    log.info("[%s] extracted %d listings into the DB", spider_name, found)
    for row in _sample_listings(temp_db, spider_name):
        log.info("  - %s", row)

    assert found >= 1, (
        f"{spider_name} extracted 0 listings from {url}. "
        f"This usually means the site changed its HTML, the URL format "
        f"changed, or the spider is being blocked. See logs above for "
        f"the page title / status / first-pass body preview."
    )
