from __future__ import annotations

import io
import stat
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest
import rasterio

from sat_simulation.common.models import ProcessorStage
from sat_simulation.common.protocol import crc32c
from sat_simulation.processors import (
    ProcessorBundleError,
    ProcessorRunner,
    inspect_processor_bundle,
)
from sat_simulation.processors.templates import (
    builtin_template,
    source_from_bundle,
    workspace_bundle,
)


def bundle(manifest: str, files: dict[str, bytes] | None = None) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("processor.yaml", manifest)
        for name, content in (files or {"processor.py": b"print('ok')"}).items():
            archive.writestr(name, content)
    return output.getvalue()


MANIFEST = """\
schema_version: 1
id: customer-l0
name: Customer L0
version: 1.0.0
stage: l0
entrypoint: processor.py
timeout_seconds: 60
cpu_limit: 1
memory_mb: 512
output_limit_mb: 64
"""


def test_processor_bundle_is_strict_and_stage_is_frozen() -> None:
    definition, digest = inspect_processor_bundle(bundle(MANIFEST))
    assert definition.stage == ProcessorStage.L0
    assert definition.entrypoint == "processor.py"
    assert len(digest) == 64

    with pytest.raises(ProcessorBundleError, match="unexpected"):
        inspect_processor_bundle(bundle(MANIFEST + "unexpected: true\n"))


def test_processor_bundle_rejects_traversal_and_symlink() -> None:
    with pytest.raises(ProcessorBundleError, match="unsafe bundle path"):
        inspect_processor_bundle(bundle(MANIFEST, {"processor.py": b"", "../escape.py": b""}))

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("processor.yaml", MANIFEST)
        link = zipfile.ZipInfo("processor.py")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "target.py")
    with pytest.raises(ProcessorBundleError, match="Symbolic|symbolic"):
        inspect_processor_bundle(output.getvalue())

    with pytest.raises(ProcessorBundleError, match="wheels"):
        inspect_processor_bundle(bundle(MANIFEST, {"processor.py": b"", "wheels/foo.whl": b"x"}))


@pytest.mark.parametrize("stage", [ProcessorStage.L0, ProcessorStage.L1])
def test_builtin_workspace_templates_are_executable_default_bundles(stage: ProcessorStage) -> None:
    template = builtin_template(stage)
    assert "def main()" in template.source
    assert "NotImplementedError" not in template.source
    assert "spacezenith-built-in-sdk" in template.source or "_decode_raw" in template.source
    content = workspace_bundle(template.definition, template.source)
    definition, _digest = inspect_processor_bundle(content)
    assert definition.stage == stage


def test_workspace_bundle_rejects_invalid_python_and_round_trips_source(tmp_path: Path) -> None:
    template = builtin_template(ProcessorStage.L0)
    with pytest.raises(ProcessorBundleError, match="syntax error"):
        workspace_bundle(template.definition, "def broken(:\n")
    bundle_path = tmp_path / "processor.zip"
    bundle_path.write_bytes(workspace_bundle(template.definition, template.source))
    manifest, source = source_from_bundle(str(bundle_path), template.definition)
    assert "stage: l0" in manifest
    assert source == template.source


@pytest.mark.asyncio
async def test_macos_desktop_runner_executes_only_inside_seatbelt(tmp_path: Path) -> None:
    runner = ProcessorRunner(runtime="desktop-sandbox")
    if not await runner.available():
        pytest.skip("macOS Seatbelt is unavailable on this platform")
    definition = builtin_template(ProcessorStage.L0).definition.model_copy(
        update={"id": "seatbelt-smoke", "timeout_seconds": 10, "memory_mb": 2048}
    )
    source = builtin_template(ProcessorStage.L0).source
    bundle_path = tmp_path / "processor.zip"
    bundle_path.write_bytes(workspace_bundle(definition, source))
    raw_path = tmp_path / "raw.bin"
    payload = np.array([42], dtype=">u2").tobytes()
    raw_path.write_bytes(
        struct.Struct("!4sHHII").pack(b"OPTR", 0, 0, len(payload), crc32c(payload)) + payload
    )
    result = await runner.run(
        bundle_path=bundle_path,
        request={"schema_version": 1, "raw_layout": {"shape": [1, 1, 1]}},
        input_files={"raw": raw_path},
        execution_dir=tmp_path / "execution",
    )
    assert (result.output_dir / "l0.npy").is_file()


@pytest.mark.asyncio
async def test_macos_desktop_runner_writes_l1_geotiff_with_proj_data(tmp_path: Path) -> None:
    runner = ProcessorRunner(runtime="desktop-sandbox")
    if not await runner.available():
        pytest.skip("macOS Seatbelt is unavailable on this platform")
    definition = builtin_template(ProcessorStage.L1).definition.model_copy(
        update={"id": "seatbelt-l1-geotiff", "timeout_seconds": 10, "memory_mb": 2048}
    )
    bundle_path = tmp_path / "processor.zip"
    bundle_path.write_bytes(
        workspace_bundle(definition, builtin_template(ProcessorStage.L1).source)
    )
    l0_path = tmp_path / "l0.npy"
    np.save(l0_path, np.full((1, 256, 256), 512, dtype=np.uint16), allow_pickle=False)

    result = await runner.run(
        bundle_path=bundle_path,
        request={
            "schema_version": 1,
            "captured_at": "2026-08-20T00:00:00+00:00",
            "sensor": {
                "bit_depth": 12,
                "gain": 1.0,
                "offset_dn": 32.0,
                "dark_current_dn": 4.0,
            },
            "raster": {
                "width": 256,
                "height": 256,
                "bands": 1,
                "crs": "EPSG:4326",
                "transform": [0.0001, 0.0, 116.4, 0.0, -0.0001, 39.9],
            },
        },
        input_files={"l0": l0_path},
        execution_dir=tmp_path / "l1-execution",
    )
    with rasterio.open(result.output_dir / "l1a.tif") as l1a:
        assert l1a.crs.to_string() == "EPSG:4326"
        assert l1a.dtypes == ("uint16",)
    with rasterio.open(result.output_dir / "l1b.tif") as l1b:
        assert l1b.crs.to_string() == "EPSG:4326"
        assert l1b.dtypes == ("float32",)
