.PHONY: install test lint web-install web-check desktop-dev desktop-dist jetson-export

install:
	uv sync --all-groups

test:
	uv run pytest

lint:
	uv run ruff check sat_simulation tests
	uv run ruff format --check sat_simulation tests

web-install:
	cd web && pnpm install

web-check:
	cd web && pnpm typecheck && pnpm build

desktop-dev:
	cd web && pnpm desktop:dev

desktop-dist:
	cd web && pnpm desktop:dist

jetson-export:
	./deploy/jetson/build-export.sh
