from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    CANCELLED = "cancelled"


TERMINAL_MISSION_STATUSES = {
    MissionStatus.COMPLETED,
    MissionStatus.FAILED,
    MissionStatus.CANCELLED,
}


class MissionPhase(StrEnum):
    INITIALIZED = "initialized"
    UPLINK_COMPLETE = "uplink_complete"
    CAPTURE_COMPLETE = "capture_complete"
    PROCESSING_COMPLETE = "processing_complete"
    GTX_COMPLETE = "gtx_complete"
    AI_COMPLETE = "ai_complete"
    COMPLETED = "completed"


class ExecutionState(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    BLOCKED = "blocked"
    RETRYABLE_ERROR = "retryable_error"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AIMode(StrEnum):
    YOLO = "yolo"
    LLM = "llm"


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
    PAYLOAD_BUS = "payload_bus"


class NodeKind(StrEnum):
    GROUND = "ground"
    PLATFORM = "platform"
    OPTICAL = "optical"
    GPU = "gpu"


class ProtocolLinkKind(StrEnum):
    UPLINK = "uplink"
    DOWNLINK = "downlink"
    GTX = "gtx"
    PAYLOAD_BUS = "payload_bus"


class ProtocolTransactionStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessorStage(StrEnum):
    L0 = "l0"
    L1 = "l1"


class ProcessorRuntimeStatus(StrEnum):
    BUILTIN = "builtin"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessorDefinition(BaseModel):
    """Strict manifest embedded in an uploaded processor bundle."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,79}$")
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    stage: ProcessorStage
    entrypoint: str = Field(min_length=3, max_length=240)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    cpu_limit: float = Field(default=1.0, gt=0, le=16)
    memory_mb: int = Field(default=1024, ge=128, le=32768)
    output_limit_mb: int = Field(default=1024, ge=1, le=16384)


class ProcessorVersion(BaseModel):
    id: str = Field(default_factory=lambda: new_id("processor"))
    definition: ProcessorDefinition
    sha256: str = Field(min_length=64, max_length=64)
    bundle_path: str | None = None
    runtime_status: ProcessorRuntimeStatus = ProcessorRuntimeStatus.READY
    runtime_type: str = "oci"
    source_files: list[str] = Field(default_factory=lambda: ["processor.yaml", "processor.py"])
    created_at: datetime = Field(default_factory=utc_now)


class ProcessorWorkspaceCreate(BaseModel):
    """A UI-authored source revision. The host owns the resulting manifest."""

    stage: ProcessorStage
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,79}$")
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    source: str = Field(min_length=1, max_length=256 * 1024)


class ProcessorExecution(BaseModel):
    id: str = Field(default_factory=lambda: new_id("execution"))
    mission_id: str
    processor_id: str
    stage: ProcessorStage
    status: ProcessorRuntimeStatus = ProcessorRuntimeStatus.RUNNING
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    exit_code: int | None = None
    error: str | None = None
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    resource_limits: dict[str, Any] = Field(default_factory=dict)
    runtime_type: str = "oci"
    sandbox_profile_version: str | None = None
    block_reason: str | None = None
    stdout: str = ""
    stderr: str = ""


class SceneAsset(BaseModel):
    id: str = Field(default_factory=lambda: new_id("scene_asset"))
    scene_id: str
    version: int = Field(default=1, ge=1)
    source_name: str
    source_mime_type: str
    source_sha256: str = Field(min_length=64, max_length=64)
    canonical_sha256: str = Field(min_length=64, max_length=64)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    bands: int = Field(gt=0, le=16)
    dtype: str = "uint16"
    crs: str
    transform: tuple[float, float, float, float, float, float, float, float, float]
    conversion: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


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
        LinkKind.PAYLOAD_BUS: LinkProfile(
            kind=LinkKind.PAYLOAD_BUS,
            bandwidth_bps=1e9,
            latency_ms=0.1,
        ),
    }


class SensorSettings(BaseModel):
    """Validated optical-sensor parameters frozen with a scenario."""

    model_config = ConfigDict(extra="forbid")

    bit_depth: int = Field(default=12, ge=8, le=16)
    gain: float = Field(default=1.0, gt=0, le=100)
    offset_dn: float = Field(default=32.0, ge=0, le=65535)
    dark_current_dn: float = Field(default=4.0, ge=0, le=65535)
    read_noise_dn: float = Field(default=0.0, ge=0, le=65535)
    prnu_sigma: float = Field(default=0.0, ge=0, le=1)
    bad_pixel_rate: float = Field(default=0.0, ge=0, le=1)
    stripe_amplitude_dn: float = Field(default=0.0, ge=0, le=65535)
    line_period_ms: float = Field(default=1.0, gt=0, le=1000)


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
    ground_station_latitude: float = Field(default=39.9042, ge=-90, le=90)
    ground_station_longitude: float = Field(default=116.4074, ge=-180, le=180)
    ground_station_altitude_m: float = Field(default=50.0, ge=-1000, le=100000)
    deterministic_contact: bool = True
    scene_id: str = "demo-optical-scene"
    scene_asset_id: str | None = None
    l0_processor_id: str = "builtin-l0"
    l1_processor_id: str = "builtin-l1"
    scene_ready: bool = True
    links: dict[LinkKind, LinkProfile] = Field(default_factory=default_link_profiles)
    sensor: SensorSettings = Field(default_factory=SensorSettings)

    def link_profile(self, kind: LinkKind) -> LinkProfile:
        return self.links.get(kind, default_link_profiles()[kind])


class SatelliteCreateRequest(BaseModel):
    """The basic, user-authored fields for a new satellite scenario."""

    satellite_name: str = Field(min_length=1, max_length=120)
    tle_line1: str = Field(min_length=2, max_length=100)
    tle_line2: str = Field(min_length=2, max_length=100)
    ground_station_name: str = Field(min_length=1, max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float = Field(ge=-1000, le=100000)

    @field_validator("satellite_name", "tle_line1", "tle_line2", "ground_station_name")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class StrictScenarioModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImportedLinkProfile(StrictScenarioModel):
    bandwidth_bps: float = Field(gt=0)
    latency_ms: float = Field(ge=0)
    jitter_ms: float = Field(default=0, ge=0)
    frame_payload_bytes: int | None = Field(default=None, ge=256, le=1024 * 1024)
    queue_capacity_bytes: int | None = Field(default=None, ge=1024)
    max_retries: int | None = Field(default=None, ge=0, le=20)


class ImportedLinks(StrictScenarioModel):
    gtx: ImportedLinkProfile
    uplink: ImportedLinkProfile
    downlink: ImportedLinkProfile


class ImportedSatellite(StrictScenarioModel):
    name: str = Field(min_length=1, max_length=120)
    tle_line1: str = Field(min_length=2, max_length=100)
    tle_line2: str = Field(min_length=2, max_length=100)


class ImportedGroundStation(StrictScenarioModel):
    id: str = Field(min_length=1, max_length=120)
    simulated: bool
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float = Field(ge=-1000, le=100000)


class ImportedScenarioYaml(StrictScenarioModel):
    schema_version: Literal[1]
    name: str = Field(min_length=1, max_length=200)
    seed: int = Field(ge=0, le=2**63 - 1)
    clock_rate: Literal[1, 10, 100]
    satellite: ImportedSatellite
    ground_station: ImportedGroundStation
    links: ImportedLinks
    sensor: SensorSettings
    scene_id: str | None = Field(default=None, min_length=1, max_length=200)


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
    scene_asset_id: str | None = None
    scene_asset: SceneAsset | None = None
    l0_processor_id: str = "builtin-l0"
    l1_processor_id: str = "builtin-l1"
    processor_snapshots: dict[str, dict[str, Any]] = Field(default_factory=dict)
    enable_ai: bool = True
    ai_mode: AIMode = AIMode.YOLO
    ai_model: str | None = Field(default=None, max_length=200)
    project_context: str = Field(default="SpaceZenith-Sim 光学观测任务", max_length=4000)
    analysis_prompt: str = Field(
        default="识别图像中的主要地物、目标和异常，说明判断依据与不确定性。",
        max_length=2000,
    )
    scenario_snapshot: ScenarioConfig | None = None
    planned_windows: PlannedWindows | None = None


class MissionCreate(BaseModel):
    scenario_id: str
    name: str = "北京目标光学观测"
    target_name: str = "北京演示目标"
    target_latitude: float = Field(default=39.9042, ge=-90, le=90)
    target_longitude: float = Field(default=116.4074, ge=-180, le=180)
    scene_id: str = "demo-optical-scene"
    enable_ai: bool = True
    ai_mode: AIMode = AIMode.YOLO
    ai_model: str | None = Field(default=None, max_length=200)
    project_context: str = Field(default="SpaceZenith-Sim 光学观测任务", max_length=4000)
    analysis_prompt: str = Field(
        default="识别图像中的主要地物、目标和异常，说明判断依据与不确定性。",
        max_length=2000,
    )


class MissionAdvance(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=160)
    playback_speed: Literal[1, 2, 5] = 1


class MissionPromptUpdate(BaseModel):
    """Mutable LLM instruction before the AI execution step begins."""

    analysis_prompt: str = Field(min_length=1, max_length=2000)


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


class OrbitSample(BaseModel):
    sampled_at: datetime
    latitude: float
    longitude: float
    altitude_km: float
    elevation_deg: float
    visible: bool


class ContactWindow(BaseModel):
    aos: datetime
    los: datetime
    max_elevation_at: datetime
    max_elevation_deg: float


class PlannedWindows(BaseModel):
    uplink: ContactWindow
    capture: ContactWindow
    downlink: ContactWindow
    target_name: str
    target_latitude: float
    target_longitude: float
    tle_line1: str
    tle_line2: str
    minimum_elevation_deg: float = 5.0


class MissionStepAttempt(BaseModel):
    id: str = Field(default_factory=lambda: new_id("attempt"))
    mission_id: str
    from_phase: MissionPhase
    target_phase: MissionPhase
    attempt_number: int
    idempotency_key: str
    state: ExecutionState = ExecutionState.RUNNING
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    error: str | None = None


class OrbitTrack(BaseModel):
    generated_at: datetime
    satellite_name: str
    ground_station_name: str
    minimum_elevation_deg: float
    visibility_radius_m: float
    contact_mode: Literal["geometric", "deterministic"]
    current: OrbitSample
    history: list[OrbitSample]
    forecast: list[OrbitSample]
    contact_windows: list[ContactWindow]


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
    channel: Literal["simulation_control", "uplink", "gtx", "downlink"] = "simulation_control"


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
    protocol_transaction_id: str | None = None


class ProtocolPayloadView(BaseModel):
    kind: Literal["json", "binary", "none"] = "none"
    mime_type: str | None = None
    decoded_json: dict[str, Any] | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    redacted: bool = False


class ProtocolFrameTrace(BaseModel):
    id: str = Field(default_factory=lambda: new_id("frame"))
    transaction_id: str
    sequence: int
    total: int
    message_type: str
    payload_bytes: int = Field(ge=0)
    simulated_at: datetime
    crc32c: str | None = None
    crc_valid: bool = True
    attempt: int = Field(default=0, ge=0)
    ack_status: Literal["sent", "ack", "nak", "dropped", "crc_error"] = "sent"
    missing_sequences: list[int] = Field(default_factory=list)


class ProtocolTransaction(BaseModel):
    id: str
    run_id: str
    mission_id: str
    link: ProtocolLinkKind
    protocol: str = "SIMF/1"
    message_type: str
    source_node: NodeKind
    target_node: NodeKind
    direction: str
    status: ProtocolTransactionStatus = ProtocolTransactionStatus.RUNNING
    total_bytes: int = Field(default=0, ge=0)
    frame_count: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    crc_failures: int = Field(default=0, ge=0)
    sha256: str | None = None
    payload: ProtocolPayloadView = Field(default_factory=ProtocolPayloadView)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    legacy_summary_only: bool = False


class NodeArtifact(BaseModel):
    key: str
    name: str
    level: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    sha256: str
    available: bool = True
    observation_only: bool = True
    previewable: bool = False


class NodeSnapshot(BaseModel):
    node: NodeKind
    mission_id: str
    reachable: bool = True
    status: str
    observation_notice: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[NodeArtifact] = Field(default_factory=list)


class ProductLevel(StrEnum):
    RAW = "raw"
    L0 = "l0"
    L1A = "l1a"
    L1B = "l1b"
    AUX_CONTEXT = "aux_context"
    THUMBNAIL = "thumbnail"
    STAC = "stac"
    AI_RESULT = "ai_result"
    RESULT_PACKAGE = "result_package"


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


class MissionSummary(BaseModel):
    command: MissionCommand
    status: MissionStatus
    error: str | None = None
    phase: MissionPhase
    execution_state: ExecutionState
    active_substage: str | None = None
    ai_mode: AIMode
    planned_windows: PlannedWindows | None = None
    block_reason: str | None = None
    legacy_terminal: bool = False
    next_action: str | None = None
    can_advance: bool = False
    created_at: datetime
    updated_at: datetime


class MissionDetail(MissionSummary):
    events: list[TelemetryEvent] = Field(default_factory=list)
    products: list[ProductManifest] = Field(default_factory=list)
    onboard_products: list[ProductManifest] = Field(default_factory=list)
    transfers: list[TransferRecord] = Field(default_factory=list)
    step_attempts: list[MissionStepAttempt] = Field(default_factory=list)


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
    model_version: str | None = None
    elapsed_ms: float = Field(default=0, ge=0)
    content: str | None = None
    finish_reason: str | None = None
    truncated: bool = False
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
