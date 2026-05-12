"""NYC borough/neighborhood catalog and per-source search URL builders.

The crawl UI lets users pick a borough (always required) and optionally a
neighborhood within that borough. For each spider we build a search URL that
already bakes in the user's min_beds / min_baths / max_price filters so the
search page only returns relevant results — much more reliable than scraping a
generic "all listings" page and post-filtering in Python.

Each source has its own URL convention:

* Craigslist NYC uses one subdomain (``newyork.craigslist.org``) with subregion
  paths (``mnh``, ``brk``, ``que``, ``brx``, ``stn``). It only filters at
  borough granularity, so neighborhood selections fall back to the borough
  subregion. Filters are query-string (``?min_bedrooms=X&max_price=Y``).
* StreetEasy uses path slugs for both boroughs and neighborhoods
  (``/for-rent/williamsburg``) with pipe-separated path filters
  (``/price:-4000%7Cbeds%3E=2``).
* Zillow uses ``<slug>-new-york-ny/`` (and ``-bronx-ny``, ``-staten-island-ny``)
  with underscore path filters (``/2-_beds/0-4000_price/``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import quote, urlencode

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Borough:
    id: str  # internal id used by the API (snake_case)
    name: str  # display name
    craigslist_subregion: str  # ``mnh``, ``brk``, ...
    streeteasy_slug: str
    zillow_slug: str  # e.g. ``brooklyn-new-york-ny``


@dataclass(frozen=True)
class Neighborhood:
    id: str
    name: str
    borough: str  # Borough.id
    streeteasy_slug: str
    zillow_slug: str


BOROUGHS: tuple[Borough, ...] = (
    Borough(
        id="manhattan",
        name="Manhattan",
        craigslist_subregion="mnh",
        streeteasy_slug="manhattan",
        zillow_slug="manhattan-new-york-ny",
    ),
    Borough(
        id="brooklyn",
        name="Brooklyn",
        craigslist_subregion="brk",
        streeteasy_slug="brooklyn",
        zillow_slug="brooklyn-new-york-ny",
    ),
    Borough(
        id="queens",
        name="Queens",
        craigslist_subregion="que",
        streeteasy_slug="queens",
        zillow_slug="queens-new-york-ny",
    ),
    Borough(
        id="bronx",
        name="Bronx",
        craigslist_subregion="brx",
        streeteasy_slug="bronx",
        zillow_slug="bronx-new-york-ny",
    ),
    Borough(
        id="staten_island",
        name="Staten Island",
        craigslist_subregion="stn",
        streeteasy_slug="staten-island",
        zillow_slug="staten-island-new-york-ny",
    ),
)

BOROUGHS_BY_ID: dict[str, Borough] = {b.id: b for b in BOROUGHS}


def _n(
    name: str,
    borough: str,
    se_slug: str | None = None,
    z_slug: str | None = None,
) -> Neighborhood:
    """Compact constructor — defaults the slug to a kebab-case version of name."""
    base = se_slug or name.lower().replace("'", "").replace(".", "").replace(" ", "-")
    z = z_slug or f"{base}-new-york-ny"
    return Neighborhood(
        id=f"{borough}_{base}".replace("-", "_"),
        name=name,
        borough=borough,
        streeteasy_slug=base,
        zillow_slug=z,
    )


# Common NYC neighborhoods. Not exhaustive — designed to cover the high-traffic
# areas people actually search for. Add more as needed.
NEIGHBORHOODS: tuple[Neighborhood, ...] = (
    # Manhattan
    _n("Upper East Side", "manhattan"),
    _n("Upper West Side", "manhattan"),
    _n("Harlem", "manhattan"),
    _n("East Harlem", "manhattan"),
    _n("Washington Heights", "manhattan"),
    _n("Midtown", "manhattan"),
    _n("Midtown East", "manhattan"),
    _n("Midtown West", "manhattan"),
    _n("Hell's Kitchen", "manhattan", se_slug="hells-kitchen"),
    _n("Chelsea", "manhattan"),
    _n("Gramercy", "manhattan"),
    _n("Murray Hill", "manhattan"),
    _n("Greenwich Village", "manhattan"),
    _n("East Village", "manhattan"),
    _n("West Village", "manhattan"),
    _n("Lower East Side", "manhattan"),
    _n("SoHo", "manhattan", se_slug="soho"),
    _n("NoHo", "manhattan", se_slug="noho"),
    _n("Tribeca", "manhattan"),
    _n("Financial District", "manhattan"),
    _n("Battery Park City", "manhattan"),
    _n("Inwood", "manhattan"),
    # Brooklyn
    _n("Williamsburg", "brooklyn"),
    _n("Greenpoint", "brooklyn"),
    _n("Bushwick", "brooklyn"),
    _n("Bedford-Stuyvesant", "brooklyn", se_slug="bedford-stuyvesant"),
    _n("Crown Heights", "brooklyn"),
    _n("Prospect Heights", "brooklyn"),
    _n("Park Slope", "brooklyn"),
    _n("Fort Greene", "brooklyn"),
    _n("Clinton Hill", "brooklyn"),
    _n("DUMBO", "brooklyn", se_slug="dumbo"),
    _n("Brooklyn Heights", "brooklyn"),
    _n("Cobble Hill", "brooklyn"),
    _n("Carroll Gardens", "brooklyn"),
    _n("Boerum Hill", "brooklyn"),
    _n("Red Hook", "brooklyn"),
    _n("Gowanus", "brooklyn"),
    _n("Sunset Park", "brooklyn"),
    _n("Bay Ridge", "brooklyn"),
    _n("Bensonhurst", "brooklyn"),
    _n("Flatbush", "brooklyn"),
    _n("Ditmas Park", "brooklyn"),
    _n("Windsor Terrace", "brooklyn"),
    # Queens
    _n("Astoria", "queens"),
    _n("Long Island City", "queens"),
    _n("Sunnyside", "queens"),
    _n("Woodside", "queens"),
    _n("Jackson Heights", "queens"),
    _n("Ridgewood", "queens"),
    _n("Forest Hills", "queens"),
    _n("Rego Park", "queens"),
    _n("Flushing", "queens"),
    _n("Elmhurst", "queens"),
    _n("Kew Gardens", "queens"),
    # Bronx
    _n("Riverdale", "bronx"),
    _n("Mott Haven", "bronx"),
    _n("Fordham", "bronx"),
    _n("Concourse", "bronx"),
    _n("Pelham Bay", "bronx"),
    _n("Throgs Neck", "bronx"),
    # Staten Island
    _n("St. George", "staten_island", se_slug="st-george"),
    _n("Stapleton", "staten_island"),
    _n("Tottenville", "staten_island"),
)

NEIGHBORHOODS_BY_ID: dict[str, Neighborhood] = {n.id: n for n in NEIGHBORHOODS}


# ---------------------------------------------------------------------------
# Request types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrawlLocation:
    borough: str  # Borough.id
    neighborhood: str | None = None  # Neighborhood.id, optional

    def resolve(self) -> tuple[Borough, Neighborhood | None]:
        b = BOROUGHS_BY_ID.get(self.borough)
        if b is None:
            raise ValueError(f"Unknown borough: {self.borough!r}")
        if self.neighborhood is None:
            return b, None
        n = NEIGHBORHOODS_BY_ID.get(self.neighborhood)
        if n is None:
            raise ValueError(f"Unknown neighborhood: {self.neighborhood!r}")
        if n.borough != b.id:
            raise ValueError(
                f"Neighborhood {n.id!r} does not belong to borough {b.id!r}",
            )
        return b, n


@dataclass(frozen=True)
class CrawlFilters:
    min_beds: int | None = None
    min_baths: float | None = None
    max_price: int | None = None
    min_price: int | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> "CrawlFilters":
        if not data:
            return cls()
        def _i(v: object) -> int | None:
            if v is None or v == "":
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
        def _f(v: object) -> float | None:
            if v is None or v == "":
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        return cls(
            min_beds=_i(data.get("min_beds")),
            min_baths=_f(data.get("min_baths")),
            max_price=_i(data.get("max_price")),
            min_price=_i(data.get("min_price")),
        )


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------


def build_craigslist_url(
    borough: Borough,
    listing_type: str,
    filters: CrawlFilters,
) -> str:
    section = "rea" if listing_type == "sale" else "apa"
    base = f"https://newyork.craigslist.org/search/{borough.craigslist_subregion}/{section}"
    params: list[tuple[str, str]] = []
    if filters.min_beds is not None:
        params.append(("min_bedrooms", str(filters.min_beds)))
    if filters.min_baths is not None:
        # Craigslist takes an integer here.
        params.append(("min_bathrooms", str(int(filters.min_baths))))
    if filters.max_price is not None:
        params.append(("max_price", str(filters.max_price)))
    if filters.min_price is not None:
        params.append(("min_price", str(filters.min_price)))
    # Always order by newest so the integration test sees fresh listings.
    params.append(("sort", "date"))
    return f"{base}?{urlencode(params)}" if params else base


def build_streeteasy_url(
    borough: Borough,
    neighborhood: Neighborhood | None,
    listing_type: str,
    filters: CrawlFilters,
) -> str:
    section = "for-sale" if listing_type == "sale" else "for-rent"
    slug = neighborhood.streeteasy_slug if neighborhood else borough.streeteasy_slug
    base = f"https://streeteasy.com/{section}/{slug}"

    # StreetEasy expects pipe-separated path filters: ``/price:-4000|beds>=2``.
    parts: list[str] = []
    if filters.max_price is not None or filters.min_price is not None:
        lo = filters.min_price or 0
        hi = filters.max_price or ""
        parts.append(f"price:{lo}-{hi}")
    if filters.min_beds is not None:
        parts.append(f"beds>={filters.min_beds}")
    if filters.min_baths is not None:
        # StreetEasy supports fractional baths in some places, but ">=N" is the
        # safer form.
        parts.append(f"baths>={int(filters.min_baths)}")
    if not parts:
        return base
    filter_segment = quote("|".join(parts), safe=":")
    return f"{base}/{filter_segment}"


def build_zillow_url(
    borough: Borough,
    neighborhood: Neighborhood | None,
    listing_type: str,
    filters: CrawlFilters,
) -> str:
    slug = neighborhood.zillow_slug if neighborhood else borough.zillow_slug
    base = f"https://www.zillow.com/{slug}"
    parts: list[str] = []
    if listing_type == "sale":
        # The default Zillow city page is sales, so no extra path needed.
        pass
    else:
        parts.append("rentals")
    if filters.min_beds is not None:
        parts.append(f"{filters.min_beds}-_beds")
    if filters.max_price is not None or filters.min_price is not None:
        lo = filters.min_price or 0
        hi = filters.max_price or ""
        parts.append(f"{lo}-{hi}_price")
    if filters.min_baths is not None:
        parts.append(f"{int(filters.min_baths)}-_baths")
    if not parts:
        return f"{base}/"
    return f"{base}/" + "/".join(parts) + "/"


def build_start_urls(
    location: CrawlLocation,
    listing_type: str,
    filters: CrawlFilters,
    spiders: Iterable[str] | None = None,
) -> dict[str, list[str]]:
    """Return ``{spider_name: [search_url, ...]}`` for the given crawl.

    ``spiders`` filters the returned keys so we only build URLs for sources the
    user actually selected. ``None`` returns all three.
    """
    borough, neighborhood = location.resolve()
    requested = set(spiders) if spiders is not None else {"craigslist", "streeteasy", "zillow"}
    out: dict[str, list[str]] = {}
    if "craigslist" in requested:
        out["craigslist"] = [build_craigslist_url(borough, listing_type, filters)]
    if "streeteasy" in requested:
        # StreetEasy is NYC-only; since every CrawlLocation is NYC the check is
        # trivially true, but we keep the structure explicit so it's easy to
        # extend later.
        out["streeteasy"] = [build_streeteasy_url(borough, neighborhood, listing_type, filters)]
    if "zillow" in requested:
        out["zillow"] = [build_zillow_url(borough, neighborhood, listing_type, filters)]
    return out


# ---------------------------------------------------------------------------
# Serialization helpers (used by /api/locations)
# ---------------------------------------------------------------------------


def borough_to_dict(b: Borough) -> dict:
    return {"id": b.id, "name": b.name}


def neighborhood_to_dict(n: Neighborhood) -> dict:
    return {"id": n.id, "name": n.name, "borough": n.borough}


def all_locations() -> dict:
    return {
        "boroughs": [borough_to_dict(b) for b in BOROUGHS],
        "neighborhoods": [neighborhood_to_dict(n) for n in NEIGHBORHOODS],
    }
