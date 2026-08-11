from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import rasterio
from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from sat_simulation import __version__
from sat_simulation.common.clock import SimulationClock
from sat_simulation.common.link import TCPReceiver, TCPTransport
from sat_simulation.common.models import (
    ClockAction,
    FaultRule,
    LinkKind,
    MissionCommand,
    MissionStatus,
    ProductLevel,
    ScenarioConfig,
    ScenarioControl,
    TelemetryEvent,
    TransferRecord,
    TransferStatus,
    default_link_profiles,
)
from sat_simulation.common.orbit import target_attitude
from sat_simulation.common.protocol import Frame, MessageType
from sat_simulation.common.wire import pack_json, pack_product, unpack_json
from sat_simulation.config import Settings, settings
from sat_simulation.optical.pipeline import (
    OpticalPipeline,
    SceneMetadata,
    SensorConfig,
    ensure_demo_scene,
)


class PlatformState:
    def __init__(self, app_settings: Settings) -> None:
        self.settings = app_settings
        self.data_dir = app_settings.data_dir / "platform"
        self.scene_dir = self.data_dir / "scenes"
        self.product_dir = self.data_dir / "products"
        self.receiver = TCPReceiver(self.handle_uplink)
        self.clocks: dict[str, SimulationClock] = {}
        self.scenarios: dict[str, ScenarioConfig] = {}
        self.faults: dict[str, list[FaultRule]] = {}
        self.tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        self.scene_dir.mkdir(parents=True, exist_ok=True)
        self.product_dir.mkdir(parents=True, exist_ok=True)
        ensure_demo_scene(self.scene_dir)
        await self.receiver.start(self.settings.host, self.settings.platform_uplink_port)

    async def close(self) -> None:
        for task in self.tasks:
            task.cancel()
        await self.receiver.close()

    async def handle_uplink(
        self, message_type: MessageType, payload: bytes, frame: Frame
    ) -> dict[str, Any]:
        if message_type == MessageType.CONTROL:
            body = unpack_json(payload)
            await self.apply_control(
                body["scenario_id"], ScenarioControl.model_validate(body["control"])
            )
            return {"controlled": True}
        if message_type != MessageType.COMMAND:
            raise ValueError(f"unsupported uplink message type {message_type.name}")
        body = unpack_json(payload)
        command = MissionCommand.model_validate(body["command"])
        scenario = ScenarioConfig.model_validate(body["scenario"])
        faults = [FaultRule.model_validate(item) for item in body.get("faults", [])]
        self.scenarios[scenario.id] = scenario
        self.faults[scenario.id] = faults
        clock = self.clocks.get(scenario.id)
        if not clock:
            clock = SimulationClock(scenario.epoch, scenario.clock_rate)
            self.clocks[scenario.id] = clock
        await clock.resume()
        task = asyncio.create_task(self.execute(command, scenario, clock, faults))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return {"accepted": True, "mission_id": command.id}

    async def apply_control(self, scenario_id: str, control: ScenarioControl) -> None:
        clock = self.clocks.get(scenario_id)
        if not clock:
            return
        if control.action in {ClockAction.START, ClockAction.RESUME}:
            await clock.resume()
        elif control.action == ClockAction.PAUSE:
            await clock.pause()
        elif control.action == ClockAction.STEP:
            await clock.step(control.step_seconds)
        elif control.action == ClockAction.SET_RATE:
            await clock.set_rate(control.rate or 1)
        elif control.action == ClockAction.RESET:
            scenario = self.scenarios.get(scenario_id)
            await clock.reset(scenario.epoch if scenario else None)

    def fault_for(self, faults: list[FaultRule], kind: LinkKind) -> FaultRule | None:
        return next((item for item in faults if item.link == kind and item.enabled), None)

    async def event(
        self,
        command: MissionCommand,
        clock: SimulationClock,
        faults: list[FaultRule],
        *,
        event_type: str,
        status: MissionStatus,
        message: str,
        data: dict[str, Any] | None = None,
        provenance: str = "simulated",
    ) -> None:
        event = TelemetryEvent(
            run_id=command.run_id,
            mission_id=command.id,
            event_type=event_type,
            status=status,
            message=message,
            simulated_at=clock.now(),
            source="platform-node",
            data=data or {},
            provenance=provenance,
        )
        transport = TCPTransport(
            profile=default_link_profiles()[LinkKind.DOWNLINK],
            clock=clock,
            fault=self.fault_for(faults, LinkKind.DOWNLINK),
            seed=self.scenarios[command.scenario_id].seed,
        )
        await transport.send(
            self.settings.ground_downlink_host,
            self.settings.ground_downlink_port,
            run_id=command.run_id,
            mission_id=command.id,
            message_type=MessageType.EVENT,
            payload=pack_json(event.model_dump(mode="json")),
        )

    async def execute(
        self,
        command: MissionCommand,
        scenario: ScenarioConfig,
        clock: SimulationClock,
        faults: list[FaultRule],
    ) -> None:
        try:
            await self.event(
                command,
                clock,
                faults,
                event_type="command_received",
                status=MissionStatus.UPLINKING,
                message="星务平台已接收并校验任务指令。",
            )
            await clock.sleep(1)
            await self.event(
                command,
                clock,
                faults,
                event_type="attitude_maneuver_started",
                status=MissionStatus.MANEUVERING,
                message="开始目标指向姿态机动。",
            )
            await clock.sleep(3)
            spacecraft = target_attitude(
                scenario,
                clock.now(),
                command.target_latitude,
                command.target_longitude,
                pointing_error_deg=0.05,
            )
            if spacecraft.pointing_error_deg > 0.1:
                raise RuntimeError("pointing error exceeds optical capture threshold")
            if not spacecraft.in_contact:
                raise RuntimeError("deterministic contact window is not open")
            await self.event(
                command,
                clock,
                faults,
                event_type="optical_capture_started",
                status=MissionStatus.CAPTURING,
                message="姿态满足约束，光学载荷开始曝光。",
                data={"spacecraft": spacecraft.model_dump(mode="json")},
                provenance="derived",
            )
            await clock.sleep(2)

            scene_path = self.scene_dir / f"{command.scene_id}.tif"
            if not scene_path.exists():
                raise FileNotFoundError(f"scene {command.scene_id} is not staged on platform")
            with rasterio.open(scene_path) as src:
                bounds = src.bounds
                scene = SceneMetadata(
                    scene_id=command.scene_id,
                    target_name=command.target_name,
                    center_latitude=(bounds.top + bounds.bottom) / 2,
                    center_longitude=(bounds.left + bounds.right) / 2,
                    pixel_size_deg=abs(src.transform.a),
                    crs=str(src.crs or "EPSG:4326"),
                )
            mission_dir = self.product_dir / command.id
            pipeline = OpticalPipeline(SensorConfig(seed=scenario.seed))
            await self.event(
                command,
                clock,
                faults,
                event_type="l0_processing_started",
                status=MissionStatus.L0_PROCESSING,
                message="重组 RAW 分包并生成 L0。",
            )
            products = await asyncio.to_thread(
                pipeline.process,
                scene_path=scene_path,
                scene=scene,
                output_dir=mission_dir,
                run_id=command.run_id,
                mission_id=command.id,
                captured_at=clock.now(),
                spacecraft_state=spacecraft.model_dump(mode="json"),
            )
            await self.event(
                command,
                clock,
                faults,
                event_type="l1a_processing_completed",
                status=MissionStatus.L1A_PROCESSING,
                message="L1A 已附加时间、轨姿与定标辅助数据。",
            )
            l1b_manifest = next(
                item for item in products.manifests if item.level == ProductLevel.L1B
            )
            await self.event(
                command,
                clock,
                faults,
                event_type="l1b_processing_completed",
                status=MissionStatus.L1B_PROCESSING,
                message="L1B 辐射校正和地理参考产品已生成。",
                data={"manifest": l1b_manifest.model_dump(mode="json")},
                provenance="derived",
            )

            await self.event(
                command,
                clock,
                faults,
                event_type="gtx_transfer_started",
                status=MissionStatus.GTX_TRANSFER,
                message="经 Virtual GTX 向 GPU 载荷发送 L1B。",
            )
            gtx = TCPTransport(
                profile=default_link_profiles()[LinkKind.GTX],
                clock=clock,
                fault=self.fault_for(faults, LinkKind.GTX),
                seed=scenario.seed,
            )
            gtx_result = await gtx.send(
                self.settings.gpu_gtx_host,
                self.settings.gpu_gtx_port,
                run_id=command.run_id,
                mission_id=command.id,
                message_type=MessageType.AI_JOB,
                payload=pack_product(l1b_manifest, products.paths[ProductLevel.L1B]),
            )
            gtx_record = TransferRecord(
                run_id=command.run_id,
                mission_id=command.id,
                link=LinkKind.GTX,
                name=l1b_manifest.name,
                total_bytes=gtx_result.total_bytes,
                transferred_bytes=gtx_result.total_bytes,
                frame_count=gtx_result.frames,
                retry_count=gtx_result.retries,
                crc_failures=gtx_result.crc_failures,
                sha256=l1b_manifest.sha256,
                status=TransferStatus.COMPLETED,
                started_at=clock.now(),
                completed_at=clock.now(),
            )
            detection = gtx_result.response.get("detection", {})
            await self.event(
                command,
                clock,
                faults,
                event_type="ai_provider_skipped",
                status=MissionStatus.AI_SKIPPED,
                message="GPU 已校验 L1B；本地模型服务未配置，AI 阶段诚实跳过。",
                data={
                    "gtx": {
                        "bytes": gtx_result.total_bytes,
                        "frames": gtx_result.frames,
                        "retries": gtx_result.retries,
                        "crc_failures": gtx_result.crc_failures,
                    },
                    "detection": detection,
                },
                provenance="placeholder",
            )

            await self.event(
                command,
                clock,
                faults,
                event_type="downlink_started",
                status=MissionStatus.DOWNLINKING,
                message="在可见窗口内开始下传产品。",
            )
            downlink = TCPTransport(
                profile=default_link_profiles()[LinkKind.DOWNLINK],
                clock=clock,
                fault=self.fault_for(faults, LinkKind.DOWNLINK),
                seed=scenario.seed,
            )
            transfer_records = [gtx_record]
            for manifest in products.manifests:
                path = Path(manifest.artifact_path or "")
                downlink_result = await downlink.send(
                    self.settings.ground_downlink_host,
                    self.settings.ground_downlink_port,
                    run_id=command.run_id,
                    mission_id=command.id,
                    message_type=MessageType.PRODUCT,
                    payload=pack_product(manifest, path),
                )
                transfer_records.append(
                    TransferRecord(
                        run_id=command.run_id,
                        mission_id=command.id,
                        link=LinkKind.DOWNLINK,
                        name=manifest.name,
                        total_bytes=downlink_result.total_bytes,
                        transferred_bytes=downlink_result.total_bytes,
                        frame_count=downlink_result.frames,
                        retry_count=downlink_result.retries,
                        crc_failures=downlink_result.crc_failures,
                        sha256=manifest.sha256,
                        status=TransferStatus.COMPLETED,
                        started_at=clock.now(),
                        completed_at=clock.now(),
                    )
                )
            await self.event(
                command,
                clock,
                faults,
                event_type="transfer_completed",
                status=MissionStatus.DOWNLINKING,
                message="GTX 与产品下传事务均已完成并通过完整性校验。",
                data={"records": [record.model_dump(mode="json") for record in transfer_records]},
                provenance="derived",
            )
            await self.event(
                command,
                clock,
                faults,
                event_type="mission_completed",
                status=MissionStatus.COMPLETED,
                message="任务、产品校验与下传全部完成。",
                data={"product_count": len(products.manifests)},
                provenance="derived",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                await self.event(
                    command,
                    clock,
                    faults,
                    event_type="mission_failed",
                    status=MissionStatus.FAILED,
                    message=f"任务失败：{exc}",
                    data={"error": str(exc)},
                )
            except Exception:
                pass


def create_app(app_settings: Settings = settings) -> FastAPI:
    state = PlatformState(app_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await state.start()
        yield
        await state.close()

    app = FastAPI(title="Satellite Platform Node", version=__version__, lifespan=lifespan)
    app.state.platform = state

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "platform-node",
            "version": __version__,
            "uplink_listener": app_settings.platform_uplink_port,
            "payloads": {
                "optical": "ready",
                "infrared": "not_implemented",
            },
        }

    @app.post("/internal/control")
    async def control(body: dict[str, Any]) -> dict[str, bool]:
        await state.apply_control(
            str(body["scenario_id"]), ScenarioControl.model_validate(body["control"])
        )
        return {"ok": True}

    @app.post("/internal/scenes")
    async def stage_scene(
        scene_id: str = Query(..., min_length=1, max_length=120),
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        content = await file.read()
        path = state.scene_dir / f"{scene_id}.tif"
        path.write_bytes(content)
        try:
            with rasterio.open(path) as src:
                if src.dtypes[0] != "uint16":
                    raise ValueError("scene must use uint16 samples")
                shape = [src.count, src.height, src.width]
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise HTTPException(400, f"invalid scene: {exc}") from exc
        return {"id": scene_id, "sha256": hashlib.sha256(content).hexdigest(), "shape": shape}

    return app


app = create_app()
