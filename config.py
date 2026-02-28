from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}

def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None else int(raw)

def _get_str(name: str, default: str = "") -> str:
    raw = os.getenv(name)
    return default if raw is None else raw

def _get_urls(name: str) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    # comma or newline separated
    parts = [p.strip() for p in raw.replace("\n", ",").split(",")]
    return [p for p in parts if p]

@dataclass(frozen=True)
class Settings:
    headless: bool = _get_bool("HEADLESS", True)
    max_requests: int = _get_int("MAX_REQUESTS", 50)
    concurrency: int = _get_int("CONCURRENCY", 3)
    respect_robots: bool = _get_bool("RESPECT_ROBOTS", True)

    min_beds: int = _get_int("MIN_BEDS", 3)
    min_baths: int = _get_int("MIN_BATHS", 1)
    max_rent: int = _get_int("MAX_RENT", 6000)

    zillow_start_urls: list[str] = tuple(_get_urls("ZILLOW_START_URLS"))  # type: ignore
    streeteasy_start_urls: list[str] = tuple(_get_urls("STREETEASY_START_URLS"))  # type: ignore

    discord_webhook_url: str = _get_str("DISCORD_WEBHOOK_URL")