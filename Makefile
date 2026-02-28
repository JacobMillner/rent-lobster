SHELL := /usr/bin/env bash
PROJECT := apt-scout

# If you want to pin python:
PYTHON_VERSION ?= 3.12

# Where uv's installer puts the binary by default on Linux
UV_BIN ?= $(HOME)/.local/bin/uv

.PHONY: help install uv sync playwright run test lint fmt typecheck check clean

help:
	@echo "Targets:"
	@echo "  make install    - install uv (if needed), sync deps, install playwright browser"
	@echo "  make run        - run crawler"
	@echo "  make check      - lint + typecheck + tests"
	@echo "  make clean      - remove caches and venv"

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
	@# Ensure a venv exists and deps are installed
	uv sync

playwright: sync
	uv run playwright install chromium

install: playwright
	@echo "Installed. Use: make run"

run: sync
	uv run python run.py

test: sync
	uv run pytest -q

lint: sync
	uv run ruff check .

fmt: sync
	uv run ruff format .

typecheck: sync
	uv run mypy src

check: lint typecheck test

clean:
	rm -rf .venv .pytest_cache .ruff_cache .mypy_cache dist build