"""Application-owned processor SDK templates and safe workspace bundles."""

from __future__ import annotations

import ast
import io
import zipfile
from dataclasses import dataclass

import yaml

from sat_simulation.common.models import ProcessorDefinition, ProcessorStage
from sat_simulation.processors.runtime import ProcessorBundleError, inspect_processor_bundle


@dataclass(frozen=True)
class ProcessorTemplate:
    stage: ProcessorStage
    definition: ProcessorDefinition
    source: str

    @property
    def manifest(self) -> str:
        return yaml.safe_dump(
            self.definition.model_dump(mode="json"), sort_keys=False, allow_unicode=True
        )


_L0_SOURCE = '''"""L0 processor template for SpaceZenith-Sim.

`main()` is owned by the SDK contract. The helper functions below are the
working built-in default. A custom version may replace them while preserving
the input/output contract; the host validates the resulting uint16 NumPy product.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

import numpy as np

_PACKET = struct.Struct("!4sHHII")
_CRC32C_POLY = 0x82F63B78


def _crc32c(data: bytes) -> int:
    value = 0xFFFFFFFF
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (_CRC32C_POLY if value & 1 else 0)
    return value ^ 0xFFFFFFFF


def _decode_raw(raw_path: Path, request: dict) -> np.ndarray:
    bands, height, width = map(int, request["raw_layout"]["shape"])
    output = np.zeros((bands, height, width), dtype=np.uint16)
    seen: set[tuple[int, int]] = set()
    with raw_path.open("rb") as stream:
        while header := stream.read(_PACKET.size):
            if len(header) != _PACKET.size:
                raise ValueError("truncated RAW packet header")
            magic, band, row, length, checksum = _PACKET.unpack(header)
            payload = stream.read(length)
            if magic != b"OPTR":
                raise ValueError("invalid optical RAW packet sync")
            if not (0 <= band < bands and 0 <= row < height):
                raise ValueError("RAW packet coordinate is out of range")
            if len(payload) != length or _crc32c(payload) != checksum:
                raise ValueError(f"invalid RAW packet band={band} row={row}")
            if length != width * 2:
                raise ValueError("unexpected RAW row payload length")
            key = (band, row)
            if key not in seen:
                output[band, row] = np.frombuffer(payload, dtype=">u2").astype(np.uint16)
                seen.add(key)
    if len(seen) != bands * height:
        raise ValueError(f"incomplete RAW reconstruction: {len(seen)}/{bands * height}")
    return output


def validate_packet(raw_path: Path, request: dict) -> None:
    _decode_raw(raw_path, request)


def reconstruct_l0(raw_path: Path, request: dict) -> np.ndarray:
    return _decode_raw(raw_path, request)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    request = json.loads(Path(args.input).read_text(encoding="utf-8"))
    raw_path = Path(request["files"]["raw"])
    validate_packet(raw_path, request)
    l0 = reconstruct_l0(raw_path, request)
    if l0.dtype != np.uint16:
        raise ValueError("L0 output must be uint16")
    output_dir = Path(args.output).parent
    l0_name = "l0.npy"
    np.save(output_dir / l0_name, l0, allow_pickle=False)
    Path(args.output).write_text(json.dumps({"outputs": {"l0": l0_name}}), encoding="utf-8")


if __name__ == "__main__":
    main()
'''

_L1_SOURCE = '''"""L1 processor template for SpaceZenith-Sim.

`main()` is owned by the SDK contract. The helper functions below are the
working built-in default. A custom version may replace them while preserving
the input/output contract; the host validates L1A/L1B GeoTIFF outputs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine


def generate_l1a(l0: np.ndarray, request: dict) -> np.ndarray:
    if l0.dtype != np.uint16:
        raise ValueError("L0 input must be uint16")
    return l0.copy()


def generate_l1b(l1a: np.ndarray, request: dict) -> np.ndarray:
    sensor = request["sensor"]
    max_dn = (1 << int(sensor["bit_depth"])) - 1
    denominator = max_dn * float(sensor["gain"])
    corrected = (
        l1a.astype(np.float32)
        - float(sensor["offset_dn"])
        - float(sensor["dark_current_dn"])
    ) / denominator
    return np.clip(corrected, 0.0, 1.0).astype(np.float32)


def write_geotiff(path: Path, data: np.ndarray, request: dict, level: str) -> None:
    raster = request["raster"]
    transform = Affine(*list(raster["transform"])[:6])
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=int(raster["width"]),
        height=int(raster["height"]),
        count=int(raster["bands"]),
        dtype="uint16" if level == "L1A" else "float32",
        crs=raster["crs"],
        transform=transform,
        tiled=True,
        compress="deflate",
    ) as destination:
        destination.write(data)
        destination.update_tags(
            processing_level=level,
            captured_at=request["captured_at"],
            processor="spacezenith-built-in-sdk",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    request = json.loads(Path(args.input).read_text(encoding="utf-8"))
    l0 = np.load(request["files"]["l0"], allow_pickle=False)
    l1a = generate_l1a(l0, request)
    l1b = generate_l1b(l1a, request)
    output_dir = Path(args.output).parent
    l1a_name, l1b_name = "l1a.tif", "l1b.tif"
    write_geotiff(output_dir / l1a_name, l1a, request, "L1A")
    write_geotiff(output_dir / l1b_name, l1b, request, "L1B")
    Path(args.output).write_text(
        json.dumps({"outputs": {"l1a": l1a_name, "l1b": l1b_name}}), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
'''


def builtin_template(stage: ProcessorStage) -> ProcessorTemplate:
    suffix = stage.value
    definition = ProcessorDefinition(
        schema_version=1,
        id=f"builtin-{suffix}",
        name=f"SpaceZenith built-in {stage.value.upper()} reference template",
        version="1.0.0",
        stage=stage,
        entrypoint="processor.py",
        timeout_seconds=120,
        cpu_limit=1.0,
        memory_mb=1024,
        output_limit_mb=1024,
    )
    return ProcessorTemplate(stage, definition, _L0_SOURCE if stage == ProcessorStage.L0 else _L1_SOURCE)


def workspace_bundle(definition: ProcessorDefinition, source: str) -> bytes:
    if definition.entrypoint != "processor.py":
        raise ProcessorBundleError("workspace entrypoint must be processor.py")
    try:
        compile(source, definition.entrypoint, "exec")
    except SyntaxError as exc:
        raise ProcessorBundleError(f"processor.py syntax error: {exc.msg} at line {exc.lineno}") from exc
    template_tree = ast.parse(builtin_template(definition.stage).source)
    source_tree = ast.parse(source)
    template_main = next(
        (node for node in template_tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"),
        None,
    )
    source_main = next(
        (node for node in source_tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"),
        None,
    )
    if source_main is None or ast.dump(source_main, include_attributes=False) != ast.dump(
        template_main, include_attributes=False
    ):
        raise ProcessorBundleError(
            "workspace processor.py must preserve the application-owned main() contract; "
            "implement the provided helper functions instead"
        )
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("processor.yaml", yaml.safe_dump(definition.model_dump(mode="json"), sort_keys=False))
        archive.writestr(definition.entrypoint, source)
    bundle = content.getvalue()
    inspect_processor_bundle(bundle)
    return bundle


def source_from_bundle(bundle_path: str, definition: ProcessorDefinition) -> tuple[str, str]:
    with zipfile.ZipFile(bundle_path) as archive:
        manifest = archive.read("processor.yaml").decode("utf-8")
        source = archive.read(definition.entrypoint).decode("utf-8")
    return manifest, source
