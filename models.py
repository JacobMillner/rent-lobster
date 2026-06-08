from __future__ import annotations

import re
from pydantic import BaseModel, HttpUrl


class Listing(BaseModel):
    source: str
    url: HttpUrl
    listing_type: str = "rental"
    price: int | None = None
    beds: int | None = None
    baths: float | None = None
    address: str | None = None
    neighborhood: str | None = None
    thumbnail_url: str | None = None
    image_urls: list[str] = []
    sqft: int | None = None
    description: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    subway_minutes: int | None = None
    nearest_subway: str | None = None
    has_dishwasher: bool | None = None
    has_balcony: bool | None = None
    laundry: str | None = None
    has_doorman: bool | None = None
    has_elevator: bool | None = None
    has_gym: bool | None = None
    pets_allowed: bool | None = None
    no_fee: bool | None = None
    available_date: str | None = None
    floor: str | None = None
    date_listed: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    hoa_fee: int | None = None
    year_built: int | None = None
    property_type: str | None = None
    tax_annual: int | None = None

    def matches(
        self,
        *,
        min_beds: int,
        min_baths: int,
        max_price: int,
        min_price: int = 0,
    ) -> bool:
        if self.price is not None and self.price > max_price:
            return False
        # A `min_price` floor is what keeps rent-priced listings from polluting
        # sale results: rental search pages on Zillow/StreetEasy occasionally
        # link out to a $3,500/mo card from a sale results page, and without
        # this guard those would be saved as if they were sale listings.
        if min_price > 0 and self.price is not None and self.price < min_price:
            return False
        if self.beds is not None and self.beds < min_beds:
            return False
        if self.baths is not None and self.baths < float(min_baths):
            return False
        return True


_SQFT_RE = re.compile(r"(\d[\d,]*)\s*(?:sq\.?\s*ft|sqft|sf)\b", re.IGNORECASE)
_SUBWAY_RE = re.compile(
    r"(\d+)\s*(?:min(?:ute)?s?\s*(?:walk|to)\s*(?:the\s*)?)?(?:to\s+)?(?:subway|train|metro|station|(?:[A-Z0-9/]+)\s+(?:train|line))",
    re.IGNORECASE,
)
_SUBWAY_STATION_RE = re.compile(
    r"(?:near|close to|steps? (?:from|to)|blocks? (?:from|to))\s+(.+?(?:station|stop|subway|train))",
    re.IGNORECASE,
)
_AVAIL_RE = re.compile(
    r"(?:available|move[- ]?in|starting)\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+ \d{1,2},?\s*\d{4}|immediately|now|asap)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
_FLOOR_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\s+floor\b", re.IGNORECASE)
_HOA_RE = re.compile(r"(?:hoa|maintenance|common charges?)[:\s]*\$?([\d,]+)(?:\s*/\s*mo)?", re.IGNORECASE)
_YEAR_BUILT_RE = re.compile(r"(?:built|year built|constructed)[:\s]*(\d{4})", re.IGNORECASE)
_TAX_RE = re.compile(r"(?:annual tax|property tax|taxes?)[:\s]*\$?([\d,]+)(?:\s*/\s*yr)?", re.IGNORECASE)
_PROPERTY_TYPE_MAP = [
    ("condo", "condo"),
    ("co-op", "co-op"),
    ("coop", "co-op"),
    ("townhouse", "townhouse"),
    ("single family", "single_family"),
    ("multi-family", "multi_family"),
]


def scan_amenities(text: str) -> dict:
    """Scan listing text for common apartment amenities and return a dict of detected values."""
    lower = text.lower()
    result: dict = {}

    if "dishwasher" in lower:
        result["has_dishwasher"] = True
    if any(w in lower for w in ("balcony", "terrace", "patio", "private deck", "outdoor space")):
        result["has_balcony"] = True

    if any(w in lower for w in ("washer/dryer in unit", "in-unit laundry", "w/d in unit",
                                 "washer and dryer in unit", "in unit washer", "in-unit w/d")):
        result["laundry"] = "in_unit"
    elif any(w in lower for w in ("laundry in building", "laundry room", "shared laundry",
                                   "laundry in bldg", "common laundry")):
        result["laundry"] = "in_building"

    if "doorman" in lower or "door man" in lower:
        result["has_doorman"] = True
    if "elevator" in lower:
        result["has_elevator"] = True
    if any(w in lower for w in ("gym", "fitness center", "fitness room", "exercise room")):
        result["has_gym"] = True
    if any(w in lower for w in ("pets ok", "pet friendly", "dogs ok", "cats ok",
                                 "pets allowed", "pet-friendly", "dogs allowed", "cats allowed")):
        result["pets_allowed"] = True
    if "no fee" in lower or "no broker fee" in lower or "no-fee" in lower:
        result["no_fee"] = True

    m = _SQFT_RE.search(text)
    if m:
        try:
            result["sqft"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass

    m = _SUBWAY_RE.search(text)
    if m:
        try:
            result["subway_minutes"] = int(m.group(1))
        except ValueError:
            pass

    m = _SUBWAY_STATION_RE.search(text)
    if m:
        result["nearest_subway"] = m.group(1).strip().rstrip(".")

    m = _AVAIL_RE.search(text)
    if m:
        result["available_date"] = m.group(1).strip()

    m = _FLOOR_RE.search(text)
    if m:
        result["floor"] = m.group(0)

    m = _EMAIL_RE.search(text)
    if m:
        result["contact_email"] = m.group(0)

    m = _PHONE_RE.search(text)
    if m:
        result["contact_phone"] = m.group(0)

    m = _HOA_RE.search(text)
    if m:
        try:
            result["hoa_fee"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass

    m = _YEAR_BUILT_RE.search(text)
    if m:
        try:
            year = int(m.group(1))
            if 1800 <= year <= 2100:
                result["year_built"] = year
        except ValueError:
            pass

    m = _TAX_RE.search(text)
    if m:
        try:
            result["tax_annual"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass

    for label, value in _PROPERTY_TYPE_MAP:
        if label in lower:
            result["property_type"] = value
            break

    return result