from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import rasterio
from rasterio.shutil import copy as raster_copy
from rasterio.transform import from_origin

from sat_simulation.common.models import ProductLevel, ProductManifest
from sat_simulation.common.protocol import crc32c

RAW_PACKET = struct.Struct("!4sHHII")
RAW_MAGIC = b"OPTR"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class SensorConfig:
    bit_depth: int = 12
    gain: float = 1.0
    offset_dn: float = 32.0
    dark_current_dn: float = 4.0
    read_noise_dn: float = 0.0
    prnu_sigma: float = 0.0
    bad_pixel_rate: float = 0.0
    stripe_amplitude_dn: float = 0.0
    line_period_ms: float = 0.5
    seed: int = 20260811

    @property
    def max_dn(self) -> int:
        return (1 << self.bit_depth) - 1


@dataclass(frozen=True)
class SceneMetadata:
    scene_id: str
    target_name: str
    center_latitude: float
    center_longitude: float
    pixel_size_deg: float = 0.0001
    crs: str = "EPSG:4326"


@dataclass
class OpticalProducts:
    manifests: list[ProductManifest]
    paths: dict[ProductLevel, Path]
    truth_path: Path


def ensure_demo_scene(root: Path) -> tuple[Path, SceneMetadata]:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "demo-optical-scene.tif"
    metadata = SceneMetadata(
        scene_id="demo-optical-scene",
        target_name="北京演示目标",
        center_latitude=39.9042,
        center_longitude=116.4074,
    )
    if path.exists():
        return path, metadata

    height = width = 256
    y, x = np.mgrid[0:height, 0:width]
    background = 0.12 + 0.20 * (x / width) + 0.12 * (y / height)
    roads = (np.abs(x - y * 0.65 - 35) < 3) | (np.abs(x + y * 0.25 - 170) < 4)
    water = ((x - 180) ** 2 / 70**2 + (y - 85) ** 2 / 42**2) < 1
    buildings = ((x // 18 + y // 18) % 4 == 0) & ~water
    rgb = np.stack(
        [
            background + roads * 0.35 + buildings * 0.20,
            background * 1.12 + roads * 0.28 + water * 0.17,
            background * 0.90 + roads * 0.20 + water * 0.42,
        ]
    )
    rgb = np.clip(rgb, 0, 1)
    truth = np.round(rgb * 65535).astype(np.uint16)
    transform = from_origin(
        metadata.center_longitude - width * metadata.pixel_size_deg / 2,
        metadata.center_latitude + height * metadata.pixel_size_deg / 2,
        metadata.pixel_size_deg,
        metadata.pixel_size_deg,
    )
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=3,
        dtype="uint16",
        crs=metadata.crs,
        transform=transform,
        compress="deflate",
    ) as dst:
        dst.write(truth)
        dst.update_tags(scene_id=metadata.scene_id, source="deterministic-generated-fixture")
    return path, metadata


class OpticalPipeline:
    def __init__(self, sensor: SensorConfig | None = None) -> None:
        self.sensor = sensor or SensorConfig()

    def capture_raw(
        self,
        *,
        scene_path: Path,
        output_dir: Path,
        run_id: str,
        mission_id: str,
    ) -> tuple[ProductManifest, Path]:
        """Simulate detector packets only; later processing consumes this exact file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        with rasterio.open(scene_path) as src:
            truth = src.read().astype(np.float64) / 65535.0
        dn, _bad_mask = self._simulate_detector(truth)
        raw_path = output_dir / f"{mission_id}_raw.bin"
        self._write_raw(raw_path, dn)
        manifest = self._manifest(
            path=raw_path,
            level=ProductLevel.RAW,
            mime="application/octet-stream",
            run_id=run_id,
            mission_id=mission_id,
            lineage=[],
            quality={"packet_count": int(dn.shape[0] * dn.shape[1])},
        )
        return manifest, raw_path

    def process(
        self,
        *,
        scene_path: Path,
        scene: SceneMetadata,
        output_dir: Path,
        run_id: str,
        mission_id: str,
        captured_at: datetime,
        spacecraft_state: dict[str, Any],
    ) -> OpticalProducts:
        output_dir.mkdir(parents=True, exist_ok=True)
        with rasterio.open(scene_path) as src:
            truth_u16 = src.read().astype(np.uint16)
            profile = src.profile.copy()
            transform = src.transform
            crs = src.crs
        truth = truth_u16.astype(np.float64) / 65535.0
        dn, bad_mask = self._simulate_detector(truth)

        raw_path = output_dir / f"{mission_id}_raw.bin"
        if not raw_path.exists():
            self._write_raw(raw_path, dn)
        l0 = self._read_raw(raw_path, dn.shape)
        l0_path = output_dir / f"{mission_id}_l0.npy"
        np.save(l0_path, l0, allow_pickle=False)

        l1a_path = output_dir / f"{mission_id}_l1a.tif"
        l1a_profile = profile | {"dtype": "uint16", "compress": "deflate"}
        with rasterio.open(l1a_path, "w", **l1a_profile) as dst:
            dst.write(l0)
            dst.update_tags(
                processing_level="L1A",
                captured_at=captured_at.astimezone(UTC).isoformat(),
                calibration=json.dumps(asdict(self.sensor), sort_keys=True),
                spacecraft_state=json.dumps(spacecraft_state, sort_keys=True),
            )

        corrected = self._calibrate(l0, bad_mask)
        l1b_temp = output_dir / f"{mission_id}_l1b_work.tif"
        l1b_path = output_dir / f"{mission_id}_l1b.tif"
        with rasterio.open(
            l1b_temp,
            "w",
            driver="GTiff",
            width=l0.shape[2],
            height=l0.shape[1],
            count=l0.shape[0],
            dtype="float32",
            crs=crs,
            transform=transform,
            tiled=True,
            compress="deflate",
        ) as dst:
            dst.write(corrected.astype(np.float32))
            dst.update_tags(
                processing_level="L1B",
                units="normalized_sensor_radiance",
                captured_at=captured_at.astimezone(UTC).isoformat(),
            )
        try:
            raster_copy(l1b_temp, l1b_path, driver="COG", compress="DEFLATE")
            l1b_temp.unlink()
        except Exception:
            l1b_temp.replace(l1b_path)

        thumbnail_path = output_dir / f"{mission_id}_thumbnail.png"
        self._thumbnail(corrected, thumbnail_path)
        stac_path = output_dir / f"{mission_id}_stac-item.json"

        rmse = float(np.sqrt(np.mean((corrected - truth) ** 2)))
        paths = {
            ProductLevel.RAW: raw_path,
            ProductLevel.L0: l0_path,
            ProductLevel.L1A: l1a_path,
            ProductLevel.L1B: l1b_path,
            ProductLevel.THUMBNAIL: thumbnail_path,
            ProductLevel.STAC: stac_path,
        }
        manifests = [
            self._manifest(
                path=raw_path,
                level=ProductLevel.RAW,
                mime="application/octet-stream",
                run_id=run_id,
                mission_id=mission_id,
                lineage=[],
                quality={"packet_count": int(dn.shape[0] * dn.shape[1])},
            ),
            self._manifest(
                path=l0_path,
                level=ProductLevel.L0,
                mime="application/x-npy",
                run_id=run_id,
                mission_id=mission_id,
                lineage=[raw_path.name],
                quality={"reconstruction_equal": bool(np.array_equal(dn, l0))},
            ),
            self._manifest(
                path=l1a_path,
                level=ProductLevel.L1A,
                mime="image/tiff; application=geotiff",
                run_id=run_id,
                mission_id=mission_id,
                lineage=[l0_path.name],
                quality={"ancillary_attached": True},
            ),
            self._manifest(
                path=l1b_path,
                level=ProductLevel.L1B,
                mime="image/tiff; application=geotiff; profile=cloud-optimized",
                run_id=run_id,
                mission_id=mission_id,
                lineage=[l1a_path.name],
                quality={
                    "truth_rmse": rmse,
                    "bad_pixel_count": int(bad_mask.sum()),
                    "noise_mode": "disabled"
                    if self.sensor.read_noise_dn == 0 and self.sensor.prnu_sigma == 0
                    else "configured",
                },
            ),
            self._manifest(
                path=thumbnail_path,
                level=ProductLevel.THUMBNAIL,
                mime="image/png",
                run_id=run_id,
                mission_id=mission_id,
                lineage=[l1b_path.name],
                quality={},
            ),
        ]
        stac = self._stac_item(scene, captured_at, manifests, transform, l0.shape)
        stac_path.write_text(json.dumps(stac, ensure_ascii=False, indent=2), encoding="utf-8")
        manifests.append(
            self._manifest(
                path=stac_path,
                level=ProductLevel.STAC,
                mime="application/geo+json",
                run_id=run_id,
                mission_id=mission_id,
                lineage=[manifest.name for manifest in manifests],
                quality={"stac_version": "1.1.0"},
            )
        )
        return OpticalProducts(manifests=manifests, paths=paths, truth_path=scene_path)

    def _simulate_detector(self, truth: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        rng = np.random.default_rng(self.sensor.seed)
        prnu = rng.normal(1.0, self.sensor.prnu_sigma, size=truth.shape)
        stripe = np.zeros_like(truth)
        if self.sensor.stripe_amplitude_dn:
            stripe[:, :, ::16] = self.sensor.stripe_amplitude_dn
        noise = rng.normal(0, self.sensor.read_noise_dn, size=truth.shape)
        value = (
            truth * self.sensor.max_dn * self.sensor.gain * prnu
            + self.sensor.offset_dn
            + self.sensor.dark_current_dn
            + stripe
            + noise
        )
        bad_mask = rng.random(truth.shape) < self.sensor.bad_pixel_rate
        value[bad_mask] = 0
        return np.clip(np.round(value), 0, self.sensor.max_dn).astype(np.uint16), bad_mask

    def _calibrate(self, dn: np.ndarray, bad_mask: np.ndarray) -> np.ndarray:
        corrected_dn = dn.astype(np.float64)
        if bad_mask.any():
            for band in range(dn.shape[0]):
                median = cv2.medianBlur(dn[band], 3)
                corrected_dn[band][bad_mask[band]] = median[bad_mask[band]]
        corrected = (corrected_dn - self.sensor.offset_dn - self.sensor.dark_current_dn) / (
            self.sensor.max_dn * self.sensor.gain
        )
        return np.clip(corrected, 0, 1)

    def _write_raw(self, path: Path, dn: np.ndarray) -> None:
        with path.open("wb") as stream:
            for band in range(dn.shape[0]):
                for row in range(dn.shape[1]):
                    payload = dn[band, row].astype(">u2", copy=False).tobytes()
                    stream.write(
                        RAW_PACKET.pack(RAW_MAGIC, band, row, len(payload), crc32c(payload))
                    )
                    stream.write(payload)

    def _read_raw(self, path: Path, shape: tuple[int, ...]) -> np.ndarray:
        output = np.zeros(shape, dtype=np.uint16)
        seen: set[tuple[int, int]] = set()
        with path.open("rb") as stream:
            while header := stream.read(RAW_PACKET.size):
                magic, band, row, length, checksum = RAW_PACKET.unpack(header)
                if magic != RAW_MAGIC:
                    raise ValueError("invalid optical RAW packet sync")
                payload = stream.read(length)
                if len(payload) != length or crc32c(payload) != checksum:
                    raise ValueError(f"invalid optical RAW packet band={band} row={row}")
                key = (band, row)
                if key in seen:
                    continue
                output[band, row] = np.frombuffer(payload, dtype=">u2").astype(np.uint16)
                seen.add(key)
        expected = shape[0] * shape[1]
        if len(seen) != expected:
            raise ValueError(f"incomplete RAW reconstruction: {len(seen)}/{expected}")
        return output

    def _thumbnail(self, corrected: np.ndarray, path: Path) -> None:
        bands = corrected[:3]
        if bands.shape[0] == 1:
            bands = np.repeat(bands, 3, axis=0)
        rgb = np.transpose(bands, (1, 2, 0))
        low, high = np.percentile(rgb, [2, 98])
        display = np.clip((rgb - low) / max(high - low, 1e-9), 0, 1)
        bgr = cv2.cvtColor(np.round(display * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(path), bgr)

    def _manifest(
        self,
        *,
        path: Path,
        level: ProductLevel,
        mime: str,
        run_id: str,
        mission_id: str,
        lineage: list[str],
        quality: dict[str, Any],
    ) -> ProductManifest:
        return ProductManifest(
            run_id=run_id,
            mission_id=mission_id,
            level=level,
            name=path.name,
            mime_type=mime,
            size_bytes=path.stat().st_size,
            sha256=sha256_file(path),
            processing_parameters=asdict(self.sensor),
            quality=quality,
            lineage=lineage,
            artifact_path=str(path),
        )

    def _stac_item(
        self,
        scene: SceneMetadata,
        captured_at: datetime,
        manifests: list[ProductManifest],
        transform,
        shape: tuple[int, ...],
    ) -> dict[str, Any]:
        height, width = shape[1:]
        west, north = transform * (0, 0)
        east, south = transform * (width, height)
        bbox = [west, south, east, north]
        geometry = {
            "type": "Polygon",
            "coordinates": [
                [[west, south], [east, south], [east, north], [west, north], [west, south]]
            ],
        }
        return {
            "type": "Feature",
            "stac_version": "1.1.0",
            "stac_extensions": [],
            "id": f"{scene.scene_id}-{captured_at:%Y%m%dT%H%M%S}",
            "collection": "sat-simulation-optical",
            "bbox": bbox,
            "geometry": geometry,
            "properties": {
                "datetime": captured_at.astimezone(UTC).isoformat(),
                "platform": "SIM-OPTICAL-01",
                "instruments": ["OPTICAL-01"],
            },
            "links": [],
            "assets": {
                manifest.level.value: {
                    "href": manifest.name,
                    "type": manifest.mime_type,
                    "roles": ["thumbnail"]
                    if manifest.level == ProductLevel.THUMBNAIL
                    else ["data"],
                    "file:checksum": f"sha256:{manifest.sha256}",
                }
                for manifest in manifests
            },
        }


class InfraredPayloadPlaceholder:
    name = "INFRARED-01"

    async def capture(self, *_args, **_kwargs) -> dict[str, str]:
        return {"status": "not_implemented", "provenance": "placeholder"}
