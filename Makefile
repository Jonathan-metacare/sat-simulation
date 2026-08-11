.PHONY: install test lint web-install web-check dev compose-up compose-down smoke

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
	cd web && pnpm typecheck && pnpm lint && pnpm build

compose-up:
	docker compose up --build

compose-down:
	docker compose down

smoke:
	uv run python scripts/demo_mission.py

