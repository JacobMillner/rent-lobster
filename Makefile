SHELL := /usr/bin/env bash
PROJECT := rent-lobster

PYTHON_VERSION ?= 3.12
UV_BIN ?= $(HOME)/.local/bin/uv
FRONTEND_DIR := frontend
STATIC_OUT := $(FRONTEND_DIR)/out

.PHONY: help install uv sync playwright install-browsers run test test-scrapers lint fmt typecheck check clean \
        frontend frontend-install server

help:
	@echo "Targets:"
	@echo "  make install    - install all deps (python + playwright + frontend)"
	@echo "  make run        - run crawler"
	@echo "  make server     - build frontend & start FastAPI server"
	@echo "  make check      - lint + typecheck + tests"
	@echo "  make clean      - remove caches, venv, and frontend build"

# ---- Bootstrap uv if missing ----
uv:
	@if command -v uv >/dev/null 2>&1; then \
		echo "uv already installed: $$(command -v uv)"; \
	elif [ -x "$(UV_BIN)" ]; then \
		echo "uv found at $(UV_BIN)"; \
	else \
		echo "Installing uv..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	fi

# ---- Create venv + install deps from pyproject + uv.lock ----
sync: uv
	uv sync

playwright: sync
	uv run playwright install chromium

install-browsers: sync
	uv run playwright install --with-deps chromium firefox

# ---- Frontend ----
frontend-install:
	@if ! command -v node >/dev/null 2>&1; then \
		echo "ERROR: Node.js is required. Install it from https://nodejs.org"; \
		exit 1; \
	fi
	cd $(FRONTEND_DIR) && npm install

frontend: frontend-install
	cd $(FRONTEND_DIR) && npm run build

# ---- Top-level install ----
install: install-browsers frontend-install
	@echo "Installed. Use: make run / make server"

# ---- Run crawler ----
run: sync
	uv run python run.py

# ---- Serve (build frontend, then start FastAPI) ----
server: sync frontend
	uv run uvicorn server:app --host 0.0.0.0 --port 7777

# ---- QA ----
test: sync
	uv run pytest -q

# Live, opt-in integration tests that drive each spider against the real site.
# See AGENTS.md — run this after touching anything under spiders/, worker.py,
# or nyc_locations.py.
test-scrapers: sync
	uv run pytest -m live -s tests/test_scrapers_live.py

lint: sync
	uv run ruff check .

fmt: sync
	uv run ruff format .

typecheck: sync
	uv run mypy src

check: lint typecheck test

clean:
	rm -rf .venv .pytest_cache .ruff_cache .mypy_cache dist build
	rm -rf $(FRONTEND_DIR)/node_modules $(FRONTEND_DIR)/.next $(STATIC_OUT)
	rm -f rent_lobster.db
