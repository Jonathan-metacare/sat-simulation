FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# The API uses the host Docker daemon only to create isolated, short-lived L1
# processor containers. This image contains the CLI, not a Docker daemon.
# Rasterio's Linux ARM64 extension links libexpat.so.1.
RUN apt-get update \
    && apt-get install -y --no-install-recommends docker.io libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY sat_simulation ./sat_simulation

RUN pip install .

EXPOSE 8002 9101

CMD ["sh", "-c", "exec python -m uvicorn sat_simulation.services.gpu:app --host \"${SAT_SIM_HOST:-0.0.0.0}\" --port \"${SAT_SIM_GPU_API_PORT:-8002}\""]
