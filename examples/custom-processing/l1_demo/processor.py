"""Reference custom L1 processor for SpaceZenith-Sim.

L1A preserves the received L0 DN. L1B applies the frozen sensor offset, dark
current and gain, then stores calibrated reflectance as uint16 [0, 65535].
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine


def write_geotiff(path: Path, data: np.ndarray, raster: dict, tags: dict[str, str]) -> None:
    transform_values = raster["transform"]
    transform = Affine(*transform_values[:6])
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=int(raster["width"]),
        height=int(raster["height"]),
        count=int(raster["bands"]),
        dtype=data.dtype,
        crs=raster["crs"],
        transform=transform,
        compress="deflate",
    ) as destination:
        destination.write(data)
        destination.update_tags(**tags)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    request = json.loads(Path(args.input).read_text(encoding="utf-8"))
    l0 = np.load(request["files"]["l0"], allow_pickle=False)
    raster = request["raster"]
    sensor = request.get("sensor", {})
    output_dir = Path(args.output).parent

    l1a_name = "custom_l1a.tif"
    l1b_name = "custom_l1b.tif"
    write_geotiff(
        output_dir / l1a_name,
        l0.astype(np.uint16, copy=False),
        raster,
        {"processing_level": "L1A", "processor": "demo-custom-l1", "captured_at": request["captured_at"]},
    )

    max_dn = float((1 << int(sensor.get("bit_depth", 12))) - 1)
    corrected = (l0.astype(np.float64) - float(sensor.get("offset_dn", 0)) - float(sensor.get("dark_current_dn", 0)))
    corrected /= max(max_dn * float(sensor.get("gain", 1.0)), 1.0)
    l1b = np.round(np.clip(corrected, 0.0, 1.0) * 65535.0).astype(np.uint16)
    write_geotiff(
        output_dir / l1b_name,
        l1b,
        raster,
        {"processing_level": "L1B", "processor": "demo-custom-l1", "calibration": "offset-dark-gain"},
    )
    Path(args.output).write_text(json.dumps({"outputs": {"l1a": l1a_name, "l1b": l1b_name}}), encoding="utf-8")


if __name__ == "__main__":
    main()
