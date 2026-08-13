"""Generate the deterministic 16-bit Seattle fixture used by the import demo."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "scenarios" / "seattle-optical-scene.tif"
    width = height = 512
    pixel_size = 0.00012
    center_latitude, center_longitude = 47.6062, -122.3321
    y, x = np.mgrid[0:height, 0:width]

    # Deterministic synthetic truth: water, urban blocks, two major corridors,
    # and a few high-reflectance port targets. It is not real satellite data.
    base = 0.13 + 0.12 * x / width + 0.07 * y / height
    water = ((x - 102) / 165) ** 2 + ((y - 270) / 300) ** 2 < 1
    roads = (np.abs(y - (0.44 * x + 52)) < 4) | (np.abs(y - (-0.22 * x + 348)) < 3)
    blocks = ((x // 22 + y // 18) % 5 == 0) & ~water
    port = (((x - 325) // 18) % 2 == 0) & (y > 265) & (y < 380)
    cloud = np.exp(-(((x - 390) / 78) ** 2 + ((y - 98) / 48) ** 2)) * 0.12

    red = base + blocks * 0.22 + roads * 0.32 + port * 0.42 + cloud
    green = base * 1.04 + blocks * 0.18 + roads * 0.30 + port * 0.36 + cloud
    blue = base * 0.92 + water * 0.36 + roads * 0.20 + port * 0.17 + cloud
    image = np.round(np.clip(np.stack([red, green, blue]), 0, 1) * 65535).astype(np.uint16)

    transform = from_origin(
        center_longitude - width * pixel_size / 2,
        center_latitude + height * pixel_size / 2,
        pixel_size,
        pixel_size,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        output, "w", driver="GTiff", width=width, height=height, count=3,
        dtype="uint16", crs="EPSG:4326", transform=transform, compress="deflate",
    ) as dataset:
        dataset.write(image)
        dataset.update_tags(
            scene_id="seattle-optical-scene",
            target_name="Seattle synthetic optical fixture",
            source="deterministic-synthetic-fixture-no-real-imagery",
        )
    print(output)


if __name__ == "__main__":
    main()
