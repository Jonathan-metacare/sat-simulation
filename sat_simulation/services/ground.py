from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import tempfile
import zipfile
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

import httpx
import rasterio
import yaml
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import ValidationError
from sgp4.api import Satrec
from sse_starlette.sse import EventSourceResponse

from sat_simulation import __version__
from sat_simulation.common.clock import SimulationClock
from sat_simulation.common.link import TCPReceiver, TCPTransport
from sat_simulation.common.models import (
    ClockAction,
    ExecutionState,
    FaultRule,
    ImportedScenarioYaml,
    LinkKind,
    MissionAdvance,
    MissionCommand,
    MissionCreate,
    MissionDetail,
    MissionPhase,
    MissionPromptUpdate,
    MissionStatus,
    MissionSummary,
    NodeArtifact,
    NodeKind,
    NodeSnapshot,
    ProcessorExecution,
    ProcessorRuntimeStatus,
    ProcessorStage,
    ProcessorVersion,
    ProcessorWorkspaceCreate,
    ProductLevel,
    ProductManifest,
    ProtocolFrameTrace,
    ProtocolTransaction,
    SatelliteCreateRequest,
    ScenarioConfig,
    ScenarioControl,
    SceneAsset,
    TelemetryEvent,
    TransferRecord,
    TransferStatus,
    default_link_profiles,
    new_id,
    utc_now,
)
from sat_simulation.common.orbit import orbit_track, plan_mission_windows
from sat_simulation.common.protocol import Frame, MessageType
from sat_simulation.common.wire import pack_json, unpack_json, unpack_product
from sat_simulation.config import Settings, settings
from sat_simulation.ground_stations import normalize_satnogs_station
from sat_simulation.omm import extract_omm, omm_hash, omm_to_tle
from sat_simulation.optical.pipeline import ensure_demo_scene, sha256_file
from sat_simulation.optical.scenes import validate_and_convert_scene
from sat_simulation.processors import ProcessorBundleError, inspect_processor_bundle
from sat_simulation.processors.templates import (
    builtin_template,
    source_from_bundle,
    workspace_bundle,
)
from sat_simulation.storage import Repository

PHASE_FLOW: dict[MissionPhase, tuple[MissionPhase, str, str, MissionStatus]] = {
    MissionPhase.INITIALIZED: (
        MissionPhase.UPLINK_COMPLETE,
        "uplink",
        "mission.action.enterUplinkWindow",
        MissionStatus.UPLINKING,
    ),
    MissionPhase.UPLINK_COMPLETE: (
        MissionPhase.CAPTURE_COMPLETE,
        "capture",
        "mission.action.enterCaptureWindow",
        MissionStatus.CAPTURING,
    ),
    MissionPhase.CAPTURE_COMPLETE: (
        MissionPhase.PROCESSING_COMPLETE,
        "processing",
        "mission.action.processProducts",
        MissionStatus.L1A_PROCESSING,
    ),
    MissionPhase.PROCESSING_COMPLETE: (
        MissionPhase.GTX_COMPLETE,
        "gtx",
        "mission.action.transferGtx",
        MissionStatus.GTX_TRANSFER,
    ),
    MissionPhase.GTX_COMPLETE: (
        MissionPhase.AI_COMPLETE,
        "ai",
        "mission.action.runAiAnalysis",
        MissionStatus.AI_PROCESSING,
    ),
    MissionPhase.AI_COMPLETE: (
        MissionPhase.COMPLETED,
        "downlink",
        "mission.action.requestOnboardResult",
        MissionStatus.DOWNLINKING,
    ),
}

logger = logging.getLogger(__name__)
SATNOGS_CATALOG_KEY = "satnogs_ground_stations_v1"


def new_satellite_config(body: SatelliteCreateRequest) -> ScenarioConfig:
    """Validate a user-entered orbit and apply the safe scenario defaults."""
    def valid_tle_line(line: str, line_number: str) -> bool:
        if len(line) != 69 or not line.startswith(f"{line_number} ") or not line[-1].isdigit():
            return False
        checksum = sum(int(char) if char.isdigit() else 1 if char == "-" else 0 for char in line[:68])
        return checksum % 10 == int(line[-1])

    if not valid_tle_line(body.tle_line1, "1") or not valid_tle_line(body.tle_line2, "2"):
        raise ValueError("TLE lines must have valid line numbers and checksums")
    satellite = Satrec.twoline2rv(body.tle_line1, body.tle_line2)
    if satellite.error:
        raise ValueError(f"SGP4 error code {satellite.error}")
    scenario_id = new_id("scenario")
    return ScenarioConfig(
        id=scenario_id,
        name=body.satellite_name,
        satellite_name=body.satellite_name,
        tle_line1=body.tle_line1,
        tle_line2=body.tle_line2,
        ground_station_name=body.ground_station_name,
        ground_station_latitude=body.latitude,
        ground_station_longitude=body.longitude,
        ground_station_altitude_m=body.altitude_m,
        scene_id=f"{scenario_id}-scene",
        scene_ready=False,
    )

# Telemetry stores a stable message key alongside its compatibility message.
# Browser clients translate the key at render time, so event history also
# changes language without rewriting the append-only event log.
EVENT_MESSAGE_KEYS: dict[str, str] = {
    "mission_initialized": "mission.event.initialized",
    "macro_phase_started": "mission.event.phaseStarted",
    "command_received": "mission.event.commandReceived",
    "result_package_received": "mission.event.resultPackageReceived",
    "macro_phase_completed": "mission.event.phaseCompleted",
    "mission_cancelled": "mission.event.cancelled",
    "attitude_maneuver_completed": "mission.event.attitudeManeuverCompleted",
    "raw_stored": "mission.event.rawStored",
    "l0_processing_completed": "mission.event.l0ProcessingCompleted",
    "l1_products_reused": "mission.event.l1ProductsReused",
    "gtx_transfer_completed": "mission.event.gtxTransferCompleted",
    "ai_result_reused": "mission.event.aiResultReused",
    "ai_result_stored": "mission.event.aiResultStored",
    "mission_prompt_updated": "mission.event.promptUpdated",
}


class GroundState:
    def __init__(self, app_settings: Settings) -> None:
        self.settings = app_settings
        self.data_dir = app_settings.data_dir / "ground"
        self.artifact_dir = self.data_dir / "artifacts"
        self.scene_dir = self.data_dir / "scenes"
        self.processor_dir = self.data_dir / "processors"
        self.repo = Repository(app_settings.database_url)
        self.clocks: dict[str, SimulationClock] = {}
        self.receiver = TCPReceiver(self.handle_downlink)
        self.event_conditions: dict[str, asyncio.Condition] = defaultdict(asyncio.Condition)
        self.protocol_conditions: dict[str, asyncio.Condition] = defaultdict(asyncio.Condition)
        self.tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.scene_dir.mkdir(parents=True, exist_ok=True)
        self.processor_dir.mkdir(parents=True, exist_ok=True)
        await self.repo.init()
        await self.ensure_default_scene()
        await self.repo.recover_running_missions()
        await self.receiver.start(self.settings.host, self.settings.ground_downlink_port)
        # Refresh is deliberately detached from startup: cached or manual TLE input
        # remains usable while KeepTrack is unreachable.
        self._track_task(asyncio.create_task(self.refresh_stale_omm_cache()))
        if await self.repo.catalog_status(SATNOGS_CATALOG_KEY) != "complete":
            self._track_task(asyncio.create_task(self.import_satnogs_ground_stations()))

    def _track_task(self, task: asyncio.Task[Any]) -> None:
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def lookup_norad(self, norad_id: int) -> dict[str, Any]:
        if not 1 <= norad_id <= 999999:
            raise ValueError("NORAD id must be between 1 and 999999")
        api_key = (self.settings.keeptrack_api_key or "").strip()
        if not api_key:
            raise PermissionError(
                "KeepTrack API key is not configured. Add it in Settings > Plugin & Keys."
            )
        url = self.settings.keeptrack_api_url.format(norad=norad_id)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(url, headers={"X-API-Key": api_key})
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise LookupError(f"NORAD {norad_id} was not found in KeepTrack") from exc
            raise ConnectionError(
                f"KeepTrack request failed with HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ConnectionError("KeepTrack is unavailable or returned invalid JSON") from exc
        omm = extract_omm(payload, norad_id)
        tle_line1, tle_line2 = omm_to_tle(omm)
        checked_at = datetime.now(UTC)
        satellite_name = omm["OBJECT_NAME"]
        await self.repo.upsert_latest_satellite_omm(
            norad_id=norad_id,
            satellite_name=satellite_name,
            omm_epoch=omm["EPOCH"],
            omm=omm,
            tle_line1=tle_line1,
            tle_line2=tle_line2,
            content_hash=omm_hash(omm),
            checked_at=checked_at,
        )
        return {
            "norad_id": norad_id, "satellite_name": satellite_name, "omm_epoch": omm["EPOCH"],
            "tle_line1": tle_line1, "tle_line2": tle_line2, "checked_at": checked_at,
        }

    async def refresh_stale_omm_cache(self) -> None:
        """Check each cached NORAD at most once per UTC date, after service readiness."""
        if not (self.settings.keeptrack_api_key or "").strip():
            return
        today = datetime.now(UTC).date()
        for entry in await self.repo.cached_latest_satellite_omm():
            checked_at = entry["last_checked_at"]
            if checked_at.tzinfo is None:
                # SQLite does not round-trip timezone metadata despite the column hint.
                checked_at = checked_at.replace(tzinfo=UTC)
            if checked_at.astimezone(UTC).date() >= today:
                continue
            try:
                await self.lookup_norad(entry["norad_id"])
            except Exception:
                logger.warning(
                    "KeepTrack background refresh failed for NORAD %s",
                    entry["norad_id"],
                    exc_info=True,
                )

    async def import_satnogs_ground_stations(self) -> None:
        """Build the local station directory once, without delaying service readiness."""
        if await self.repo.catalog_status(SATNOGS_CATALOG_KEY) == "complete":
            return
        await self.repo.set_catalog_status(SATNOGS_CATALOG_KEY, "importing")
        url = self.settings.satnogs_station_api_url
        visited: set[str] = set()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                while url and url not in visited:
                    visited.add(url)
                    response = await client.get(url, headers={"Accept": "application/json"})
                    response.raise_for_status()
                    payload = response.json()
                    if isinstance(payload, list):
                        candidates = payload
                        next_url = None
                    elif isinstance(payload, dict) and isinstance(payload.get("results"), list):
                        candidates = payload["results"]
                        next_url = payload.get("next")
                    else:
                        raise ValueError("SatNOGS station response is neither a list nor a paginated result")
                    stations: list[dict[str, Any]] = []
                    for candidate in candidates:
                        if not isinstance(candidate, dict):
                            continue
                        try:
                            stations.append(normalize_satnogs_station(candidate))
                        except ValueError:
                            logger.warning("Skipping invalid station payload", exc_info=True)
                    if stations:
                        await self.repo.upsert_satnogs_ground_stations(stations)
                    url = urljoin(str(response.url), str(next_url)) if next_url else ""
            await self.repo.set_catalog_status(SATNOGS_CATALOG_KEY, "complete")
        except Exception as exc:
            await self.repo.set_catalog_status(SATNOGS_CATALOG_KEY, "failed", str(exc))
            logger.warning("Station catalog import failed", exc_info=True)

    async def search_ground_stations(self, name: str) -> dict[str, Any]:
        status = await self.repo.catalog_status(SATNOGS_CATALOG_KEY)
        if status != "complete":
            return {"status": "initializing" if status in (None, "importing") else "failed", "results": []}
        return {
            "status": "ready",
            "results": await self.repo.search_satnogs_ground_stations(name),
        }

    async def ensure_default_scene(self) -> None:
        """Install the versioned Beijing fixture into the writable runtime data."""
        default_id = "scenario-demo-beijing"
        if await self.repo.get_scenario(default_id):
            return
        repository_root = Path(__file__).resolve().parents[2]
        config_dir = self.data_dir / "scenario-configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        source_yaml = repository_root / "scenarios" / "demo-beijing.yaml"
        imported: ImportedScenarioYaml | None = None
        if source_yaml.is_file():
            shutil.copy2(source_yaml, config_dir / source_yaml.name)
            imported = ImportedScenarioYaml.model_validate(
                yaml.safe_load(source_yaml.read_text(encoding="utf-8"))
            )
        scene_path, metadata = ensure_demo_scene(self.scene_dir)
        with rasterio.open(scene_path) as dataset:
            digest = sha256_file(scene_path)
            scene_asset = SceneAsset(
                id=metadata.scene_id,
                scene_id=metadata.scene_id,
                source_name=scene_path.name,
                source_mime_type="image/tiff",
                source_sha256=digest,
                canonical_sha256=digest,
                width=dataset.width,
                height=dataset.height,
                bands=dataset.count,
                crs=str(dataset.crs),
                transform=tuple(dataset.transform),
                conversion={"source": "built-in"},
            )
        await self.repo.add_scene(
            scene_id=metadata.scene_id,
            name="demo-beijing built-in 16-bit GeoTIFF",
            path=str(scene_path),
            sha256=digest,
            metadata=scene_asset.model_dump(mode="json"),
        )
        if imported:
            defaults = default_link_profiles()
            links = {
                kind: defaults[kind].model_copy(
                    update={
                        key: value
                        for key, value in source.model_dump().items()
                        if value is not None
                    }
                )
                for kind, source in (
                    (LinkKind.GTX, imported.links.gtx),
                    (LinkKind.UPLINK, imported.links.uplink),
                    (LinkKind.DOWNLINK, imported.links.downlink),
                )
            }
            links[LinkKind.PAYLOAD_BUS] = defaults[LinkKind.PAYLOAD_BUS]
            config = ScenarioConfig(
                id=default_id,
                name=imported.name,
                seed=imported.seed,
                clock_rate=imported.clock_rate,
                tle_line1=imported.satellite.tle_line1,
                tle_line2=imported.satellite.tle_line2,
                satellite_name=imported.satellite.name,
                ground_station_name=imported.ground_station.id,
                ground_station_latitude=imported.ground_station.latitude,
                ground_station_longitude=imported.ground_station.longitude,
                ground_station_altitude_m=imported.ground_station.altitude_m,
                deterministic_contact=imported.ground_station.simulated,
                scene_id=metadata.scene_id,
                scene_asset_id=scene_asset.id,
                scene_ready=True,
                links=links,
                sensor=imported.sensor,
            )
        else:
            config = ScenarioConfig(
                id=default_id,
                scene_id=metadata.scene_id,
                scene_asset_id=scene_asset.id,
                scene_ready=True,
            )
        clock = SimulationClock(config.epoch, config.clock_rate)
        self.clocks[config.id] = clock
        await self.repo.create_scenario(config, clock.state())

    async def close(self) -> None:
        for task in self.tasks:
            task.cancel()
        await self.receiver.close()
        await self.repo.close()

    async def clock_for(self, scenario_id: str) -> SimulationClock:
        clock = self.clocks.get(scenario_id)
        if clock:
            return clock
        stored = await self.repo.get_scenario(scenario_id)
        if not stored:
            raise KeyError(scenario_id)
        config, saved = stored
        clock = SimulationClock(config.epoch, saved.rate, run_id=saved.run_id)
        await clock.jump_to(saved.simulated_at)
        self.clocks[scenario_id] = clock
        return clock

    async def append_event(self, event: TelemetryEvent) -> None:
        await self.repo.append_event(event)
        condition = self.event_conditions[event.run_id]
        async with condition:
            condition.notify_all()

    async def append_protocol_trace(self, value: ProtocolTransaction | ProtocolFrameTrace) -> None:
        if isinstance(value, ProtocolTransaction):
            await self.repo.upsert_protocol_transaction(value)
            run_id = value.run_id
        else:
            await self.repo.add_protocol_frame(value)
            transaction = await self.repo.get_protocol_transaction(value.transaction_id)
            if not transaction:
                return
            run_id = transaction.run_id
        condition = self.protocol_conditions[run_id]
        async with condition:
            condition.notify_all()

    async def handle_downlink(
        self, message_type: MessageType, payload: bytes, _frame: Frame
    ) -> dict[str, Any]:
        if message_type == MessageType.EVENT:
            event = TelemetryEvent.model_validate(unpack_json(payload))
            await self.append_event(event)
            return {"event_id": event.id, "stored": True}
        if message_type in {MessageType.PRODUCT, MessageType.RESULT_PACKAGE}:
            manifest, content = unpack_product(payload)
            digest = hashlib.sha256(content).hexdigest()
            if digest != manifest.sha256:
                raise ValueError("downlinked product SHA-256 mismatch")
            mission_dir = self.artifact_dir / manifest.mission_id
            mission_dir.mkdir(parents=True, exist_ok=True)
            path = mission_dir / manifest.name
            path.write_bytes(content)
            await self.repo.add_product(manifest, str(path))
            if message_type == MessageType.RESULT_PACKAGE:
                await self.unpack_result_package(manifest, path, mission_dir)
            return {"product_id": manifest.id, "sha256": digest, "stored": True}
        raise ValueError(f"unsupported downlink message type {message_type.name}")

    async def unpack_result_package(
        self, package: ProductManifest, path: Path, mission_dir: Path
    ) -> None:
        extract_dir = mission_dir / "result"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
                raise ValueError("unsafe result package member")
            checksum_content = archive.read("checksums.json")
            expected_checksum = package.processing_parameters.get("members", {}).get(
                "checksums.json"
            )
            if (
                not expected_checksum
                or hashlib.sha256(checksum_content).hexdigest() != expected_checksum
            ):
                raise ValueError("result package checksums.json SHA-256 mismatch")
            checksum_data = json.loads(checksum_content)
            for name, expected in checksum_data.items():
                content = archive.read(name)
                if hashlib.sha256(content).hexdigest() != expected:
                    raise ValueError(f"result package member SHA-256 mismatch: {name}")
                (extract_dir / name).write_bytes(content)
            summary = json.loads((extract_dir / "mission_summary.json").read_text("utf-8"))
            by_name = {item["name"]: item for item in summary.get("products", [])}
            for name in checksum_data:
                value = by_name.get(name)
                if value:
                    product = ProductManifest.model_validate(value)
                    await self.repo.add_product(product, str(extract_dir / name))

    async def animate_to(
        self,
        *,
        mission: dict[str, Any],
        scenario: ScenarioConfig,
        clock: SimulationClock,
        target,
        playback_speed: int,
        label: str,
        status: MissionStatus,
    ) -> None:
        await clock.pause()
        start = clock.now()
        if target < start:
            target = start
        ticks = 12
        delta = (target - start).total_seconds() / ticks
        wall_delay = max(0.0, self.settings.stage_animation_seconds / playback_speed / ticks)
        command: MissionCommand = mission["command"]
        for index in range(1, ticks + 1):
            if delta > 0:
                await clock.step(delta)
            sample = orbit_track(
                scenario,
                clock.now(),
                history_minutes=2,
                forecast_minutes=4,
                pass_horizon_minutes=60,
                step_seconds=30,
            ).current
            await self.repo.update_scenario_clock(command.scenario_id, clock.state())
            await self.append_event(
                TelemetryEvent(
                    run_id=command.run_id,
                    mission_id=command.id,
                    event_type="simulation_tick",
                    status=status,
                    message=label,
                    simulated_at=clock.now(),
                    source="ground-orchestrator",
                    data={
                        "progress": index / ticks,
                        "spacecraft": sample.model_dump(mode="json"),
                        "message_key": label,
                    },
                    channel="simulation_control",
                )
            )
            if wall_delay:
                await asyncio.sleep(wall_delay)

    async def progress_delay(
        self,
        mission: dict[str, Any],
        clock: SimulationClock,
        playback_speed: int,
        label: str,
        status: MissionStatus,
    ) -> None:
        command: MissionCommand = mission["command"]
        ticks = 8
        wall_delay = max(0.0, self.settings.stage_animation_seconds / playback_speed / ticks)
        for index in range(1, ticks + 1):
            await self.append_event(
                TelemetryEvent(
                    run_id=command.run_id,
                    mission_id=command.id,
                    event_type="stage_progress",
                    status=status,
                    message=label,
                    simulated_at=clock.now(),
                    source="ground-orchestrator",
                    data={"progress": index / ticks, "message_key": label},
                )
            )
            if wall_delay:
                await asyncio.sleep(wall_delay)

    async def send_uplink(
        self,
        mission: dict[str, Any],
        scenario: ScenarioConfig,
        clock: SimulationClock,
        message_type: MessageType,
        body: bytes,
        name: str,
    ) -> tuple[Any, TransferRecord]:
        command: MissionCommand = mission["command"]
        faults = await self.repo.list_faults(command.scenario_id)
        fault = next(
            (item for item in faults if item.link == LinkKind.UPLINK and item.enabled), None
        )
        transport = TCPTransport(
            profile=scenario.link_profile(LinkKind.UPLINK),
            clock=clock,
            fault=fault,
            seed=scenario.seed,
            trace_sink=self.append_protocol_trace,
            source_node=NodeKind.GROUND,
            target_node=NodeKind.PLATFORM,
        )
        started = utc_now()
        result = await transport.send(
            self.settings.platform_uplink_host,
            self.settings.platform_uplink_port,
            run_id=command.run_id,
            mission_id=command.id,
            message_type=message_type,
            payload=body,
        )
        record = TransferRecord(
            run_id=command.run_id,
            mission_id=command.id,
            link=LinkKind.UPLINK,
            name=name,
            total_bytes=result.total_bytes,
            transferred_bytes=result.total_bytes,
            frame_count=result.frames,
            retry_count=result.retries,
            crc_failures=result.crc_failures,
            sha256=hashlib.sha256(body).hexdigest(),
            status=TransferStatus.COMPLETED,
            started_at=started,
            completed_at=utc_now(),
            protocol_transaction_id=result.transfer_id,
        )
        await self.repo.add_transfer(record)
        return result, record

    async def run_step(self, mission_id: str, attempt_id: str, playback_speed: int) -> None:
        mission = await self.repo.get_mission(mission_id)
        if not mission:
            return
        command: MissionCommand = mission["command"]
        scenario_stored = await self.repo.get_scenario(command.scenario_id)
        if not scenario_stored or not command.planned_windows:
            return
        scenario = scenario_stored[0]
        clock = await self.clock_for(command.scenario_id)
        phase = MissionPhase(mission["phase"])
        target_phase, stage, label, status = PHASE_FLOW[phase]
        try:
            await self.append_event(
                TelemetryEvent(
                    run_id=command.run_id,
                    mission_id=mission_id,
                    event_type="macro_phase_started",
                    status=status,
                    message=f"单步开始：{label}",
                    simulated_at=clock.now(),
                    source="ground-orchestrator",
                    data={
                        "from_phase": phase,
                        "target_phase": target_phase,
                        "active_substage": stage,
                        "message_key": "mission.event.phaseStarted",
                        "action_key": label,
                    },
                )
            )
            if stage == "uplink":
                await self.animate_to(
                    mission=mission,
                    scenario=scenario,
                    clock=clock,
                    target=command.planned_windows.uplink.max_elevation_at,
                    playback_speed=playback_speed,
                    label="mission.event.enteringUplinkWindow",
                    status=MissionStatus.UPLINKING,
                )
                faults = await self.repo.list_faults(command.scenario_id)
                body = pack_json(
                    {
                        "command": command.model_dump(mode="json"),
                        "scenario": scenario.model_dump(mode="json"),
                        "faults": [item.model_dump(mode="json") for item in faults],
                    }
                )
                _result, record = await self.send_uplink(
                    mission, scenario, clock, MessageType.COMMAND, body, "mission-command.json"
                )
                await self.append_event(
                    TelemetryEvent(
                        run_id=command.run_id,
                        mission_id=mission_id,
                        event_type="command_received",
                        status=MissionStatus.UPLINKING,
                        message="任务指令经真实数传上注，星务已接收并校验。",
                        simulated_at=clock.now(),
                        source="platform-node",
                        data={
                            "record": record.model_dump(mode="json"),
                            "message_key": EVENT_MESSAGE_KEYS["command_received"],
                        },
                        channel="uplink",
                        provenance="measured",
                    )
                )
            elif stage == "capture":
                await self.animate_to(
                    mission=mission,
                    scenario=scenario,
                    clock=clock,
                    target=command.planned_windows.capture.max_elevation_at,
                    playback_speed=playback_speed,
                    label="mission.event.enteringCaptureArea",
                    status=MissionStatus.MANEUVERING,
                )
                await self.call_platform_stage(mission, stage, clock)
            elif stage == "downlink":
                await self.animate_to(
                    mission=mission,
                    scenario=scenario,
                    clock=clock,
                    target=command.planned_windows.downlink.max_elevation_at,
                    playback_speed=playback_speed,
                    label="mission.event.enteringDownlinkWindow",
                    status=MissionStatus.DOWNLINKING,
                )
                body = pack_json({"mission_id": mission_id, "request": "result_package"})
                result, record = await self.send_uplink(
                    mission,
                    scenario,
                    clock,
                    MessageType.RESULT_REQUEST,
                    body,
                    "result-request.json",
                )
                downlink_value = result.response.get("transfer")
                if downlink_value:
                    await self.repo.add_transfer(TransferRecord.model_validate(downlink_value))
                await self.append_event(
                    TelemetryEvent(
                        run_id=command.run_id,
                        mission_id=mission_id,
                        event_type="result_package_received",
                        status=MissionStatus.DOWNLINKING,
                        message="地面按 mission_id 请求，星务结果包已在下一过站窗口下传。",
                        simulated_at=clock.now(),
                        source="ground-station",
                        data={
                            "request_transfer": record.model_dump(mode="json"),
                            "message_key": EVENT_MESSAGE_KEYS["result_package_received"],
                        },
                        channel="downlink",
                        provenance="measured",
                    )
                )
            else:
                await self.progress_delay(mission, clock, playback_speed, label, status)
                await self.call_platform_stage(mission, stage, clock)

            await clock.pause()
            await self.repo.update_scenario_clock(command.scenario_id, clock.state())
            final_state = (
                ExecutionState.COMPLETED
                if target_phase == MissionPhase.COMPLETED
                else ExecutionState.WAITING
            )
            final_status = (
                MissionStatus.COMPLETED if target_phase == MissionPhase.COMPLETED else status
            )
            await self.repo.finish_step(
                mission_id,
                attempt_id,
                phase=target_phase,
                execution_state=final_state,
                status=final_status,
            )
            await self.append_event(
                TelemetryEvent(
                    run_id=command.run_id,
                    mission_id=mission_id,
                    event_type="macro_phase_completed",
                    status=final_status,
                    message="阶段成功 · 仿真已暂停",
                    simulated_at=clock.now(),
                    source="ground-orchestrator",
                    data={
                        "phase": target_phase,
                        "paused": True,
                        "message_key": "mission.event.phaseCompleted",
                    },
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await clock.pause()
            blocked = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 423
            reason = self.platform_error(exc)
            await self.repo.finish_step(
                mission_id,
                attempt_id,
                phase=phase,
                execution_state=ExecutionState.BLOCKED
                if blocked
                else ExecutionState.RETRYABLE_ERROR,
                status=status,
                error=reason,
            )
            await self.append_event(
                TelemetryEvent(
                    run_id=command.run_id,
                    mission_id=mission_id,
                    event_type="macro_phase_blocked" if blocked else "macro_phase_failed",
                    status=status,
                    message=reason,
                    simulated_at=clock.now(),
                    source="ground-orchestrator",
                    data={"phase": phase, "retryable": True},
                )
            )

    @staticmethod
    def platform_error(exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            try:
                return str(exc.response.json().get("detail", exc))
            except ValueError:
                pass
        if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
            return "等待智能载荷响应超时；模型可能仍在 GPU 上执行，可直接重试本步"
        return str(exc) or exc.__class__.__name__

    async def call_platform_stage(
        self, mission: dict[str, Any], stage: str, clock: SimulationClock
    ) -> None:
        command: MissionCommand = mission["command"]
        stage_timeout = max(
            300.0 if stage == "ai" else 60.0,
            self.settings.provider_timeout_seconds + 30,
        )
        async with httpx.AsyncClient(timeout=stage_timeout) as client:
            response = await client.post(
                f"{self.settings.platform_http_url}/internal/missions/{command.id}/advance",
                json={"stage": stage, "simulated_at": clock.now().isoformat()},
            )
            response.raise_for_status()
            body = response.json()
        for value in body.get("events", []):
            event = TelemetryEvent(
                run_id=command.run_id,
                mission_id=command.id,
                event_type=value["event_type"],
                status=value["status"],
                message=value["message"],
                simulated_at=clock.now(),
                source="platform-node",
                data={
                    **value.get("data", {}),
                    "message_key": value.get("data", {}).get("message_key")
                    or EVENT_MESSAGE_KEYS.get(value["event_type"]),
                },
                provenance="derived",
                channel="simulation_control" if stage in {"capture", "processing"} else "gtx",
            )
            await self.append_event(event)
            record_value = event.data.get("record")
            if record_value:
                await self.repo.add_transfer(TransferRecord.model_validate(record_value))


def enrich_mission(mission: dict[str, Any]) -> dict[str, Any]:
    phase = MissionPhase(mission["phase"])
    flow = PHASE_FLOW.get(phase)
    mission["next_action"] = flow[2] if flow else None
    mission["can_advance"] = bool(
        flow
        and not mission.get("legacy_terminal")
        and mission["execution_state"]
        not in {ExecutionState.RUNNING, ExecutionState.COMPLETED, ExecutionState.CANCELLED}
    )
    # The public mission detail is the Ground control-plane view. Product
    # manifests learned from platform events must not be projected into it:
    # RAW/L0 are only observable in the Optical/OBC debug tabs and are
    # not ground-accessible until a RESULT_PACKAGE is actually downlinked.
    mission["onboard_products"] = []
    return mission


def create_app(app_settings: Settings = settings) -> FastAPI:
    state = GroundState(app_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await state.start()
        yield
        await state.close()

    app = FastAPI(
        title="Satellite Simulation Ground Station API", version=__version__, lifespan=lifespan
    )
    app.state.simulation = state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def initialized_mission_for_configuration(
        scenario_id: str,
    ) -> dict[str, Any] | None:
        """Return the pre-flight mission, or reject an already-frozen configuration."""
        active_id = await state.repo.active_mission_for_scenario(scenario_id)
        if not active_id:
            return None
        mission = await state.repo.get_mission(active_id)
        if not mission:
            return None
        if (
            mission["phase"] != MissionPhase.INITIALIZED
            or mission["execution_state"] != ExecutionState.WAITING
        ):
            raise HTTPException(
                409,
                "任务已开始执行，场景资产和 L0/L1 处理器版本已冻结。",
            )
        return mission

    async def processor_snapshots_for(scenario: ScenarioConfig) -> dict[str, dict[str, Any]]:
        snapshots: dict[str, dict[str, Any]] = {}
        for stage, processor_id in (
            (ProcessorStage.L0, scenario.l0_processor_id),
            (ProcessorStage.L1, scenario.l1_processor_id),
        ):
            if processor_id.startswith("builtin-"):
                snapshots[stage.value] = {
                    "id": processor_id,
                    "version": __version__,
                    "sha256": "builtin",
                }
                continue
            processor = await state.repo.get_processor(processor_id)
            if not processor or processor.definition.stage != stage:
                raise HTTPException(409, f"Scenario processor is unavailable: {processor_id}")
            snapshots[stage.value] = processor.model_dump(mode="json")
        return snapshots

    async def refresh_initialized_command(
        mission: dict[str, Any], scenario: ScenarioConfig
    ) -> None:
        """Freeze the latest pre-flight image and processor choices into the mission."""
        scene_record = await state.repo.get_scene(scenario.scene_asset_id or scenario.scene_id)
        if not scene_record:
            raise HTTPException(409, "Scenario image is not ready. Import it in Optical first.")
        try:
            asset = SceneAsset.model_validate(scene_record["metadata"])
        except ValidationError as exc:
            raise HTTPException(409, "Scenario asset metadata is incomplete; import it again.") from exc
        command: MissionCommand = mission["command"].model_copy(deep=True)
        command.scene_id = scenario.scene_id
        command.scene_asset_id = asset.id
        command.scene_asset = asset
        command.l0_processor_id = scenario.l0_processor_id
        command.l1_processor_id = scenario.l1_processor_id
        command.processor_snapshots = await processor_snapshots_for(scenario)
        command.scenario_snapshot = scenario.model_copy(deep=True)
        try:
            await state.repo.update_mission_command(command)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "ground-api",
            "version": __version__,
            "downlink_listener": app_settings.ground_downlink_port,
        }

    @app.get("/api/config")
    async def public_config() -> dict[str, Any]:
        return {
            "version": __version__,
            "ai": {
                "detection": "configured" if app_settings.yolo_api_url else "not_configured",
                "language": "configured" if app_settings.llm_api_url else "not_configured",
            },
            "links": {
                key.value: value.model_dump(mode="json")
                for key, value in default_link_profiles().items()
            },
        }

    @app.get("/api/providers/health")
    async def provider_health() -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.get(f"{app_settings.gpu_http_url}/health")
                response.raise_for_status()
                return response.json()["providers"]
        except Exception as exc:
            return {"status": "unavailable", "reason": str(exc)}

    @app.get("/api/providers/models")
    async def provider_models(provider: str) -> dict[str, Any]:
        if provider != "ollama":
            raise HTTPException(404, "Only ollama model discovery is supported")
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.get(f"{app_settings.gpu_http_url}/internal/providers/ollama/models")
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise HTTPException(503, f"GPU/Ollama unavailable: {exc}") from exc

    async def prepare_scene_asset(
        file: UploadFile,
        scene_id: str,
        center_latitude: float | None,
        center_longitude: float | None,
        pixel_size: float | None,
        crs: str,
        destination: Path,
    ) -> tuple[SceneAsset, bytes]:
        if not file.filename:
            raise HTTPException(400, "Scene filename is required.")
        content = await file.read()
        try:
            asset = await asyncio.to_thread(
                validate_and_convert_scene,
                content,
                filename=file.filename,
                scene_id=scene_id,
                destination=destination,
                center_latitude=center_latitude,
                center_longitude=center_longitude,
                pixel_size=pixel_size,
                crs=crs,
            )
        except ValueError as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(422, str(exc)) from exc
        return asset, content

    @app.post("/api/scenes/validate")
    async def validate_scene(
        file: UploadFile = File(...),
        scene_id: str = Query(..., min_length=1, max_length=120),
        center_latitude: float | None = Query(default=None),
        center_longitude: float | None = Query(default=None),
        pixel_size: float | None = Query(default=None),
        crs: str = Query(default="EPSG:4326"),
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="sat-sim-scene-") as temporary:
            asset, _content = await prepare_scene_asset(
                file,
                scene_id,
                center_latitude,
                center_longitude,
                pixel_size,
                crs,
                Path(temporary) / "scene.tif",
            )
        return {"status": "valid", "asset": asset}

    @app.post("/api/scenes/import")
    async def import_scene(
        file: UploadFile = File(...),
        scene_id: str = Query(..., min_length=1, max_length=120),
        scenario_id: str | None = Query(default=None, min_length=1, max_length=120),
        center_latitude: float | None = Query(default=None),
        center_longitude: float | None = Query(default=None),
        pixel_size: float | None = Query(default=None),
        crs: str = Query(default="EPSG:4326"),
    ) -> dict[str, Any]:
        scenario_config: ScenarioConfig | None = None
        initialized_mission: dict[str, Any] | None = None
        if scenario_id:
            stored = await state.repo.get_scenario(scenario_id)
            if not stored:
                raise HTTPException(404, "Scenario not found.")
            scenario_config, _clock = stored
            if scenario_config.scene_id != scene_id:
                raise HTTPException(422, "scene_id does not match the selected scenario.")
            initialized_mission = await initialized_mission_for_configuration(scenario_id)
        temporary_path = state.scene_dir / f"{new_id('scene_import')}.tif"
        asset, content = await prepare_scene_asset(
            file,
            scene_id,
            center_latitude,
            center_longitude,
            pixel_size,
            crs,
            temporary_path,
        )
        asset.id = new_id("scene_asset")
        path = state.scene_dir / f"{asset.id}.tif"
        temporary_path.replace(path)
        suffix = Path(file.filename or "scene.tif").suffix.lower()
        source_path = state.scene_dir / f"{asset.id}.source{suffix}"
        source_path.write_bytes(content)
        optical_params: dict[str, str | float] = {
            "asset_id": asset.id,
            "scene_id": scene_id,
            "crs": crs,
        }
        for key, value in (
            ("center_latitude", center_latitude),
            ("center_longitude", center_longitude),
            ("pixel_size", pixel_size),
        ):
            if value is not None:
                optical_params[key] = value
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{app_settings.optical_http_url}/internal/scenes",
                    params=optical_params,
                    files={
                        "file": (
                            file.filename,
                            content,
                            file.content_type or "application/octet-stream",
                        )
                    },
                )
                response.raise_for_status()
                remote_asset = SceneAsset.model_validate(response.json())
        except Exception as exc:
            path.unlink(missing_ok=True)
            source_path.unlink(missing_ok=True)
            raise HTTPException(502, f"Optical scene staging failed: {exc}") from exc
        if remote_asset.canonical_sha256 != asset.canonical_sha256:
            path.unlink(missing_ok=True)
            source_path.unlink(missing_ok=True)
            raise HTTPException(502, "Optical scene staging SHA-256 mismatch")
        await state.repo.add_scene(
            scene_id=asset.id,
            name=file.filename or scene_id,
            path=str(path),
            sha256=asset.canonical_sha256,
            metadata=asset.model_dump(mode="json") | {"source_path": str(source_path)},
        )
        if scenario_config:
            scenario_config.scene_ready = True
            scenario_config.scene_asset_id = asset.id
            await state.repo.update_scenario_config(scenario_config)
            if initialized_mission:
                await refresh_initialized_command(initialized_mission, scenario_config)
        return {
            "id": asset.id,
            "sha256": asset.canonical_sha256,
            "metadata": asset,
            "scene_ready": bool(scenario_id),
        }

    @app.get("/api/scenes")
    async def list_scenes() -> list[dict[str, Any]]:
        return await state.repo.list_scenes()

    async def stage_processor_bundle(content: bytes, filename: str) -> ProcessorVersion:
        try:
            definition, digest = inspect_processor_bundle(content)
        except ProcessorBundleError as exc:
            raise HTTPException(422, str(exc)) from exc
        processor_id = f"{definition.id}-{definition.version}-{digest[:12]}"
        target = state.processor_dir / f"{processor_id}.zip"
        target.write_bytes(content)
        base = (
            app_settings.optical_http_url
            if definition.stage == ProcessorStage.L0
            else app_settings.gpu_http_url
        )
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{base}/internal/processors",
                    params={"processor_id": processor_id},
                    files={"file": (filename, content, "application/zip")},
                )
                response.raise_for_status()
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(502, f"Processor staging failed: {exc}") from exc
        processor = ProcessorVersion(
            id=processor_id,
            definition=definition,
            sha256=digest,
            bundle_path=str(target),
            runtime_status=ProcessorRuntimeStatus.READY,
            runtime_type=("desktop-sandbox" if app_settings.oci_runtime == "desktop-sandbox" else "oci"),
        )
        return await state.repo.add_processor(processor)

    @app.get("/api/processors/templates")
    async def processor_template(stage: ProcessorStage) -> dict[str, Any]:
        template = builtin_template(stage)
        return {
            "id": template.definition.id,
            "definition": template.definition,
            "processor_yaml": template.manifest,
            "processor_py": template.source,
            "readonly": True,
        }

    @app.get("/api/processors/{processor_id}/source")
    async def processor_source(processor_id: str) -> dict[str, Any]:
        if processor_id in {"builtin-l0", "builtin-l1"}:
            template = builtin_template(
                ProcessorStage.L0 if processor_id.endswith("l0") else ProcessorStage.L1
            )
            return {
                "id": processor_id,
                "processor_yaml": template.manifest,
                "processor_py": template.source,
                "readonly": True,
            }
        processor = await state.repo.get_processor(processor_id)
        if not processor or not processor.bundle_path:
            raise HTTPException(404, "Processor source not found.")
        try:
            manifest, source = source_from_bundle(processor.bundle_path, processor.definition)
        except (OSError, KeyError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
            raise HTTPException(422, f"Processor source is unreadable: {exc}") from exc
        return {
            "id": processor.id,
            "processor_yaml": manifest,
            "processor_py": source,
            "readonly": False,
        }

    @app.get("/api/processors/{processor_id}/download")
    async def download_processor(processor_id: str) -> Response:
        if processor_id in {"builtin-l0", "builtin-l1"}:
            template = builtin_template(
                ProcessorStage.L0 if processor_id.endswith("l0") else ProcessorStage.L1
            )
            content = workspace_bundle(template.definition, template.source)
            return Response(
                content=content,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{processor_id}.zip"'},
            )
        processor = await state.repo.get_processor(processor_id)
        if not processor or not processor.bundle_path or not Path(processor.bundle_path).is_file():
            raise HTTPException(404, "Processor bundle not found.")
        return FileResponse(
            processor.bundle_path,
            media_type="application/zip",
            filename=f"{processor.id}.zip",
        )

    @app.post("/api/processors/validate")
    async def validate_processor(file: UploadFile = File(...)) -> dict[str, Any]:
        try:
            definition, digest = inspect_processor_bundle(await file.read())
        except ProcessorBundleError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"status": "valid", "definition": definition, "sha256": digest}

    @app.post("/internal/processor-executions", status_code=204)
    async def record_processor_execution(execution: ProcessorExecution) -> None:
        await state.repo.upsert_processor_execution(execution)

    @app.post("/api/processors", response_model=ProcessorVersion)
    async def import_processor(file: UploadFile = File(...)) -> ProcessorVersion:
        return await stage_processor_bundle(await file.read(), file.filename or "processor.zip")

    @app.post("/api/processors/workspace", response_model=ProcessorVersion)
    async def save_processor_workspace(workspace: ProcessorWorkspaceCreate) -> ProcessorVersion:
        template = builtin_template(workspace.stage)
        definition = template.definition.model_copy(
            update={"id": workspace.id, "name": workspace.name, "version": workspace.version}
        )
        try:
            content = workspace_bundle(definition, workspace.source)
        except ProcessorBundleError as exc:
            raise HTTPException(422, str(exc)) from exc
        return await stage_processor_bundle(content, f"{workspace.id}-{workspace.version}.zip")

    @app.get("/api/processors", response_model=list[ProcessorVersion])
    async def list_processors(stage: ProcessorStage | None = None) -> list[ProcessorVersion]:
        return await state.repo.list_processors(stage.value if stage else None)

    @app.get("/api/processors/{processor_id}", response_model=ProcessorVersion)
    async def get_processor(processor_id: str) -> ProcessorVersion:
        processor = await state.repo.get_processor(processor_id)
        if not processor:
            raise HTTPException(404, "Processor not found.")
        return processor

    @app.post("/api/scenarios/{scenario_id}/processors")
    async def select_processors(scenario_id: str, body: dict[str, str]) -> ScenarioConfig:
        stored = await state.repo.get_scenario(scenario_id)
        if not stored:
            raise HTTPException(404, "Scenario not found.")
        initialized_mission = await initialized_mission_for_configuration(scenario_id)
        config, _clock = stored
        for field, stage in (
            ("l0_processor_id", ProcessorStage.L0),
            ("l1_processor_id", ProcessorStage.L1),
        ):
            selected = body.get(field, getattr(config, field))
            if selected not in {"builtin-l0", "builtin-l1"}:
                processor = await state.repo.get_processor(selected)
                if not processor or processor.definition.stage != stage:
                    raise HTTPException(422, f"Invalid {stage.value} processor: {selected}")
            setattr(config, field, selected)
        await state.repo.update_scenario_config(config)
        if initialized_mission:
            await refresh_initialized_command(initialized_mission, config)
        return config

    @app.post("/api/scenarios/import/yaml")
    async def import_scenario_yaml(file: UploadFile = File(...)) -> dict[str, Any]:
        if not file.filename or not file.filename.lower().endswith((".yaml", ".yml")):
            raise HTTPException(400, "Only YAML scenario configuration files are accepted.")
        try:
            payload = yaml.safe_load((await file.read()).decode("utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise HTTPException(422, f"Invalid YAML: {exc}") from exc
        if not isinstance(payload, dict):
            raise HTTPException(422, "Scenario YAML root must be a mapping.")
        try:
            imported = ImportedScenarioYaml.model_validate(payload)
        except ValidationError as exc:
            raise HTTPException(
                422,
                detail=[
                    {"path": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
                    for error in exc.errors()
                ],
            ) from exc
        try:
            satellite = Satrec.twoline2rv(
                imported.satellite.tle_line1, imported.satellite.tle_line2
            )
            if satellite.error:
                raise ValueError(f"SGP4 error code {satellite.error}")
        except Exception as exc:
            raise HTTPException(
                422,
                detail=[{"path": "satellite.tle_line1", "message": f"Invalid TLE: {exc}"}],
            ) from exc
        scenario_id = new_id("scenario")
        scene_id = imported.scene_id or f"{scenario_id}-scene"
        defaults = default_link_profiles()
        links = {
            kind: defaults[kind].model_copy(
                update={
                    key: value for key, value in source.model_dump().items() if value is not None
                }
            )
            for kind, source in (
                (LinkKind.GTX, imported.links.gtx),
                (LinkKind.UPLINK, imported.links.uplink),
                (LinkKind.DOWNLINK, imported.links.downlink),
            )
        }
        links[LinkKind.PAYLOAD_BUS] = defaults[LinkKind.PAYLOAD_BUS]
        config = ScenarioConfig(
            id=scenario_id,
            name=imported.name,
            seed=imported.seed,
            clock_rate=imported.clock_rate,
            tle_line1=imported.satellite.tle_line1,
            tle_line2=imported.satellite.tle_line2,
            satellite_name=imported.satellite.name,
            ground_station_name=imported.ground_station.id,
            ground_station_latitude=imported.ground_station.latitude,
            ground_station_longitude=imported.ground_station.longitude,
            ground_station_altitude_m=imported.ground_station.altitude_m,
            deterministic_contact=imported.ground_station.simulated,
            scene_id=scene_id,
            scene_ready=False,
            links=links,
            sensor=imported.sensor,
        )
        clock = SimulationClock(config.epoch, config.clock_rate)
        state.clocks[config.id] = clock
        await state.repo.create_scenario(config, clock.state())
        config_dir = state.data_dir / "scenario-configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / f"{config.id}.yaml").write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        return {
            "config": config,
            "clock": clock.state(),
            "validation": {"status": "valid", "scene_ready": False, "required_scene_id": scene_id},
        }

    @app.post("/api/scenarios")
    async def create_scenario(config: ScenarioConfig) -> dict[str, Any]:
        if await state.repo.get_scenario(config.id):
            raise HTTPException(409, "Scenario ID already exists.")
        clock = SimulationClock(config.epoch, config.clock_rate)
        state.clocks[config.id] = clock
        await state.repo.create_scenario(config, clock.state())
        return {"config": config, "clock": clock.state()}

    @app.post("/api/scenarios/satellite")
    async def create_satellite_scenario(body: SatelliteCreateRequest) -> dict[str, Any]:
        """Create a basic scenario before its observation scene is uploaded."""
        try:
            config = new_satellite_config(body)
        except Exception as exc:
            raise HTTPException(
                422,
                detail=[{"path": "tle_line1", "message": f"Invalid TLE: {exc}"}],
            ) from exc
        clock = SimulationClock(config.epoch, config.clock_rate)
        state.clocks[config.id] = clock
        await state.repo.create_scenario(config, clock.state())
        return {"config": config, "clock": clock.state()}

    @app.post("/api/satellites/norad/{norad_id}")
    async def lookup_satellite_norad(norad_id: int) -> dict[str, Any]:
        """Fetch the current KeepTrack OMM and return its TLE representation."""
        try:
            return await state.lookup_norad(norad_id)
        except PermissionError as exc:
            raise HTTPException(412, str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except ConnectionError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.get("/api/ground-stations")
    async def search_ground_stations(name: str = Query(min_length=1, max_length=120)) -> dict[str, Any]:
        """Search the initialized local SatNOGS directory; never performs a live lookup."""
        return await state.search_ground_stations(name)

    @app.get("/api/scenarios")
    async def list_scenarios() -> list[dict[str, Any]]:
        return await state.repo.list_scenarios()

    @app.get("/api/scenarios/{scenario_id}/orbit")
    async def get_scenario_orbit(scenario_id: str):
        stored = await state.repo.get_scenario(scenario_id)
        if not stored:
            raise HTTPException(404, "Scenario not found.")
        return orbit_track(stored[0], (await state.clock_for(scenario_id)).now())

    @app.post("/api/scenarios/{scenario_id}/control")
    async def control_scenario(scenario_id: str, control: ScenarioControl) -> dict[str, Any]:
        active = await state.repo.active_mission_for_scenario(scenario_id)
        if active and control.action in {ClockAction.START, ClockAction.RESUME, ClockAction.STEP}:
            raise HTTPException(409, "存在活动任务，请使用任务单步按钮推进仿真")
        try:
            clock = await state.clock_for(scenario_id)
        except KeyError as exc:
            raise HTTPException(404, "Scenario not found.") from exc
        if control.action in {ClockAction.START, ClockAction.RESUME}:
            result = await clock.resume()
        elif control.action == ClockAction.PAUSE:
            result = await clock.pause()
        elif control.action == ClockAction.STEP:
            result = await clock.step(control.step_seconds)
        elif control.action == ClockAction.SET_RATE:
            result = await clock.set_rate(control.rate or 1)
        elif control.action == ClockAction.RESET:
            stored = await state.repo.get_scenario(scenario_id)
            result = await clock.reset(stored[0].epoch if stored else None)
        else:
            raise HTTPException(400, "Unsupported control action.")
        await state.repo.update_scenario_clock(scenario_id, result)
        return {"clock": result}

    @app.post("/api/missions", status_code=201, response_model=MissionDetail)
    async def create_mission(request: MissionCreate) -> MissionDetail:
        stored = await state.repo.get_scenario(request.scenario_id)
        if not stored:
            raise HTTPException(404, "Scenario not found.")
        active = await state.repo.active_mission_for_scenario(request.scenario_id)
        if active:
            raise HTTPException(409, f"场景已有非终态任务 {active}")
        scenario = stored[0]
        if not scenario.scene_ready:
            raise HTTPException(
                409, "Scenario image is not ready. Import the matching 16-bit GeoTIFF first."
            )
        scene_record = await state.repo.get_scene(scenario.scene_asset_id or scenario.scene_id)
        if not scene_record:
            raise HTTPException(409, "Scenario asset is not registered.")
        try:
            scene_asset = SceneAsset.model_validate(scene_record["metadata"])
        except ValidationError as exc:
            raise HTTPException(
                409, "Scenario asset metadata is incomplete; import it again."
            ) from exc
        processor_snapshots: dict[str, dict[str, Any]] = {}
        for stage, processor_id in (
            (ProcessorStage.L0, scenario.l0_processor_id),
            (ProcessorStage.L1, scenario.l1_processor_id),
        ):
            if processor_id.startswith("builtin-"):
                processor_snapshots[stage.value] = {
                    "id": processor_id,
                    "version": __version__,
                    "sha256": "builtin",
                }
                continue
            processor = await state.repo.get_processor(processor_id)
            if not processor or processor.definition.stage != stage:
                raise HTTPException(409, f"Scenario processor is unavailable: {processor_id}")
            processor_snapshots[stage.value] = processor.model_dump(mode="json")
        plan = plan_mission_windows(scenario, max(scenario.epoch, utc_now()))
        clock = await state.clock_for(request.scenario_id)
        initial = plan.uplink.aos - timedelta(minutes=5)
        new_clock = await clock.reset(initial)
        await state.repo.update_scenario_clock(request.scenario_id, new_clock)
        command = MissionCommand(
            run_id=new_clock.run_id,
            scenario_id=request.scenario_id,
            name=request.name,
            target_name=plan.target_name,
            target_latitude=plan.target_latitude,
            target_longitude=plan.target_longitude,
            scene_id=scenario.scene_id,
            scene_asset_id=scene_asset.id,
            scene_asset=scene_asset,
            l0_processor_id=scenario.l0_processor_id,
            l1_processor_id=scenario.l1_processor_id,
            processor_snapshots=processor_snapshots,
            enable_ai=True,
            ai_mode=request.ai_mode,
            ai_model=request.ai_model,
            project_context=request.project_context,
            analysis_prompt=request.analysis_prompt,
            scenario_snapshot=scenario,
            planned_windows=plan,
        )
        await state.repo.create_mission(command)
        await state.append_event(
            TelemetryEvent(
                run_id=command.run_id,
                mission_id=command.id,
                event_type="mission_initialized",
                status=MissionStatus.PLANNED,
                message="任务与真实轨道窗口已规划，仿真保持暂停。",
                simulated_at=clock.now(),
                source="ground-orchestrator",
                data={
                    "planned_windows": plan.model_dump(mode="json"),
                    "ai_mode": request.ai_mode,
                    "ai_model": request.ai_model,
                    "message_key": EVENT_MESSAGE_KEYS["mission_initialized"],
                },
            )
        )
        return MissionDetail.model_validate(
            enrich_mission((await state.repo.get_mission(command.id)) or {})
        )

    @app.patch("/api/missions/{mission_id}/prompt", response_model=MissionDetail)
    async def update_mission_prompt(
        mission_id: str, request: MissionPromptUpdate
    ) -> MissionDetail:
        """Allow an LLM instruction to change until its AI step begins."""
        mission = await state.repo.get_mission(mission_id)
        if not mission:
            raise HTTPException(404, "Mission not found.")
        command: MissionCommand = mission["command"]
        if command.ai_mode.value != "llm":
            raise HTTPException(409, "只有 LLM 任务可以修改分析 Prompt。")
        if mission.get("active_substage") == "ai" or mission["phase"] in {
            MissionPhase.AI_COMPLETE,
            MissionPhase.COMPLETED,
        }:
            raise HTTPException(409, "LLM 分析已开始，任务 Prompt 已冻结。")

        updated = command.model_copy(update={"analysis_prompt": request.analysis_prompt.strip()})
        # The platform owns the command copy used to build AI_EXECUTE.  Once
        # uplink has happened, synchronize it before committing Ground's copy.
        if mission["phase"] != MissionPhase.INITIALIZED:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.patch(
                        f"{app_settings.platform_http_url}/internal/missions/{mission_id}/prompt",
                        json={"analysis_prompt": updated.analysis_prompt},
                    )
                    response.raise_for_status()
            except httpx.HTTPError as exc:
                raise HTTPException(502, f"无法同步星务平台 Prompt：{exc}") from exc
        try:
            await state.repo.update_mission_analysis_prompt(updated)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

        await state.append_event(
            TelemetryEvent(
                run_id=updated.run_id,
                mission_id=updated.id,
                event_type="mission_prompt_updated",
                status=mission["status"],
                message="LLM 分析 Prompt 已更新，AI 分析步骤前仍可继续修改。",
                simulated_at=(await state.clock_for(updated.scenario_id)).now(),
                source="ground-orchestrator",
                data={"message_key": EVENT_MESSAGE_KEYS["mission_prompt_updated"]},
                channel="simulation_control",
            )
        )
        return MissionDetail.model_validate(
            enrich_mission((await state.repo.get_mission(mission_id)) or {})
        )

    @app.post("/api/missions/{mission_id}/advance", status_code=202)
    async def advance_mission(mission_id: str, request: MissionAdvance) -> dict[str, Any]:
        mission = await state.repo.get_mission(mission_id)
        if not mission:
            raise HTTPException(404, "Mission not found.")
        key = f"{mission_id}:{request.idempotency_key or uuid4().hex}"
        previous = await state.repo.get_attempt_by_idempotency_key(key)
        if previous:
            previous_action = PHASE_FLOW[previous.from_phase][2]
            return {
                "mission_id": mission_id,
                "attempt": previous,
                "duplicate": True,
                "action": previous_action,
            }
        phase = MissionPhase(mission["phase"])
        if phase not in PHASE_FLOW:
            raise HTTPException(409, "任务已经完成")
        target_phase, stage, label, _status = PHASE_FLOW[phase]
        try:
            attempt, duplicate = await state.repo.begin_step(
                mission_id,
                target_phase=target_phase,
                idempotency_key=key,
                active_substage=stage,
            )
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not duplicate:
            task = asyncio.create_task(
                state.run_step(mission_id, attempt.id, request.playback_speed)
            )
            state.tasks.add(task)
            task.add_done_callback(state.tasks.discard)
        return {
            "mission_id": mission_id,
            "attempt": attempt,
            "duplicate": duplicate,
            "action": label,
        }

    @app.post("/api/missions/{mission_id}/cancel", response_model=MissionDetail)
    async def cancel_mission(mission_id: str) -> MissionDetail:
        mission = await state.repo.get_mission(mission_id)
        if not mission:
            raise HTTPException(404, "Mission not found.")
        if mission["execution_state"] == ExecutionState.RUNNING:
            raise HTTPException(409, "任务阶段正在执行，不能结束；请等待本阶段停止")
        if mission["execution_state"] not in {
            ExecutionState.COMPLETED,
            ExecutionState.CANCELLED,
        }:
            clock = await state.clock_for(mission["command"].scenario_id)
            paused_clock = await clock.pause()
            await state.repo.update_scenario_clock(mission["command"].scenario_id, paused_clock)
            await state.repo.cancel_mission(mission_id)
            await state.append_event(
                TelemetryEvent(
                    run_id=mission["command"].run_id,
                    mission_id=mission_id,
                    event_type="mission_cancelled",
                    status=MissionStatus.CANCELLED,
                    message="当前任务已由用户结束；历史事件与星上产品保留。",
                    simulated_at=clock.now(),
                    source="ground-orchestrator",
                    data={
                        "phase_when_cancelled": mission["phase"],
                        "message_key": EVENT_MESSAGE_KEYS["mission_cancelled"],
                    },
                )
            )
        return MissionDetail.model_validate(
            enrich_mission((await state.repo.get_mission(mission_id)) or {})
        )

    @app.get("/api/missions", response_model=list[MissionSummary])
    async def list_missions() -> list[MissionSummary]:
        return [
            MissionSummary.model_validate(enrich_mission(item))
            for item in await state.repo.list_missions()
        ]

    @app.get("/api/missions/{mission_id}", response_model=MissionDetail)
    async def get_mission(mission_id: str) -> MissionDetail:
        mission = await state.repo.get_mission(mission_id)
        if not mission:
            raise HTTPException(404, "Mission not found.")
        return MissionDetail.model_validate(enrich_mission(mission))

    @app.get("/api/missions/{mission_id}/nodes/{node}", response_model=NodeSnapshot)
    async def get_node_snapshot(mission_id: str, node: NodeKind) -> NodeSnapshot:
        mission = await state.repo.get_mission(mission_id)
        if not mission:
            raise HTTPException(404, "Mission not found.")
        if node == NodeKind.GROUND:
            artifacts = [
                NodeArtifact(
                    key=item.id,
                    name=item.name,
                    level=item.level,
                    mime_type=item.mime_type,
                    size_bytes=item.size_bytes,
                    sha256=item.sha256,
                    observation_only=False,
                    previewable=item.level
                    in {ProductLevel.THUMBNAIL, ProductLevel.STAC, ProductLevel.AI_RESULT},
                )
                for item in mission["products"]
                if item.artifact_path
            ]
            return NodeSnapshot(
                node=node,
                mission_id=mission_id,
                status=str(mission["phase"]),
                state={
                    "phase": mission["phase"],
                    "execution_state": mission["execution_state"],
                    "downlinked_products": len(artifacts),
                    "last_event": mission["events"][-1].model_dump(mode="json")
                    if mission["events"]
                    else None,
                },
                artifacts=artifacts,
            )
        base = {
            NodeKind.GPU: app_settings.gpu_http_url,
            NodeKind.OPTICAL: app_settings.optical_http_url,
            NodeKind.PLATFORM: app_settings.platform_http_url,
        }[node]
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(
                    f"{base}/internal/missions/{mission_id}/nodes/{node.value}"
                )
                response.raise_for_status()
            return NodeSnapshot.model_validate(response.json())
        except Exception as exc:
            return NodeSnapshot(
                node=node,
                mission_id=mission_id,
                reachable=False,
                status="unavailable",
                observation_notice="节点当前不可达；地面任务控制仍可使用。",
                state={"reason": state.platform_error(exc)},
            )

    @app.get("/api/missions/{mission_id}/nodes/{node}/artifacts/{key}")
    async def get_node_artifact(mission_id: str, node: NodeKind, key: str):
        if node == NodeKind.GROUND:
            manifest = await state.repo.get_product(key)
            if not manifest or manifest.mission_id != mission_id or not manifest.artifact_path:
                raise HTTPException(404, "Artifact not found.")
            path = Path(manifest.artifact_path).resolve()
            if not path.is_file() or state.artifact_dir.resolve() not in path.parents:
                raise HTTPException(404, "Artifact not found.")
            return FileResponse(path, media_type=manifest.mime_type, filename=manifest.name)
        base = {
            NodeKind.GPU: app_settings.gpu_http_url,
            NodeKind.OPTICAL: app_settings.optical_http_url,
            NodeKind.PLATFORM: app_settings.platform_http_url,
        }[node]
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{base}/internal/missions/{mission_id}/nodes/{node.value}/artifacts/{key}"
                )
                response.raise_for_status()
            headers = {
                "Content-Disposition": response.headers.get(
                    "Content-Disposition", f'attachment; filename="{key}"'
                )
            }
            from fastapi.responses import Response

            return Response(
                response.content,
                media_type=response.headers.get("Content-Type", "application/octet-stream"),
                headers=headers,
            )
        except Exception as exc:
            raise HTTPException(
                404, f"Observation artifact unavailable: {state.platform_error(exc)}"
            ) from exc

    @app.get("/api/missions/{mission_id}/result")
    async def get_mission_result(mission_id: str) -> dict[str, Any]:
        mission = await state.repo.get_mission(mission_id)
        if not mission:
            raise HTTPException(404, "Mission not found.")
        if mission["phase"] != MissionPhase.COMPLETED:
            raise HTTPException(409, "结果包尚未在下一过站窗口下传")
        products = [
            item
            for item in mission["products"]
            if item.level
            in {
                ProductLevel.RESULT_PACKAGE,
                ProductLevel.AI_RESULT,
                ProductLevel.L1B,
                ProductLevel.STAC,
                ProductLevel.THUMBNAIL,
            }
        ]
        ai = next((item for item in products if item.level == ProductLevel.AI_RESULT), None)
        ai_result = (
            json.loads(Path(ai.artifact_path).read_text("utf-8"))
            if ai and ai.artifact_path
            else None
        )
        return {"mission_id": mission_id, "ai_result": ai_result, "products": products}

    @app.post("/api/scenarios/{scenario_id}/faults")
    async def add_fault(scenario_id: str, rule: FaultRule) -> FaultRule:
        if not await state.repo.get_scenario(scenario_id):
            raise HTTPException(404, "Scenario not found.")
        await state.repo.add_fault(scenario_id, rule)
        return rule

    @app.get("/api/scenarios/{scenario_id}/faults")
    async def list_faults(scenario_id: str) -> list[FaultRule]:
        return await state.repo.list_faults(scenario_id)

    @app.delete("/api/scenarios/{scenario_id}/faults/{fault_id}", status_code=204)
    async def delete_fault(scenario_id: str, fault_id: str) -> None:
        if not await state.repo.delete_fault(scenario_id, fault_id):
            raise HTTPException(404, "Fault rule not found.")

    @app.get("/api/transfers")
    async def list_transfers(run_id: str | None = None) -> list[TransferRecord]:
        return await state.repo.list_transfers(run_id)

    @app.post("/internal/observation/protocol", include_in_schema=False)
    async def ingest_protocol_trace(body: dict[str, Any]) -> dict[str, bool]:
        if body.get("kind") == "transaction":
            value: ProtocolTransaction | ProtocolFrameTrace = ProtocolTransaction.model_validate(
                body.get("value")
            )
        elif body.get("kind") == "frame":
            value = ProtocolFrameTrace.model_validate(body.get("value"))
        else:
            raise HTTPException(400, "unknown trace kind")
        await state.append_protocol_trace(value)
        return {"stored": True}

    @app.get(
        "/api/missions/{mission_id}/protocol/transactions",
        response_model=list[ProtocolTransaction],
    )
    async def list_protocol_transactions(mission_id: str) -> list[ProtocolTransaction]:
        if not await state.repo.get_mission(mission_id):
            raise HTTPException(404, "Mission not found.")
        return await state.repo.list_protocol_transactions(mission_id)

    @app.get("/api/protocol/transactions/{transaction_id}", response_model=ProtocolTransaction)
    async def get_protocol_transaction(transaction_id: str) -> ProtocolTransaction:
        value = await state.repo.get_protocol_transaction(transaction_id)
        if not value:
            raise HTTPException(404, "Protocol transaction not found.")
        return value

    @app.get(
        "/api/protocol/transactions/{transaction_id}/frames",
        response_model=list[ProtocolFrameTrace],
    )
    async def get_protocol_frames(transaction_id: str) -> list[ProtocolFrameTrace]:
        if not await state.repo.get_protocol_transaction(transaction_id):
            raise HTTPException(404, "Protocol transaction not found.")
        return await state.repo.list_protocol_frames(transaction_id)

    @app.get("/api/protocol/stream")
    async def stream_protocol(run_id: str):
        async def generate():
            known: dict[str, str] = {}
            known_frames: set[str] = set()
            while True:
                missions = await state.repo.list_missions()
                mission_ids = [
                    item["command"].id for item in missions if item["command"].run_id == run_id
                ]
                for mission_id in mission_ids:
                    for transaction in reversed(
                        await state.repo.list_protocol_transactions(mission_id)
                    ):
                        serialized = transaction.model_dump_json()
                        if known.get(transaction.id) != serialized:
                            known[transaction.id] = serialized
                            yield {"event": "protocol", "data": serialized}
                        for frame in await state.repo.list_protocol_frames(transaction.id):
                            if frame.id not in known_frames:
                                known_frames.add(frame.id)
                                yield {
                                    "event": "protocol_frame",
                                    "data": frame.model_dump_json(),
                                }
                try:
                    async with state.protocol_conditions[run_id]:
                        await asyncio.wait_for(state.protocol_conditions[run_id].wait(), timeout=10)
                except TimeoutError:
                    yield {"event": "keepalive", "data": json.dumps({"count": len(known)})}

        return EventSourceResponse(generate())

    @app.get("/api/products/{product_id}/manifest")
    async def get_product_manifest(product_id: str):
        manifest = await state.repo.get_product(product_id)
        if not manifest:
            raise HTTPException(404, "Product not found.")
        return manifest

    @app.get("/api/artifacts/{product_id}")
    async def get_artifact(product_id: str):
        manifest = await state.repo.get_product(product_id)
        if not manifest or not manifest.artifact_path:
            raise HTTPException(404, "Artifact not found.")
        path = Path(manifest.artifact_path)
        if not path.is_file() or state.artifact_dir.resolve() not in path.resolve().parents:
            raise HTTPException(404, "Artifact not found.")
        return FileResponse(path, media_type=manifest.mime_type, filename=manifest.name)

    @app.get("/api/events/stream")
    async def stream_events(run_id: str, after: int = 0):
        async def generate():
            sequence = after
            while True:
                events = await state.repo.events_after(run_id, sequence)
                for event in events:
                    sequence = max(sequence, event.sequence)
                    yield {
                        "event": "telemetry",
                        "id": str(event.sequence),
                        "data": event.model_dump_json(),
                    }
                try:
                    async with state.event_conditions[run_id]:
                        await asyncio.wait_for(state.event_conditions[run_id].wait(), timeout=10)
                except TimeoutError:
                    yield {"event": "keepalive", "data": json.dumps({"sequence": sequence})}

        return EventSourceResponse(generate())

    return app


app = create_app()
