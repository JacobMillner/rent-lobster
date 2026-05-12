"""Unit tests for the NYC location catalog + URL builders.

These do not touch the network and run as part of the default ``make test``.
The live spider integration tests live in ``test_scrapers_live.py``.
"""

from __future__ import annotations

import pytest

from nyc_locations import (
    BOROUGHS_BY_ID,
    NEIGHBORHOODS_BY_ID,
    CrawlFilters,
    CrawlLocation,
    all_locations,
    build_start_urls,
)


def test_all_boroughs_have_distinct_slugs():
    cl = {b.craigslist_subregion for b in BOROUGHS_BY_ID.values()}
    se = {b.streeteasy_slug for b in BOROUGHS_BY_ID.values()}
    z = {b.zillow_slug for b in BOROUGHS_BY_ID.values()}
    assert len(cl) == len(BOROUGHS_BY_ID)
    assert len(se) == len(BOROUGHS_BY_ID)
    assert len(z) == len(BOROUGHS_BY_ID)


def test_neighborhoods_all_belong_to_a_borough():
    for n in NEIGHBORHOODS_BY_ID.values():
        assert n.borough in BOROUGHS_BY_ID


def test_build_start_urls_brooklyn_rental_with_filters():
    loc = CrawlLocation(borough="brooklyn")
    f = CrawlFilters(min_beds=2, max_price=4000)
    urls = build_start_urls(loc, listing_type="rental", filters=f)
    assert "craigslist" in urls and urls["craigslist"]
    assert "streeteasy" in urls and urls["streeteasy"]
    assert "zillow" in urls and urls["zillow"]

    cl = urls["craigslist"][0]
    assert "newyork.craigslist.org/search/brk/apa" in cl
    assert "min_bedrooms=2" in cl
    assert "max_price=4000" in cl

    se = urls["streeteasy"][0]
    assert "streeteasy.com/for-rent/brooklyn" in se
    assert "price%3A0-4000" in se or "price:0-4000" in se
    assert "beds%3E%3D2" in se or "beds>=2" in se

    z = urls["zillow"][0]
    assert "zillow.com/brooklyn-new-york-ny/rentals/" in z
    assert "2-_beds" in z
    assert "0-4000_price" in z


def test_build_start_urls_sale_uses_sale_paths():
    loc = CrawlLocation(borough="manhattan", neighborhood="manhattan_chelsea")
    f = CrawlFilters(min_beds=2, max_price=1_500_000)
    urls = build_start_urls(loc, listing_type="sale", filters=f)

    assert "newyork.craigslist.org/search/mnh/rea" in urls["craigslist"][0]
    assert "streeteasy.com/for-sale/chelsea" in urls["streeteasy"][0]
    # Zillow sale URL omits the /rentals/ segment.
    assert "zillow.com/chelsea-new-york-ny/" in urls["zillow"][0]
    assert "/rentals/" not in urls["zillow"][0]


def test_build_start_urls_unknown_borough_raises():
    with pytest.raises(ValueError):
        build_start_urls(
            CrawlLocation(borough="atlantis"),
            listing_type="rental",
            filters=CrawlFilters(),
        )


def test_build_start_urls_mismatched_neighborhood_raises():
    # Manhattan neighborhood with brooklyn borough should fail.
    chelsea_id = "manhattan_chelsea"
    assert chelsea_id in NEIGHBORHOODS_BY_ID
    with pytest.raises(ValueError):
        build_start_urls(
            CrawlLocation(borough="brooklyn", neighborhood=chelsea_id),
            listing_type="rental",
            filters=CrawlFilters(),
        )


def test_build_start_urls_can_filter_by_spider():
    loc = CrawlLocation(borough="brooklyn")
    urls = build_start_urls(
        loc,
        listing_type="rental",
        filters=CrawlFilters(),
        spiders=["zillow"],
    )
    assert set(urls.keys()) == {"zillow"}


def test_all_locations_returns_serializable_dicts():
    data = all_locations()
    assert {b["id"] for b in data["boroughs"]} == set(BOROUGHS_BY_ID.keys())
    assert len(data["neighborhoods"]) == len(NEIGHBORHOODS_BY_ID)


def test_crawl_filters_from_dict_handles_strings_and_empty():
    f = CrawlFilters.from_dict({"min_beds": "2", "max_price": "", "min_baths": None})
    assert f.min_beds == 2
    assert f.max_price is None
    assert f.min_baths is None
