from __future__ import annotations

import cv2
import numpy as np
import pytest
import rasterio

from sat_simulation.optical.scenes import validate_and_convert_scene


def test_png_converts_to_versioned_uint16_geotiff(tmp_path) -> None:
    image = np.zeros((8, 12, 3), dtype=np.uint8)
    image[:, :, 1] = 127
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    destination = tmp_path / "canonical.tif"
    asset = validate_and_convert_scene(
        encoded.tobytes(),
        filename="customer.png",
        scene_id="customer-scene",
        destination=destination,
        center_latitude=47.6062,
        center_longitude=-122.3321,
        pixel_size=0.0001,
        crs="EPSG:4326",
    )
    assert asset.width == 12
    assert asset.height == 8
    assert asset.bands == 3
    assert asset.source_mime_type == "image/png"
    with rasterio.open(destination) as dataset:
        assert dataset.dtypes == ("uint16", "uint16", "uint16")
        assert dataset.crs.to_string() == "EPSG:4326"


def test_scene_import_requires_georeference_and_matching_content(tmp_path) -> None:
    ok, encoded = cv2.imencode(".png", np.zeros((2, 2), dtype=np.uint8))
    assert ok
    with pytest.raises(ValueError, match="requires center_latitude"):
        validate_and_convert_scene(
            encoded.tobytes(),
            filename="scene.png",
            scene_id="bad",
            destination=tmp_path / "bad.tif",
        )
    with pytest.raises(ValueError, match="does not match extension"):
        validate_and_convert_scene(
            encoded.tobytes(),
            filename="scene.jpg",
            scene_id="bad",
            destination=tmp_path / "bad2.tif",
            center_latitude=0,
            center_longitude=0,
            pixel_size=1,
        )
