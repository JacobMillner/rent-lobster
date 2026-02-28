from urllib.parse import urlparse
from crawlee import Request

import asyncio

from config import Settings
from db import init_db
from spiders.zillow import build_zillow_crawler
from spiders.streeteasy import build_streeteasy_crawler
from spiders.craigslist import build_craigslist_crawler


async def main() -> None:
    init_db()
    settings = Settings()

    if settings.zillow_start_urls:
        z = build_zillow_crawler(settings)
        await z.run(list(settings.zillow_start_urls))
        zillow_items = await z.get_data()
        print(f"\n=== Zillow Results ({len(zillow_items.items)} listings) ===")
        for item in zillow_items.items:
            print(f"  {item}")

    if settings.streeteasy_start_urls:
        s = build_streeteasy_crawler(settings)
        await s.run(list(settings.streeteasy_start_urls))
        streeteasy_items = await s.get_data()
        print(f"\n=== StreetEasy Results ({len(streeteasy_items.items)} listings) ===")
        for item in streeteasy_items.items:
            print(f"  {item}")

    if settings.craigslist_start_urls:
        c = build_craigslist_crawler(settings)
        requests = [
            Request(url=u, unique_key=u, user_data={"seed_host": urlparse(u).netloc})
            for u in settings.craigslist_start_urls
        ]
        await c.run(requests)


if __name__ == "__main__":
    asyncio.run(main())
