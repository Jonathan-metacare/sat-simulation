from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import rasterio
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from sat_simulation import __version__
from sat_simulation.common.clock import SimulationClock
from sat_simulation.common.link import TCPReceiver, TCPTransport
from sat_simulation.common.models import (
    ClockAction,
    FaultRule,
    LinkKind,
    MissionCommand,
    MissionCreate,
    MissionStatus,
    ScenarioConfig,
    ScenarioControl,
    TelemetryEvent,
    TransferRecord,
    TransferStatus,
    default_link_profiles,
    utc_now,
)
from sat_simulation.common.protocol import Frame, MessageType
from sat_simulation.common.wire import pack_json, unpack_json, unpack_product
from sat_simulation.config import Settings, settings
from sat_simulation.optical.pipeline import sha256_file
from sat_simulation.storage import Repository


class GroundState:
    def __init__(self, app_settings: Settings) -> None:
        self.settings = app_settings
        self.data_dir = app_settings.data_dir / "ground"
        self.artifact_dir = self.data_dir / "artifacts"
        self.scene_dir = self.data_dir / "scenes"
        self.repo = Repository(app_settings.database_url)
        self.clocks: dict[str, SimulationClock] = {}
        self.receiver = TCPReceiver(self.handle_downlink)
        self.event_conditions: dict[str, asyncio.Condition] = defaultdict(asyncio.Condition)

    async def start(self) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.scene_dir.mkdir(parents=True, exist_ok=True)
        await self.repo.init()
        await self.receiver.start(self.settings.host, self.settings.ground_downlink_port)

    async def close(self) -> None:
        await self.receiver.close()
        await self.repo.close()

    async def clock_for(self, scenario_id: str) -> SimulationClock:
        clock = self.clocks.get(scenario_id)
        if clock:
            return clock
        stored = await self.repo.get_scenario(scenario_id)
        if not stored:
            raise KeyError(scenario_id)
        config, state = stored
        clock = SimulationClock(config.epoch, state.rate)
        self.clocks[scenario_id] = clock
        return clock

    async def handle_downlink(
        self, message_type: MessageType, payload: bytes, frame: Frame
    ) -> dict[str, Any]:
        if message_type == MessageType.EVENT:
            event = TelemetryEvent.model_validate(unpack_json(payload))
            await self.repo.append_event(event)
            if event.event_type == "transfer_completed":
                records = event.data.get("records", [])
                if isinstance(records, list):
                    for value in records:
                        await self.repo.add_transfer(TransferRecord.model_validate(value))
            if event.mission_id and event.status in {item.value for item in MissionStatus}:
                await self.repo.update_mission(event.mission_id, event.status)
            condition = self.event_conditions[event.run_id]
            async with condition:
                condition.notify_all()
            return {"event_id": event.id, "stored": True}
        if message_type == MessageType.PRODUCT:
            manifest, content = unpack_product(payload)
            digest = hashlib.sha256(content).hexdigest()
            if digest != manifest.sha256:
                raise ValueError("downlinked product SHA-256 mismatch")
            mission_dir = self.artifact_dir / manifest.mission_id
            mission_dir.mkdir(parents=True, exist_ok=True)
            path = mission_dir / manifest.name
            path.write_bytes(content)
            await self.repo.add_product(manifest, str(path))
            return {"product_id": manifest.id, "sha256": digest, "stored": True}
        raise ValueError(f"unsupported downlink message type {message_type.name}")

    async def dispatch_mission(
        self,
        command: MissionCommand,
        scenario: ScenarioConfig,
        faults: list[FaultRule],
    ) -> None:
        clock = await self.clock_for(command.scenario_id)
        try:
            if clock.state().paused:
                await clock.resume()
                await self.repo.update_scenario_clock(command.scenario_id, clock.state())
            fault = next(
                (item for item in faults if item.link == LinkKind.UPLINK and item.enabled), None
            )
            transport = TCPTransport(
                profile=default_link_profiles()[LinkKind.UPLINK],
                clock=clock,
                fault=fault,
                seed=scenario.seed,
            )
            await self.repo.update_mission(command.id, MissionStatus.UPLINKING)
            body = pack_json(
                {
                    "command": command.model_dump(mode="json"),
                    "scenario": scenario.model_dump(mode="json"),
                    "faults": [item.model_dump(mode="json") for item in faults],
                }
            )
            result = await transport.send(
                self.settings.platform_uplink_host,
                self.settings.platform_uplink_port,
                run_id=command.run_id,
                mission_id=command.id,
                message_type=MessageType.COMMAND,
                payload=body,
            )
            record = TransferRecord(
                run_id=command.run_id,
                mission_id=command.id,
                link=LinkKind.UPLINK,
                name="mission-command.json",
                total_bytes=result.total_bytes,
                transferred_bytes=result.total_bytes,
                frame_count=result.frames,
                retry_count=result.retries,
                crc_failures=result.crc_failures,
                sha256=hashlib.sha256(body).hexdigest(),
                status=TransferStatus.COMPLETED,
                started_at=utc_now(),
                completed_at=utc_now(),
            )
            await self.repo.add_transfer(record)
        except Exception as exc:
            await self.repo.update_mission(command.id, MissionStatus.FAILED, str(exc))
            event = TelemetryEvent(
                run_id=command.run_id,
                mission_id=command.id,
                event_type="uplink_failed",
                status=MissionStatus.FAILED,
                message=f"指令上注失败：{exc}",
                simulated_at=clock.now(),
                source="ground-station",
                data={"error": str(exc)},
            )
            await self.repo.append_event(event)


def create_app(app_settings: Settings = settings) -> FastAPI:
    state = GroundState(app_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await state.start()
        yield
        await state.close()

    app = FastAPI(
        title="Satellite Simulation Ground Station API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.simulation = state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
                "detection": "not_configured" if not app_settings.yolo_api_url else "configured",
                "language": "not_configured" if not app_settings.llm_api_url else "configured",
            },
            "links": {
                key.value: value.model_dump(mode="json")
                for key, value in default_link_profiles().items()
            },
        }

    @app.post("/api/scenes/import")
    async def import_scene(
        file: UploadFile = File(...),
        scene_id: str = Query(..., min_length=1, max_length=120),
    ) -> dict[str, Any]:
        if not file.filename or not file.filename.lower().endswith((".tif", ".tiff")):
            raise HTTPException(400, "Only 16-bit GeoTIFF scenes are accepted.")
        path = state.scene_dir / f"{scene_id}.tif"
        content = await file.read()
        path.write_bytes(content)
        try:
            with rasterio.open(path) as src:
                if src.dtypes[0] != "uint16":
                    raise ValueError("scene must use uint16 samples")
                metadata = {
                    "width": src.width,
                    "height": src.height,
                    "bands": src.count,
                    "crs": str(src.crs),
                    "transform": tuple(src.transform),
                }
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise HTTPException(400, f"Invalid GeoTIFF: {exc}") from exc

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{app_settings.platform_http_url}/internal/scenes",
                    params={"scene_id": scene_id},
                    files={"file": (path.name, content, "image/tiff")},
                )
                response.raise_for_status()
        except Exception as exc:
            raise HTTPException(503, f"Scene saved but platform staging failed: {exc}") from exc
        digest = sha256_file(path)
        await state.repo.add_scene(
            scene_id=scene_id,
            name=file.filename,
            path=str(path),
            sha256=digest,
            metadata=metadata,
        )
        return {"id": scene_id, "sha256": digest, "metadata": metadata}

    @app.post("/api/scenarios")
    async def create_scenario(config: ScenarioConfig) -> dict[str, Any]:
        if await state.repo.get_scenario(config.id):
            raise HTTPException(409, "Scenario ID already exists.")
        clock = SimulationClock(config.epoch, config.clock_rate)
        state.clocks[config.id] = clock
        await state.repo.create_scenario(config, clock.state())
        return {"config": config, "clock": clock.state()}

    @app.get("/api/scenarios")
    async def list_scenarios() -> list[dict[str, Any]]:
        return await state.repo.list_scenarios()

    @app.post("/api/scenarios/{scenario_id}/control")
    async def control_scenario(scenario_id: str, control: ScenarioControl) -> dict[str, Any]:
        try:
            clock = await state.clock_for(scenario_id)
        except KeyError as exc:
            raise HTTPException(404, "Scenario not found.") from exc
        if control.action in {ClockAction.START, ClockAction.RESUME}:
            result = await clock.resume()
        elif control.action == ClockAction.PAUSE:
            result = await clock.pause()
        elif control.action == ClockAction.STEP:
            try:
                result = await clock.step(control.step_seconds)
            except RuntimeError as exc:
                raise HTTPException(409, str(exc)) from exc
        elif control.action == ClockAction.SET_RATE:
            result = await clock.set_rate(control.rate or 1)
        elif control.action == ClockAction.RESET:
            stored = await state.repo.get_scenario(scenario_id)
            result = await clock.reset(stored[0].epoch if stored else None)
        else:
            raise HTTPException(400, "Unsupported control action.")
        await state.repo.update_scenario_clock(scenario_id, result)
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                await client.post(
                    f"{app_settings.platform_http_url}/internal/control",
                    json={"scenario_id": scenario_id, "control": control.model_dump(mode="json")},
                )
        except Exception:
            pass
        return {"clock": result}

    @app.post("/api/missions", status_code=202)
    async def create_mission(request: MissionCreate) -> dict[str, Any]:
        stored = await state.repo.get_scenario(request.scenario_id)
        if not stored:
            raise HTTPException(404, "Scenario not found.")
        scenario, _clock_state = stored
        clock = await state.clock_for(request.scenario_id)
        command = MissionCommand(
            run_id=clock.state().run_id,
            scenario_id=request.scenario_id,
            name=request.name,
            target_name=request.target_name,
            target_latitude=request.target_latitude,
            target_longitude=request.target_longitude,
            scene_id=request.scene_id,
            enable_ai=request.enable_ai,
        )
        await state.repo.create_mission(command)
        faults = await state.repo.list_faults(request.scenario_id)
        asyncio.create_task(state.dispatch_mission(command, scenario, faults))
        return {"mission_id": command.id, "run_id": command.run_id, "status": "planned"}

    @app.get("/api/missions")
    async def list_missions() -> list[dict[str, Any]]:
        return await state.repo.list_missions()

    @app.get("/api/missions/{mission_id}")
    async def get_mission(mission_id: str) -> dict[str, Any]:
        mission = await state.repo.get_mission(mission_id)
        if not mission:
            raise HTTPException(404, "Mission not found.")
        return mission

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
                condition = state.event_conditions[run_id]
                try:
                    async with condition:
                        await asyncio.wait_for(condition.wait(), timeout=10)
                except TimeoutError:
                    yield {"event": "keepalive", "data": json.dumps({"sequence": sequence})}

        return EventSourceResponse(generate())

    return app


app = create_app()
