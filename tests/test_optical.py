from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
import rasterio

from sat_simulation.common.models import ProductLevel
from sat_simulation.optical.pipeline import (
    OpticalPipeline,
    SensorConfig,
    ensure_demo_scene,
)


def test_optical_l0_l1_pipeline_is_numerically_traceable(tmp_path) -> None:
    scene_path, scene = ensure_demo_scene(tmp_path / "scenes")
    pipeline = OpticalPipeline(
        SensorConfig(
            bit_depth=12,
            gain=1,
            offset_dn=32,
            dark_current_dn=4,
            read_noise_dn=0,
            prnu_sigma=0,
            bad_pixel_rate=0,
            seed=7,
        )
    )
    products = pipeline.process(
        scene_path=scene_path,
        scene=scene,
        output_dir=tmp_path / "products",
        run_id="run_test",
        mission_id="mission_test",
        captured_at=datetime(2026, 8, 11, tzinfo=UTC),
        spacecraft_state={"pointing_error_deg": 0.05},
    )
    l0 = np.load(products.paths[ProductLevel.L0])
    assert l0.dtype == np.uint16
    l0_manifest = next(item for item in products.manifests if item.level == ProductLevel.L0)
    assert l0_manifest.quality["reconstruction_equal"] is True

    with rasterio.open(products.paths[ProductLevel.L1A]) as src:
        assert src.tags()["processing_level"] == "L1A"
        assert src.dtypes[0] == "uint16"
    with rasterio.open(products.paths[ProductLevel.L1B]) as src:
        assert src.tags()["processing_level"] == "L1B"
        assert src.dtypes[0] == "float32"
        assert src.crs.to_string() == "EPSG:4326"
    l1b_manifest = next(item for item in products.manifests if item.level == ProductLevel.L1B)
    assert l1b_manifest.quality["truth_rmse"] < 0.001

    stac = json.loads(products.paths[ProductLevel.STAC].read_text())
    assert stac["stac_version"] == "1.1.0"
    assert {"raw", "l0", "l1a", "l1b", "thumbnail"} <= set(stac["assets"])
