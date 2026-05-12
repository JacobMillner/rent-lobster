# AGENTS.md

Guidance for AI coding agents working on this repo. Humans are welcome to
follow it too.

## Layout cheat sheet

- `spiders/` — one Playwright crawler per source (Zillow, StreetEasy,
  Craigslist) plus shared parsing helpers in `_common.py` and stealth bits in
  `_stealth.py`.
- `nyc_locations.py` — NYC borough/neighborhood catalog and the URL builders
  that bake user-supplied filters (min_beds / min_baths / max_price) into the
  search URLs each spider starts from.
- `worker.py` — `CrawlManager` runs spiders against the URLs returned by
  `build_start_urls(...)`; also hosts the thumbnail/image/geocoding workers.
- `server.py` — FastAPI surface. Crawl endpoint: `POST /api/crawl`. Location
  catalog endpoint: `GET /api/locations`.
- `frontend/src/components/ListingFinder.tsx` — the UI that posts to
  `/api/crawl` with `{spiders, max_pages, listing_type, location, filters}`.
- `tests/test_scrapers_live.py` — live integration test; the source of truth
  for "are the spiders working right now".

## Required workflow after scraper changes

After touching any of:

- `spiders/**`
- `nyc_locations.py`
- `worker.py`

run the live scraper test and ensure each parametrized case passes:

```bash
make test-scrapers
```

This actually hits Zillow / StreetEasy / Craigslist over the network, runs
each spider for a few pages against a Brooklyn / rentals search URL, and
asserts the spider extracted at least one listing into a temp SQLite DB.

If a spider returns zero listings, iterate on it (selectors, stealth, URL
shape) until the test passes. Don't ship "fixes" that haven't been verified by
this test — the whole point of the test is that listing sites change their
HTML frequently and silent regressions are the default failure mode.

If one source is genuinely down for reasons outside this repo (e.g. the site
is returning 5xx, the URL convention changed *and* you've done the diligence
to confirm the new shape) leave the other sources green and note the failure
in your PR description.

## Default fast tests

Everything else — config loading, URL builder unit tests, model parsing —
runs in `make test` and must stay green on every change:

```bash
make test
```

The `live` marker is excluded from `make test` via `addopts` in
`pyproject.toml`. Only `make test-scrapers` opts in.

## Other useful commands

- `make lint` — ruff check
- `make fmt` — ruff format
- `make typecheck` — mypy
- `make check` — lint + typecheck + (fast) tests
- `make server` — build the frontend bundle and serve everything from FastAPI
  on http://localhost:7777
- `cd frontend && npm run dev` — Next.js dev server with HMR; pair with
  `make server` in another terminal for the API.

## Frontend conventions

The crawl panel always sends a `location` object (`{borough, neighborhood?}`)
and a `filters` object (`{min_beds, min_baths, max_price}`). The backend
*requires* `location.borough` — if you add new entry points to crawling, keep
that contract so the URL builder stays the single source of truth for
"what URL do we ask each site for".

## When in doubt

Run `make test-scrapers` first, then `make test`, then `make lint`. If all
three are green, your change is probably fine.
