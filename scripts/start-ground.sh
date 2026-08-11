#!/bin/sh
set -eu
alembic upgrade head
exec uvicorn sat_simulation.services.ground:app --host 0.0.0.0 --port 8000

