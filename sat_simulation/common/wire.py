from __future__ import annotations

import json
import struct
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from sat_simulation.common.models import ProductManifest

META_LENGTH = struct.Struct("!I")


def pack_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def unpack_json(payload: bytes) -> dict[str, Any]:
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def pack_product(manifest: ProductManifest, path: Path) -> bytes:
    metadata = manifest.model_dump_json().encode("utf-8")
    return META_LENGTH.pack(len(metadata)) + metadata + path.read_bytes()


def unpack_product(payload: bytes) -> tuple[ProductManifest, bytes]:
    if len(payload) < META_LENGTH.size:
        raise ValueError("truncated product envelope")
    (length,) = META_LENGTH.unpack(payload[: META_LENGTH.size])
    end = META_LENGTH.size + length
    if len(payload) < end:
        raise ValueError("truncated product metadata")
    manifest = ProductManifest.model_validate_json(payload[META_LENGTH.size : end])
    return manifest, payload[end:]


def pack_product_bundle(manifests: list[ProductManifest], paths: dict[str, Path]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps([item.model_dump(mode="json") for item in manifests], ensure_ascii=False),
        )
        for manifest in manifests:
            path = paths[manifest.id]
            archive.write(path, manifest.name)
    return buffer.getvalue()


def unpack_product_bundle(payload: bytes) -> tuple[list[ProductManifest], dict[str, bytes]]:
    with zipfile.ZipFile(BytesIO(payload), "r") as archive:
        manifests = [
            ProductManifest.model_validate(item)
            for item in json.loads(archive.read("manifest.json").decode("utf-8"))
        ]
        files = {manifest.name: archive.read(manifest.name) for manifest in manifests}
    return manifests, files
