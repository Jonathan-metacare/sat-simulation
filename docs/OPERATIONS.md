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
uv run alembic upgrade head
SAT_SIM_DATA_DIR=runtime-data/gpu uv run uvicorn sat_simulation.services.gpu:app --port 8002
SAT_SIM_DATA_DIR=runtime-data/ground uv run uvicorn sat_simulation.services.ground:app --port 8000
SAT_SIM_DATA_DIR=runtime-data/platform uv run uvicorn sat_simulation.services.platform:app --port 8001
cd web && pnpm install && pnpm dev
```

Then run `uv run python scripts/demo_mission.py`. Check `/health` on ports 8000,
8001 and 8002 before creating a mission.

Task creation fixes `ai_mode=yolo|llm` for the full run. Configure providers only
on the GPU node:

```bash
SAT_SIM_YOLO_API_URL=http://127.0.0.1:9000
SAT_SIM_YOLO_MODEL=your-model
# or OpenAI-compatible /v1/chat/completions
SAT_SIM_LLM_API_URL=http://127.0.0.1:11434
SAT_SIM_LLM_MODEL=your-vision-model
```

For LLM missions, the creation dialog captures project/user context and the
analysis request. The GPU derives a PNG visual preview from the verified L1B
GeoTIFF and sends the preview, L1B manifest, mission target and that context to
the OpenAI-compatible multimodal endpoint. Ground displays the analysis beside
the L1B preview only after the sixth-step result package is downlinked.

Optional `SAT_SIM_YOLO_API_KEY` and `SAT_SIM_LLM_API_KEY` remain server-side and
are never written to events or the database. After changing provider settings,
restart only GPU and retry the blocked fifth step with a new idempotency key.
