from __future__ import annotations

import asyncio

from apt_scout.config import Settings
from apt_scout.spiders.zillow import build_zillow_crawler
from apt_scout.spiders.streeteasy import build_streeteasy_crawler

async def main() -> None:
    settings = Settings()

    if settings.zillow_start_urls:
        z = build_zillow_crawler(settings)
        await z.run(list(settings.zillow_start_urls))

    if settings.streeteasy_start_urls:
        s = build_streeteasy_crawler(settings)
        await s.run(list(settings.streeteasy_start_urls))

if __name__ == "__main__":
    asyncio.run(main())