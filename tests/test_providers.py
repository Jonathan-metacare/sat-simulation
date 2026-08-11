from __future__ import annotations

import pytest

from sat_simulation.common.models import ProductLevel, ProductManifest
from sat_simulation.payload.providers import (
    PlaceholderDetectionProvider,
    PlaceholderLanguageProvider,
)


@pytest.mark.asyncio
async def test_placeholders_never_fabricate_model_output(tmp_path) -> None:
    path = tmp_path / "l1b.tif"
    path.write_bytes(b"fixture")
    product = ProductManifest(
        run_id="run",
        mission_id="mission",
        level=ProductLevel.L1B,
        name=path.name,
        mime_type="image/tiff",
        size_bytes=path.stat().st_size,
        sha256="0" * 64,
    )
    detection = await PlaceholderDetectionProvider().detect(product, path)
    language = await PlaceholderLanguageProvider().analyze({}, [product])
    assert detection.status == "not_configured"
    assert detection.detections == []
    assert detection.provenance == "placeholder"
    assert language.status == "not_configured"
    assert language.content is None
