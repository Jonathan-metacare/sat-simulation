from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
import rasterio
from pyproj import CRS
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from sat_simulation.common.models import SceneAsset

MAX_PIXELS = 100_000_000


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _detected_suffix(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith((b"II*\x00", b"MM\x00*")):
        return ".tif"
    return None


def validate_and_convert_scene(
    content: bytes,
    *,
    filename: str,
    scene_id: str,
    destination: Path,
    center_latitude: float | None = None,
    center_longitude: float | None = None,
    pixel_size: float | None = None,
    crs: str = "EPSG:4326",
    version: int = 1,
) -> SceneAsset:
    suffix = Path(filename).suffix.lower()
    detected = _detected_suffix(content)
    expected = ".jpg" if suffix == ".jpeg" else ".tif" if suffix == ".tiff" else suffix
    if detected is None or detected != expected:
        expected_label = expected or "supported image"
        detected_label = detected or "unknown"
        raise ValueError(
            f"file content does not match extension: expected {expected_label}, "
            f"detected {detected_label}"
        )
    source_sha = _sha(content)
    destination.parent.mkdir(parents=True, exist_ok=True)
    conversion: dict[str, object] = {"source_format": suffix.lstrip(".")}
    if suffix in {".tif", ".tiff"}:
        try:
            with MemoryFile(content) as memory, memory.open() as source:
                if source.width * source.height > MAX_PIXELS:
                    raise ValueError("scene exceeds 100 million pixels")
                if any(dtype != "uint16" for dtype in source.dtypes):
                    raise ValueError("GeoTIFF scene must use uint16 samples")
                if source.count < 1 or source.count > 16:
                    raise ValueError("scene must contain 1-16 bands")
                if not source.crs:
                    raise ValueError("GeoTIFF scene must define a CRS")
                profile = source.profile.copy()
                data = source.read()
                transform = source.transform
                canonical_crs = str(source.crs)
        except Exception as exc:
            raise ValueError(f"invalid GeoTIFF: {exc}") from exc
        profile.update(driver="GTiff", dtype="uint16", compress="deflate")
        with rasterio.open(destination, "w", **profile) as target:
            target.write(data)
            target.update_tags(scene_id=scene_id, source_sha256=source_sha)
        source_mime = "image/tiff"
    elif suffix in {".png", ".jpg", ".jpeg"}:
        if None in {center_latitude, center_longitude, pixel_size}:
            raise ValueError("PNG/JPEG requires center_latitude, center_longitude and pixel_size")
        if not (-90 <= float(center_latitude) <= 90):
            raise ValueError("center_latitude must be between -90 and 90")
        if not (-180 <= float(center_longitude) <= 180):
            raise ValueError("center_longitude must be between -180 and 180")
        if float(pixel_size) <= 0:
            raise ValueError("pixel_size must be positive")
        CRS.from_user_input(crs)
        encoded = np.frombuffer(content, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError("invalid PNG/JPEG image")
        if image.ndim == 2:
            image = image[:, :, None]
        if image.shape[0] * image.shape[1] > MAX_PIXELS:
            raise ValueError("scene exceeds 100 million pixels")
        if image.shape[2] not in {1, 3, 4}:
            raise ValueError("PNG/JPEG must have 1, 3 or 4 channels")
        if image.shape[2] == 4:
            image = image[:, :, :3]
        if image.shape[2] == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        if image.dtype == np.uint8:
            image = image.astype(np.uint16) * 257
        elif image.dtype != np.uint16:
            raise ValueError("unsupported image sample type")
        height, width, bands = image.shape
        transform = from_origin(
            float(center_longitude) - width * float(pixel_size) / 2,
            float(center_latitude) + height * float(pixel_size) / 2,
            float(pixel_size),
            float(pixel_size),
        )
        data = np.transpose(image, (2, 0, 1))
        with rasterio.open(
            destination,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=bands,
            dtype="uint16",
            crs=crs,
            transform=transform,
            compress="deflate",
        ) as target:
            target.write(data)
            target.update_tags(scene_id=scene_id, source_sha256=source_sha)
        canonical_crs = CRS.from_user_input(crs).to_string()
        source_mime = "image/png" if suffix == ".png" else "image/jpeg"
        conversion.update(
            {
                "center_latitude": center_latitude,
                "center_longitude": center_longitude,
                "pixel_size": pixel_size,
                "crs": canonical_crs,
            }
        )
    else:
        raise ValueError("only GeoTIFF, PNG and JPEG scenes are accepted")
    with rasterio.open(destination) as source:
        return SceneAsset(
            scene_id=scene_id,
            version=version,
            source_name=Path(filename).name,
            source_mime_type=source_mime,
            source_sha256=source_sha,
            canonical_sha256=_sha(destination.read_bytes()),
            width=source.width,
            height=source.height,
            bands=source.count,
            crs=canonical_crs,
            transform=tuple(source.transform),
            conversion=conversion,
        )
