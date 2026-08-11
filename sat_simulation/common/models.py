from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class MissionStatus(StrEnum):
    PLANNED = "planned"
    UPLINKING = "uplinking"
    MANEUVERING = "maneuvering"
    CAPTURING = "capturing"
    L0_PROCESSING = "l0_processing"
    L1A_PROCESSING = "l1a_processing"
    L1B_PROCESSING = "l1b_processing"
    GTX_TRANSFER = "gtx_transfer"
    AI_PROCESSING = "ai_processing"
    AI_SKIPPED = "ai_skipped"
    DOWNLINKING = "downlinking"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_MISSION_STATUSES = {MissionStatus.COMPLETED, MissionStatus.FAILED}


class ClockAction(StrEnum):
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    STEP = "step"
    RESET = "reset"
    SET_RATE = "set_rate"


class LinkKind(StrEnum):
    GTX = "gtx"
    UPLINK = "uplink"
    DOWNLINK = "downlink"


class ScenarioConfig(BaseModel):
    id: str = Field(default_factory=lambda: new_id("scenario"))
    name: str = "北京光学任务演示"
    seed: int = 20260811
    epoch: datetime = Field(default_factory=utc_now)
    clock_rate: Literal[1, 10, 100] = 10
    tle_line1: str = "1 55244U 23006C   26126.66766851  .00004587  00000-0  24048-3 0  9998"
    tle_line2: str = "2 55244  43.1978 352.6432 0015896 112.1710 248.0829 15.16807012183579"
    satellite_name: str = "SIM-OPTICAL-01"
    ground_station_name: str = "GS-DEMO-BEIJING"
    ground_station_latitude: float = 39.9042
    ground_station_longitude: float = 116.4074
    ground_station_altitude_m: float = 50.0
    deterministic_contact: bool = True
    scene_id: str = "demo-optical-scene"


class SimulationClockState(BaseModel):
    run_id: str
    simulated_at: datetime
    rate: Literal[1, 10, 100]
    paused: bool
    revision: int = 0


class LinkProfile(BaseModel):
    kind: LinkKind
    bandwidth_bps: float = Field(gt=0)
    latency_ms: float = Field(ge=0)
    jitter_ms: float = Field(default=0, ge=0)
    frame_payload_bytes: int = Field(default=64 * 1024, ge=256, le=1024 * 1024)
    queue_capacity_bytes: int = Field(default=256 * 1024 * 1024, ge=1024)
    max_retries: int = Field(default=5, ge=0, le=20)


def default_link_profiles() -> dict[LinkKind, LinkProfile]:
    return {
        LinkKind.GTX: LinkProfile(
            kind=LinkKind.GTX,
            bandwidth_bps=2.5e9,
            latency_ms=0.2,
        ),
        LinkKind.UPLINK: LinkProfile(
            kind=LinkKind.UPLINK,
            bandwidth_bps=2e6,
            latency_ms=20,
            frame_payload_bytes=1024,
        ),
        LinkKind.DOWNLINK: LinkProfile(
            kind=LinkKind.DOWNLINK,
            bandwidth_bps=150e6,
            latency_ms=20,
            frame_payload_bytes=4096,
        ),
    }


class FaultRule(BaseModel):
    id: str = Field(default_factory=lambda: new_id("fault"))
    link: LinkKind
    enabled: bool = True
    drop_rate: float = Field(default=0, ge=0, le=1)
    corrupt_rate: float = Field(default=0, ge=0, le=1)
    duplicate_rate: float = Field(default=0, ge=0, le=1)
    reorder: bool = False
    disconnected: bool = False
    extra_latency_ms: float = Field(default=0, ge=0)


class MissionCommand(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mission"))
    run_id: str
    scenario_id: str
    name: str = "北京目标光学观测"
    target_name: str = "北京演示目标"
    target_latitude: float = Field(default=39.9042, ge=-90, le=90)
    target_longitude: float = Field(default=116.4074, ge=-180, le=180)
    requested_at: datetime = Field(default_factory=utc_now)
    scene_id: str = "demo-optical-scene"
    enable_ai: bool = True


class MissionCreate(BaseModel):
    scenario_id: str
    name: str = "北京目标光学观测"
    target_name: str = "北京演示目标"
    target_latitude: float = Field(default=39.9042, ge=-90, le=90)
    target_longitude: float = Field(default=116.4074, ge=-180, le=180)
    scene_id: str = "demo-optical-scene"
    enable_ai: bool = True


class SpacecraftState(BaseModel):
    sampled_at: datetime
    latitude: float
    longitude: float
    altitude_km: float
    yaw_deg: float
    pitch_deg: float
    roll_deg: float
    quaternion_wxyz: tuple[float, float, float, float]
    angular_rate_deg_s: float
    pointing_error_deg: float
    in_contact: bool


class TelemetryEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("event"))
    run_id: str
    mission_id: str | None = None
    sequence: int = 0
    event_type: str
    status: str
    message: str
    simulated_at: datetime
    source: str
    data: dict[str, Any] = Field(default_factory=dict)
    provenance: Literal["measured", "derived", "simulated", "placeholder"] = "simulated"


class TransferStatus(StrEnum):
    QUEUED = "queued"
    TRANSFERRING = "transferring"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"


class TransferRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("transfer"))
    run_id: str
    mission_id: str
    link: LinkKind
    name: str
    total_bytes: int = Field(ge=0)
    transferred_bytes: int = Field(default=0, ge=0)
    frame_count: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    crc_failures: int = Field(default=0, ge=0)
    sha256: str
    status: TransferStatus = TransferStatus.QUEUED
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ProductLevel(StrEnum):
    RAW = "raw"
    L0 = "l0"
    L1A = "l1a"
    L1B = "l1b"
    THUMBNAIL = "thumbnail"
    STAC = "stac"
    AI_RESULT = "ai_result"


class ProductManifest(BaseModel):
    id: str = Field(default_factory=lambda: new_id("product"))
    run_id: str
    mission_id: str
    level: ProductLevel
    name: str
    mime_type: str
    size_bytes: int
    sha256: str
    created_at: datetime = Field(default_factory=utc_now)
    processing_parameters: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    lineage: list[str] = Field(default_factory=list)
    artifact_path: str | None = None


class Detection(BaseModel):
    label: Literal["ship", "aircraft", "vehicle"]
    confidence: float = Field(ge=0, le=1)
    bbox_pixel: tuple[float, float, float, float]
    polygon_wgs84: list[tuple[float, float]] | None = None


class DetectionResult(BaseModel):
    status: Literal["ok", "not_configured", "unavailable", "error"]
    provenance: Literal["model", "placeholder"]
    provider: str
    model_version: str | None = None
    elapsed_ms: float = Field(default=0, ge=0)
    detections: list[Detection] = Field(default_factory=list)
    reason: str | None = None


class AnalysisResult(BaseModel):
    status: Literal["ok", "not_configured", "unavailable", "error"]
    provenance: Literal["model", "placeholder"]
    provider: str
    content: str | None = None
    reason: str | None = None


class ScenarioControl(BaseModel):
    action: ClockAction
    rate: Literal[1, 10, 100] | None = None
    step_seconds: float = Field(default=1, gt=0, le=3600)

    @field_validator("rate")
    @classmethod
    def require_rate_for_set_rate(cls, value: int | None, info):
        if info.data.get("action") == ClockAction.SET_RATE and value is None:
            raise ValueError("rate is required for set_rate")
        return value
