from __future__ import annotations

import asyncio
import hashlib
import json
import zipfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import rasterio
from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from sat_simulation import __version__
from sat_simulation.common.clock import SimulationClock
from sat_simulation.common.link import RemoteTransferError, TCPReceiver, TCPTransport
from sat_simulation.common.models import (
    FaultRule,
    LinkKind,
    MissionCommand,
    MissionPhase,
    MissionStatus,
    ProductLevel,
    ProductManifest,
    ScenarioConfig,
    TransferRecord,
    TransferStatus,
    default_link_profiles,
    utc_now,
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
    sha256_file,
)


class PlatformState:
    def __init__(self, app_settings: Settings) -> None:
        self.settings = app_settings
        self.data_dir = app_settings.data_dir / "platform"
        self.scene_dir = self.data_dir / "scenes"
        self.product_dir = self.data_dir / "products"
        self.task_dir = self.data_dir / "tasks"
        self.uplink_receiver = TCPReceiver(self.handle_uplink)
        self.result_receiver = TCPReceiver(self.handle_ai_result)
        self.missions: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        self.scene_dir.mkdir(parents=True, exist_ok=True)
        self.product_dir.mkdir(parents=True, exist_ok=True)
        self.task_dir.mkdir(parents=True, exist_ok=True)
        ensure_demo_scene(self.scene_dir)
        for path in self.task_dir.glob("*/state.json"):
            try:
                self.missions[path.parent.name] = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                continue
        await self.uplink_receiver.start(self.settings.host, self.settings.platform_uplink_port)
        await self.result_receiver.start(self.settings.host, self.settings.platform_gtx_result_port)

    async def close(self) -> None:
        await self.uplink_receiver.close()
        await self.result_receiver.close()

    def persist(self, mission_id: str) -> None:
        directory = self.task_dir / mission_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "state.json").write_text(
            json.dumps(self.missions[mission_id], ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def fault_for(self, state: dict[str, Any], kind: LinkKind) -> FaultRule | None:
        faults = [FaultRule.model_validate(value) for value in state.get("faults", [])]
        return next((item for item in faults if item.link == kind and item.enabled), None)

    def clock_for(self, simulated_at: datetime) -> SimulationClock:
        return SimulationClock(simulated_at.astimezone(UTC), rate=1)

    async def handle_uplink(
        self, message_type: MessageType, payload: bytes, frame: Frame
    ) -> dict[str, Any]:
        body = unpack_json(payload)
        if message_type == MessageType.COMMAND:
            command = MissionCommand.model_validate(body["command"])
            scenario = ScenarioConfig.model_validate(body["scenario"])
            self.missions[command.id] = {
                "command": command.model_dump(mode="json"),
                "scenario": scenario.model_dump(mode="json"),
                "faults": body.get("faults", []),
                "phase": MissionPhase.UPLINK_COMPLETE,
                "products": {},
                "received_at": datetime.now(UTC).isoformat(),
                "clock": {
                    "run_id": command.run_id,
                    "simulated_at": datetime.fromtimestamp(
                        frame.simulated_time_ns / 1_000_000_000, tz=UTC
                    ).isoformat(),
                    "paused": True,
                },
            }
            self.persist(command.id)
            return {"accepted": True, "mission_id": command.id, "phase": "uplink_complete"}
        if message_type == MessageType.RESULT_REQUEST:
            mission_id = str(body.get("mission_id"))
            state = self.missions.get(mission_id)
            if not state:
                raise ValueError("mission_id is not stored on platform")
            if state.get("phase") != MissionPhase.AI_COMPLETE:
                raise ValueError("AI result is not ready for downlink")
            record, manifest = await self.downlink_result_package(mission_id, state)
            state["phase"] = MissionPhase.COMPLETED
            state["clock"] = {
                "run_id": state["command"]["run_id"],
                "simulated_at": datetime.fromtimestamp(
                    frame.simulated_time_ns / 1_000_000_000, tz=UTC
                ).isoformat(),
                "paused": True,
            }
            state["result_package"] = manifest.model_dump(mode="json")
            self.persist(mission_id)
            return {
                "accepted": True,
                "mission_id": mission_id,
                "result_package_sha256": manifest.sha256,
                "transfer": record.model_dump(mode="json"),
            }
        raise ValueError(f"unsupported uplink message type {message_type.name}")

    async def handle_ai_result(
        self, message_type: MessageType, payload: bytes, _frame: Frame
    ) -> dict[str, Any]:
        if message_type != MessageType.AI_RESULT:
            raise ValueError(f"unsupported GTX result type {message_type.name}")
        body = unpack_json(payload)
        mission_id = str(body["mission_id"])
        state = self.missions.get(mission_id)
        if not state:
            raise ValueError("unknown mission in AI_RESULT")
        expected = str(body.pop("sha256"))
        content = pack_json(body)
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError("AI_RESULT SHA-256 mismatch")
        directory = self.product_dir / mission_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{mission_id}_ai_result.json"
        path.write_bytes(content)
        manifest = ProductManifest(
            run_id=str(body["run_id"]),
            mission_id=mission_id,
            level=ProductLevel.AI_RESULT,
            name=path.name,
            mime_type="application/json",
            size_bytes=path.stat().st_size,
            sha256=expected,
            processing_parameters={"ai_mode": body["ai_mode"]},
            quality={"verified": True},
            lineage=[state["products"][ProductLevel.L1B]["name"]],
            artifact_path=str(path),
        )
        state["ai_result"] = body
        state["products"][ProductLevel.AI_RESULT] = manifest.model_dump(mode="json")
        self.persist(mission_id)
        return {"stored": True, "sha256": expected}

    def scene_metadata(self, command: MissionCommand) -> tuple[Path, SceneMetadata]:
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
        return scene_path, scene

    async def advance(self, mission_id: str, body: dict[str, Any]) -> dict[str, Any]:
        state = self.missions.get(mission_id)
        if not state:
            raise HTTPException(409, "星务尚未收到该任务指令")
        stage = str(body["stage"])
        simulated_at = datetime.fromisoformat(str(body["simulated_at"]).replace("Z", "+00:00"))
        command = MissionCommand.model_validate(state["command"])
        scenario = ScenarioConfig.model_validate(state["scenario"])
        mission_dir = self.product_dir / mission_id
        mission_dir.mkdir(parents=True, exist_ok=True)
        pipeline = OpticalPipeline(SensorConfig(seed=scenario.seed))
        events: list[dict[str, Any]] = []

        if stage == "capture":
            if state["phase"] not in {MissionPhase.UPLINK_COMPLETE, MissionPhase.CAPTURE_COMPLETE}:
                raise HTTPException(409, "星务任务阶段不允许拍摄")
            spacecraft = target_attitude(
                scenario,
                simulated_at,
                command.target_latitude,
                command.target_longitude,
                pointing_error_deg=0.05,
            )
            if spacecraft.pointing_error_deg > 0.1:
                raise HTTPException(409, "姿态指向误差超过拍摄阈值")
            scene_path, _scene = self.scene_metadata(command)
            manifest, path = await asyncio.to_thread(
                pipeline.capture_raw,
                scene_path=scene_path,
                output_dir=mission_dir,
                run_id=command.run_id,
                mission_id=mission_id,
            )
            state["spacecraft"] = spacecraft.model_dump(mode="json")
            state["captured_at"] = simulated_at.isoformat()
            state["products"][ProductLevel.RAW] = manifest.model_dump(mode="json")
            state["products"][ProductLevel.RAW]["artifact_path"] = str(path)
            state["phase"] = MissionPhase.CAPTURE_COMPLETE
            events.extend(
                [
                    {
                        "event_type": "attitude_maneuver_completed",
                        "status": MissionStatus.MANEUVERING,
                        "message": "姿态机动完成，目标进入视场。",
                        "data": {"spacecraft": spacecraft.model_dump(mode="json")},
                    },
                    {
                        "event_type": "raw_stored",
                        "status": MissionStatus.CAPTURING,
                        "message": "曝光完成，RAW 分包数据已保存到星务卷。",
                        "data": {"manifest": manifest.model_dump(mode="json")},
                    },
                ]
            )

        elif stage == "processing":
            if state["phase"] not in {
                MissionPhase.CAPTURE_COMPLETE,
                MissionPhase.PROCESSING_COMPLETE,
            }:
                raise HTTPException(409, "星务任务阶段不允许产品处理")
            scene_path, scene = self.scene_metadata(command)
            products = await asyncio.to_thread(
                pipeline.process,
                scene_path=scene_path,
                scene=scene,
                output_dir=mission_dir,
                run_id=command.run_id,
                mission_id=mission_id,
                captured_at=datetime.fromisoformat(state["captured_at"]),
                spacecraft_state=state["spacecraft"],
            )
            state["products"] = {
                item.level: item.model_dump(mode="json") for item in products.manifests
            }
            state["phase"] = MissionPhase.PROCESSING_COMPLETE
            for level, status in [
                (ProductLevel.L0, MissionStatus.L0_PROCESSING),
                (ProductLevel.L1A, MissionStatus.L1A_PROCESSING),
                (ProductLevel.L1B, MissionStatus.L1B_PROCESSING),
            ]:
                events.append(
                    {
                        "event_type": f"{level.value}_processing_completed",
                        "status": status,
                        "message": f"{level.value.upper()} 产品处理并保存成功。",
                        "data": {"manifest": state["products"][level]},
                    }
                )

        elif stage == "gtx":
            if state["phase"] not in {MissionPhase.PROCESSING_COMPLETE, MissionPhase.GTX_COMPLETE}:
                raise HTTPException(409, "星务任务阶段不允许 GTX 传输")
            manifest = ProductManifest.model_validate(state["products"][ProductLevel.L1B])
            clock = self.clock_for(simulated_at)
            transport = TCPTransport(
                profile=default_link_profiles()[LinkKind.GTX],
                clock=clock,
                fault=self.fault_for(state, LinkKind.GTX),
                seed=scenario.seed,
            )
            transfer = await transport.send(
                self.settings.gpu_gtx_host,
                self.settings.gpu_gtx_port,
                run_id=command.run_id,
                mission_id=mission_id,
                message_type=MessageType.AI_JOB,
                payload=pack_product(manifest, Path(str(manifest.artifact_path))),
            )
            if transfer.response.get("received_sha256") != manifest.sha256:
                raise HTTPException(502, "GPU 返回的 L1B SHA-256 不一致")
            state["phase"] = MissionPhase.GTX_COMPLETE
            record = self.transfer_record(
                command, LinkKind.GTX, manifest.name, manifest.sha256, transfer
            )
            events.append(
                {
                    "event_type": "gtx_transfer_completed",
                    "status": MissionStatus.GTX_TRANSFER,
                    "message": "L1B 已经真实 GTX 字节流传至 GPU 并校验。",
                    "data": {"record": record.model_dump(mode="json")},
                }
            )

        elif stage == "ai":
            if state["phase"] not in {MissionPhase.GTX_COMPLETE, MissionPhase.AI_COMPLETE}:
                raise HTTPException(409, "星务任务阶段不允许智能分析")
            clock = self.clock_for(simulated_at)
            transport = TCPTransport(profile=default_link_profiles()[LinkKind.GTX], clock=clock)
            try:
                transfer = await transport.send(
                    self.settings.gpu_gtx_host,
                    self.settings.gpu_gtx_port,
                    run_id=command.run_id,
                    mission_id=mission_id,
                    message_type=MessageType.AI_EXECUTE,
                    payload=pack_json(
                        {
                            "mission_id": mission_id,
                            "run_id": command.run_id,
                            "ai_mode": command.ai_mode,
                            "options": {},
                        }
                    ),
                )
            except RemoteTransferError as exc:
                if exc.code == "provider_blocked":
                    raise HTTPException(423, str(exc)) from exc
                raise
            if "ai_result" not in state:
                raise HTTPException(502, "GPU 未通过 GTX 回传 AI_RESULT")
            state["phase"] = MissionPhase.AI_COMPLETE
            events.append(
                {
                    "event_type": "ai_result_stored",
                    "status": MissionStatus.AI_PROCESSING,
                    "message": "GPU 模型结果已通过 GTX 回传并由星务持久化。",
                    "data": {"result": state["ai_result"], "gtx_bytes": transfer.total_bytes},
                }
            )
        else:
            raise HTTPException(400, "unknown platform stage")

        state["clock"] = {
            "run_id": command.run_id,
            "simulated_at": simulated_at.isoformat(),
            "paused": True,
        }
        self.persist(mission_id)
        return {
            "phase": state["phase"],
            "events": events,
            "products": list(state["products"].values()),
        }

    @staticmethod
    def transfer_record(
        command: MissionCommand, link: LinkKind, name: str, sha256: str, result
    ) -> TransferRecord:
        return TransferRecord(
            run_id=command.run_id,
            mission_id=command.id,
            link=link,
            name=name,
            total_bytes=result.total_bytes,
            transferred_bytes=result.total_bytes,
            frame_count=result.frames,
            retry_count=result.retries,
            crc_failures=result.crc_failures,
            sha256=sha256,
            status=TransferStatus.COMPLETED,
            started_at=utc_now(),
            completed_at=utc_now(),
        )

    async def downlink_result_package(
        self, mission_id: str, state: dict[str, Any]
    ) -> tuple[TransferRecord, ProductManifest]:
        command = MissionCommand.model_validate(state["command"])
        scenario = ScenarioConfig.model_validate(state["scenario"])
        directory = self.product_dir / mission_id
        package_path = directory / f"{mission_id}_result_package.zip"
        include_levels = [ProductLevel.AI_RESULT, ProductLevel.THUMBNAIL, ProductLevel.STAC]
        member_index: dict[str, str] = {}
        summary = {
            "mission_id": mission_id,
            "run_id": command.run_id,
            "ai_mode": command.ai_mode,
            "planned_windows": command.planned_windows.model_dump(mode="json")
            if command.planned_windows
            else None,
            "products": list(state["products"].values()),
        }
        summary_path = directory / "mission_summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            files = [summary_path]
            for level in include_levels:
                value = state["products"].get(level)
                if value and value.get("artifact_path"):
                    files.append(Path(value["artifact_path"]))
            for file_path in files:
                digest = sha256_file(file_path)
                member_index[file_path.name] = digest
                archive.write(file_path, file_path.name)
            checksums_content = json.dumps(member_index, sort_keys=True).encode("utf-8")
            archive.writestr("checksums.json", checksums_content)
            member_index["checksums.json"] = hashlib.sha256(checksums_content).hexdigest()
        manifest = ProductManifest(
            run_id=command.run_id,
            mission_id=mission_id,
            level=ProductLevel.RESULT_PACKAGE,
            name=package_path.name,
            mime_type="application/zip",
            size_bytes=package_path.stat().st_size,
            sha256=sha256_file(package_path),
            processing_parameters={"members": member_index},
            quality={"member_sha256_verified": True},
            lineage=list(member_index),
            artifact_path=str(package_path),
        )
        clock = self.clock_for(
            command.planned_windows.downlink.max_elevation_at
            if command.planned_windows
            else utc_now()
        )
        transport = TCPTransport(
            profile=default_link_profiles()[LinkKind.DOWNLINK],
            clock=clock,
            fault=self.fault_for(state, LinkKind.DOWNLINK),
            seed=scenario.seed,
        )
        result = await transport.send(
            self.settings.ground_downlink_host,
            self.settings.ground_downlink_port,
            run_id=command.run_id,
            mission_id=mission_id,
            message_type=MessageType.RESULT_PACKAGE,
            payload=pack_product(manifest, package_path),
        )
        return self.transfer_record(
            command, LinkKind.DOWNLINK, manifest.name, manifest.sha256, result
        ), manifest


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
            "gtx_result_listener": app_settings.platform_gtx_result_port,
            "payloads": {"optical": "ready", "infrared": "not_implemented"},
        }

    @app.post("/internal/missions/{mission_id}/advance")
    async def advance(mission_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await state.advance(mission_id, body)

    @app.get("/internal/missions/{mission_id}")
    async def mission_state(mission_id: str) -> dict[str, Any]:
        value = state.missions.get(mission_id)
        if not value:
            raise HTTPException(404, "mission not found")
        return value

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
