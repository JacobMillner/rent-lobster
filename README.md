# rent-lobster

Open-claw apartment finder. Crawls rental and for-sale listings from Zillow,
StreetEasy, and Craigslist and serves them through a FastAPI backend with a
Next.js frontend (map view, filters, favorites, thumbnails).

## Requirements

- Python 3.12+
- Node.js 18+ (for the frontend build)
- [`uv`](https://docs.astral.sh/uv/) — the Makefile will bootstrap it
  automatically if it's missing
- Linux/macOS recommended (Playwright + proxy-py)

## Setup

Clone the repo, then from the project root:

```bash
cp .env.example .env
# edit .env to add at least one of the *_START_URLS

make install
```

`make install` will:

1. Install `uv` if it isn't already on your PATH.
2. Run `uv sync` to create `.venv/` and install Python dependencies from
   `pyproject.toml` / `uv.lock`.
3. Install Playwright browsers (Chromium + Firefox) with system deps.
4. Run `npm install` in `frontend/`.

### Configuration

All configuration lives in `.env`. Highlights:

- `ZILLOW_START_URLS`, `STREETEASY_START_URLS`, `CRAIGSLIST_START_URLS` —
  comma- or newline-separated seed URLs for the rental crawlers. Their `_SALE_`
  counterparts seed the for-sale crawlers.
- `MIN_BEDS`, `MIN_BATHS`, `MAX_RENT` — filters applied to rental listings.
- `SALE_MIN_BEDS`, `SALE_MIN_BATHS`, `MAX_SALE_PRICE` — filters for sale listings.
- `HEADLESS`, `MAX_REQUESTS`, `CONCURRENCY`, `RESPECT_ROBOTS` — crawl behavior.
- `PROXY_COUNT` — number of local rotating proxies to auto-start
  (set to `0` to disable). Override with comma-separated `PROXY_URLS` to use
  external proxies instead.
- `DISCORD_WEBHOOK_URL` — optional, posts alerts when new listings appear.

Only crawl URLs you're allowed to crawl.

## Running

### Web app (recommended)

Builds the frontend and starts the FastAPI server on
[http://localhost:7777](http://localhost:7777):

```bash
make server
```

From the UI you can browse listings, view them on the map, mark favorites, and
trigger crawls per-source.

### One-shot crawler

Runs the crawlers configured in `.env` and prints results to stdout:

```bash
make run
```

This populates `rent_lobster.db` (SQLite) the same way the server does, so you
can `make server` afterward to browse the results.

### Frontend dev server

If you're iterating on the UI, run Next.js directly so you get HMR:

```bash
cd frontend
npm run dev
```

Point it at the API by running `make server` (or `uv run uvicorn server:app
--port 7777`) in another terminal.

## Development

```bash
make lint        # ruff check
make fmt         # ruff format
make typecheck   # mypy
make test        # pytest
make check       # lint + typecheck + test
```

## Cleanup

```bash
make clean
```

Removes `.venv/`, caches, the frontend build/`node_modules`, and the local
`rent_lobster.db`.
