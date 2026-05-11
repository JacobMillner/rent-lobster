"""Shared parsing helpers and constants used by all spiders.

Each spider used to define its own near-identical price/bed/bath regexes and
block-detection logic. They live here so behavior stays consistent and there is
only one place to fix things when sites change.
"""

from __future__ import annotations

import re

_PRICE_RE = re.compile(r"\$([\d,]+)")
_BED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:bed|bd|br)\b", re.IGNORECASE)
_BATH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:bath|ba)\b", re.IGNORECASE)

_BLOCKED_KEYWORDS = (
    "access denied",
    "blocked",
    "captcha",
    "just a moment",
    "robot",
    "denied",
)


def parse_int_price(text: str | None) -> int | None:
    """Extract the first dollar-amount integer from ``text`` (e.g. ``$3,250`` -> 3250)."""
    if not text:
        return None
    m = _PRICE_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_beds_baths(text: str | None) -> tuple[int | None, float | None]:
    """Return ``(beds, baths)`` parsed from a free-text string. Either may be ``None``."""
    if not text:
        return None, None

    beds: int | None = None
    baths: float | None = None

    m_bed = _BED_RE.search(text)
    if m_bed:
        try:
            beds = int(float(m_bed.group(1)))
        except ValueError:
            pass

    m_bath = _BATH_RE.search(text)
    if m_bath:
        try:
            baths = float(m_bath.group(1))
        except ValueError:
            pass

    return beds, baths


def is_blocked_title(title: str | None) -> bool:
    """True when a page title contains any of the well-known anti-bot markers."""
    if not title:
        return False
    lower = title.lower()
    return any(kw in lower for kw in _BLOCKED_KEYWORDS)
