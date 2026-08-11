# Operations

## One-command stack

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:3000`. Ground OpenAPI is at
`http://localhost:8000/docs`. Data remains in four independent Docker volumes.

## Local multi-terminal run

```bash
uv sync --all-groups
SAT_SIM_DATA_DIR=runtime-data/gpu uv run uvicorn sat_simulation.services.gpu:app --port 8002
SAT_SIM_DATA_DIR=runtime-data/ground uv run uvicorn sat_simulation.services.ground:app --port 8000
SAT_SIM_DATA_DIR=runtime-data/platform uv run uvicorn sat_simulation.services.platform:app --port 8001
cd web && pnpm install && pnpm dev
```

Then run `uv run python scripts/demo_mission.py`. Check `/health` on ports 8000,
8001 and 8002 before creating a mission.

Provider URLs are secret-bearing server configuration. V1 reports both providers
as `not_configured`; setting a URL alone does not enable a provider until a
concrete adapter is implemented and validated.

