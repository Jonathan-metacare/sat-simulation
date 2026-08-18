FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 65532 processor \
    && useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin processor \
    && pip install --no-cache-dir "numpy>=2.1,<3" "rasterio>=1.4,<2" "pyproj>=3.7,<4" "opencv-python-headless>=4.10,<5"

USER 65532:65532
WORKDIR /workspace
