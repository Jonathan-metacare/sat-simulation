"""Generate a deterministic GeoTIFF and SDK-compliant custom processor ZIPs."""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples" / "custom-processing"
OUTPUT = SOURCE / "dist"


def write_scene(path: Path) -> None:
    height = width = 384
    y, x = np.mgrid[0:height, 0:width]
    water = ((x - 275) ** 2 / 105**2 + (y - 115) ** 2 / 64**2) < 1
    runway = (np.abs(y - (0.42 * x + 92)) < 7) | (np.abs(y - (-0.13 * x + 286)) < 4)
    blocks = ((x // 24 + y // 24) % 5 == 0) & ~water
    background = 0.13 + 0.18 * (x / width) + 0.14 * (y / height)
    image = np.stack(
        [background + runway * 0.46 + blocks * 0.22, background * 0.90 + runway * 0.34 + water * 0.25, background * 0.72 + runway * 0.12 + water * 0.53]
    )
    image = np.clip(image, 0, 1)
    values = np.round(image * 65535).astype(np.uint16)
    transform = from_origin(-122.49, 47.67, 0.00012, 0.00012)
    with rasterio.open(
        path, "w", driver="GTiff", width=width, height=height, count=3,
        dtype="uint16", crs="EPSG:4326", transform=transform, compress="deflate",
    ) as destination:
        destination.write(values)
        destination.update_tags(
            scene_id="demo-seattle-custom-processing",
            source="deterministic-custom-processor-validation-fixture",
            description="Synthetic Seattle-area optical scene for custom L0/L1 validation",
        )


def make_bundle(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("processor.yaml", "processor.py"):
            archive.write(source / name, arcname=name)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_scene(OUTPUT / "demo-seattle-custom-input-16bit.tif")
    make_bundle(SOURCE / "l0_demo", OUTPUT / "demo-custom-l0-processor.zip")
    make_bundle(SOURCE / "l1_demo", OUTPUT / "demo-custom-l1-processor.zip")
    print(OUTPUT)


if __name__ == "__main__":
    main()
