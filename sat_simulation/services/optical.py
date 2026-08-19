from __future__ import annotations

import asyncio
import json
import shutil
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import rasterio
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from sat_simulation import __version__
from sat_simulation.common.clock import SimulationClock
from sat_simulation.common.link import TCPReceiver, TCPTransport
from sat_simulation.common.models import (
    LinkKind,
    MissionCommand,
    NodeArtifact,
    NodeKind,
    NodeSnapshot,
    ProcessorExecution,
    ProcessorRuntimeStatus,
    ProcessorStage,
    ProductLevel,
    ProductManifest,
    ProtocolFrameTrace,
    ProtocolTransaction,
    ScenarioConfig,
    utc_now,
)
from sat_simulation.common.protocol import Frame, MessageType
from sat_simulation.common.wire import pack_product, unpack_json
from sat_simulation.config import Settings, settings
from sat_simulation.optical.pipeline import (
    OpticalPipeline,
    SensorConfig,
    ensure_demo_scene,
    sha256_file,
)
from sat_simulation.optical.scenes import validate_and_convert_scene
from sat_simulation.processors import ProcessorBlocked, ProcessorRunner, inspect_processor_bundle


class OpticalState:
    def __init__(self, app_settings: Settings) -> None:
        self.settings = app_settings
        self.data_dir = app_settings.data_dir / "optical"
        self.scene_dir = self.data_dir / "scenes"
        self.product_dir = self.data_dir / "products"
        self.processor_dir = self.data_dir / "processors"
        self.receiver = TCPReceiver(self.handle_request)
        self.jobs: dict[str, dict[str, Any]] = {}
        self.runner = ProcessorRunner(
            runtime=app_settings.oci_runtime, image=app_settings.processor_image
        )

    async def start(self) -> None:
        self.scene_dir.mkdir(parents=True, exist_ok=True)
        self.product_dir.mkdir(parents=True, exist_ok=True)
        self.processor_dir.mkdir(parents=True, exist_ok=True)
        demo_path, _metadata = ensure_demo_scene(self.scene_dir)
        alias = self.scene_dir / "demo-optical-scene.tif"
        if demo_path != alias and not alias.exists():
            shutil.copyfile(demo_path, alias)
        for state_path in self.product_dir.glob("*/state.json"):
            try:
                self.jobs[state_path.parent.name] = json.loads(state_path.read_text("utf-8"))
            except (OSError, ValueError):
                continue
        await self.receiver.start(self.settings.host, self.settings.optical_payload_port)

    async def close(self) -> None:
        await self.receiver.close()

    async def report_trace(self, value: ProtocolTransaction | ProtocolFrameTrace) -> None:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                await client.post(
                    f"{self.settings.ground_http_url}/internal/observation/protocol",
                    json={
                        "kind": "transaction"
                        if isinstance(value, ProtocolTransaction)
                        else "frame",
                        "value": value.model_dump(mode="json"),
                    },
                )
        except Exception:
            return

    async def report_execution(self, execution: ProcessorExecution) -> None:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                await client.post(
                    f"{self.settings.ground_http_url}/internal/processor-executions",
                    json=execution.model_dump(mode="json"),
                )
        except Exception:
            return

    def persist(self, mission_id: str) -> None:
        directory = self.product_dir / mission_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "state.json").write_text(
            json.dumps(self.jobs[mission_id], ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def scene_path(self, scene_id: str) -> Path:
        path = self.scene_dir / f"{scene_id}.tif"
        if not path.is_file():
            raise FileNotFoundError(f"scene {scene_id} is not staged on optical payload")
        return path

    async def _return_product(
        self,
        *,
        command: MissionCommand,
        scenario: ScenarioConfig,
        simulated_at: datetime,
        message_type: MessageType,
        manifest: ProductManifest,
        path: Path,
    ) -> dict[str, Any]:
        clock = SimulationClock(simulated_at, rate=1)
        await clock.pause()
        result = await TCPTransport(
            profile=scenario.link_profile(LinkKind.PAYLOAD_BUS),
            clock=clock,
            trace_sink=self.report_trace,
            source_node=NodeKind.OPTICAL,
            target_node=NodeKind.PLATFORM,
        ).send(
            self.settings.platform_payload_result_host,
            self.settings.platform_payload_result_port,
            run_id=command.run_id,
            mission_id=command.id,
            message_type=message_type,
            payload=pack_product(manifest, path),
        )
        return {"sha256": manifest.sha256, "bytes": result.total_bytes}

    async def handle_request(
        self, message_type: MessageType, payload: bytes, _frame: Frame
    ) -> dict[str, Any]:
        body = unpack_json(payload)
        command = MissionCommand.model_validate(body["command"])
        scenario = ScenarioConfig.model_validate(body["scenario"])
        simulated_at = datetime.fromisoformat(str(body["simulated_at"]).replace("Z", "+00:00"))
        mission_dir = self.product_dir / command.id
        mission_dir.mkdir(parents=True, exist_ok=True)
        pipeline = OpticalPipeline(SensorConfig(seed=scenario.seed, **scenario.sensor.model_dump()))
        if message_type == MessageType.CAPTURE_REQUEST:
            manifest, raw_path = await asyncio.to_thread(
                pipeline.capture_raw,
                scene_path=self.scene_path(command.scene_asset_id or command.scene_id),
                output_dir=mission_dir,
                run_id=command.run_id,
                mission_id=command.id,
            )
            quicklook = mission_dir / f"{command.id}_raw_quicklook.png"
            await asyncio.to_thread(
                pipeline.raw_quicklook,
                raw_path=raw_path,
                scene_path=self.scene_path(command.scene_asset_id or command.scene_id),
                destination=quicklook,
            )
            self.jobs[command.id] = {
                "command": command.model_dump(mode="json"),
                "scenario": scenario.model_dump(mode="json"),
                "captured_at": simulated_at.isoformat(),
                "products": {ProductLevel.RAW: manifest.model_dump(mode="json")},
                "quicklook": str(quicklook),
            }
            self.jobs[command.id]["products"][ProductLevel.RAW]["artifact_path"] = str(raw_path)
            self.persist(command.id)
            return await self._return_product(
                command=command,
                scenario=scenario,
                simulated_at=simulated_at,
                message_type=MessageType.RAW_PRODUCT,
                manifest=manifest,
                path=raw_path,
            )
        if message_type != MessageType.L0_PROCESS_REQUEST:
            raise ValueError(f"unsupported optical message type {message_type.name}")
        job = self.jobs.get(command.id)
        if not job:
            raise ValueError("optical payload has no RAW for mission")
        raw_manifest = ProductManifest.model_validate(job["products"][ProductLevel.RAW])
        raw_path = Path(str(raw_manifest.artifact_path))
        if command.l0_processor_id == "builtin-l0":
            manifest, l0_path = await asyncio.to_thread(
                pipeline.process_l0_from_raw,
                raw_path=raw_path,
                scene_path=self.scene_path(command.scene_asset_id or command.scene_id),
                output_dir=mission_dir,
                run_id=command.run_id,
                mission_id=command.id,
            )
        else:
            bundle = self.processor_dir / f"{command.l0_processor_id}.zip"
            if not bundle.is_file():
                raise ProcessorBlocked(f"Optical 未安装处理器 {command.l0_processor_id}")
            definition, _bundle_sha = inspect_processor_bundle(bundle.read_bytes())
            with rasterio.open(
                self.scene_path(command.scene_asset_id or command.scene_id)
            ) as scene:
                shape = [scene.count, scene.height, scene.width]
            execution = ProcessorExecution(
                mission_id=command.id,
                processor_id=command.l0_processor_id,
                stage=ProcessorStage.L0,
                runtime_type=self.settings.oci_runtime,
                sandbox_profile_version=("seatbelt-v1" if self.settings.oci_runtime == "desktop-sandbox" else None),
                input_summary={"raw_sha256": raw_manifest.sha256, "shape": shape},
                resource_limits={
                    "runtime": self.settings.oci_runtime,
                    "cpu": definition.cpu_limit,
                    "memory_mb": definition.memory_mb,
                    "timeout_seconds": definition.timeout_seconds,
                    "output_limit_mb": definition.output_limit_mb,
                },
            )
            await self.report_execution(execution)
            try:
                run = await self.runner.run(
                    bundle_path=bundle,
                    request={
                        "schema_version": 1,
                        "stage": "l0",
                        "mission_id": command.id,
                        "raw_layout": {"shape": shape, "packet_header": "OPTR"},
                        "sensor": scenario.sensor.model_dump(mode="json"),
                        "captured_at": job["captured_at"],
                    },
                    input_files={"raw": raw_path},
                    execution_dir=mission_dir / "l0-execution",
                )
            except ProcessorBlocked as exc:
                execution.status = (
                    ProcessorRuntimeStatus.UNAVAILABLE
                if any(word in str(exc) for word in ("Docker", "Runtime", "镜像", "桌面安全执行器"))
                    else ProcessorRuntimeStatus.FAILED
                )
                execution.error = str(exc)
                execution.block_reason = str(exc)
                execution.finished_at = utc_now()
                await self.report_execution(execution)
                raise
            output_name = run.result["outputs"].get("l0")
            if not output_name:
                execution.status = ProcessorRuntimeStatus.FAILED
                execution.error = "L0 处理器必须输出 outputs.l0"
                execution.finished_at = utc_now()
                await self.report_execution(execution)
                raise ProcessorBlocked("L0 处理器必须输出 outputs.l0")
            source = run.output_dir / str(output_name)
            l0_path = mission_dir / f"{command.id}_l0.npy"
            shutil.copyfile(source, l0_path)
            import numpy as np

            value = np.load(l0_path, allow_pickle=False)
            if list(value.shape) != shape or value.dtype != np.uint16:
                execution.status = ProcessorRuntimeStatus.FAILED
                execution.error = "L0 输出必须是与 RAW 布局一致的 uint16 NumPy 数组"
                execution.finished_at = utc_now()
                await self.report_execution(execution)
                raise ProcessorBlocked("L0 输出必须是与 RAW 布局一致的 uint16 NumPy 数组")
            execution.status = ProcessorRuntimeStatus.COMPLETED
            execution.finished_at = utc_now()
            execution.exit_code = run.exit_code
            execution.stdout = run.stdout
            execution.stderr = run.stderr
            execution.output_summary = {"l0_sha256": sha256_file(l0_path)}
            await self.report_execution(execution)
            manifest = ProductManifest(
                run_id=command.run_id,
                mission_id=command.id,
                level=ProductLevel.L0,
                name=l0_path.name,
                mime_type="application/x-npy",
                size_bytes=l0_path.stat().st_size,
                sha256=sha256_file(l0_path),
                processing_parameters={"processor_id": command.l0_processor_id},
                quality={"processor_node": "optical", "sandboxed": True},
                lineage=[raw_manifest.name],
                artifact_path=str(l0_path),
            )
        value = manifest.model_dump(mode="json")
        value["artifact_path"] = str(l0_path)
        job["products"][ProductLevel.L0] = value
        self.persist(command.id)
        return await self._return_product(
            command=command,
            scenario=scenario,
            simulated_at=simulated_at,
            message_type=MessageType.L0_PRODUCT,
            manifest=manifest,
            path=l0_path,
        )

    def snapshot(self, mission_id: str) -> NodeSnapshot:
        job = self.jobs.get(mission_id)
        if not job:
            raise KeyError(mission_id)
        manifests = [ProductManifest.model_validate(item) for item in job["products"].values()]
        artifacts = [
            NodeArtifact(
                key=item.id,
                name=item.name,
                level=item.level,
                mime_type=item.mime_type,
                size_bytes=item.size_bytes,
                sha256=item.sha256,
                previewable=False,
            )
            for item in manifests
        ]
        quicklook = Path(str(job.get("quicklook", "")))
        if quicklook.is_file():
            artifacts.append(
                NodeArtifact(
                    key="raw_quicklook",
                    name=quicklook.name,
                    level="raw_quicklook",
                    mime_type="image/png",
                    size_bytes=quicklook.stat().st_size,
                    sha256=sha256_file(quicklook),
                    previewable=True,
                )
            )
        return NodeSnapshot(
            node=NodeKind.OPTICAL,
            mission_id=mission_id,
            status="l0_ready" if ProductLevel.L0 in job["products"] else "raw_ready",
            observation_notice="仿真观察数据，未通过星地下传",
            state={
                "scene_id": job["command"]["scene_id"],
                "captured_at": job.get("captured_at"),
                "l0_processor_id": job["command"].get("l0_processor_id", "builtin-l0"),
            },
            artifacts=artifacts,
        )


def create_app(app_settings: Settings = settings) -> FastAPI:
    state = OpticalState(app_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await state.start()
        yield
        await state.close()

    app = FastAPI(title="Optical Payload Node", version=__version__, lifespan=lifespan)
    app.state.optical = state

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "optical-node",
            "payload_listener": app_settings.optical_payload_port,
            "oci_runtime": "ready" if await state.runner.available() else "unavailable",
        }

    @app.post("/internal/scenes")
    async def stage_scene(
        file: UploadFile = File(...),
        scene_id: str = Query(...),
        asset_id: str = Query(...),
        center_latitude: float | None = Query(default=None),
        center_longitude: float | None = Query(default=None),
        pixel_size: float | None = Query(default=None),
        crs: str = Query(default="EPSG:4326"),
    ) -> dict[str, Any]:
        content = await file.read()
        destination = state.scene_dir / f"{asset_id}.tif"
        try:
            asset = await asyncio.to_thread(
                validate_and_convert_scene,
                content,
                filename=file.filename or "scene.tif",
                scene_id=scene_id,
                destination=destination,
                center_latitude=center_latitude,
                center_longitude=center_longitude,
                pixel_size=pixel_size,
                crs=crs,
            )
            asset.id = asset_id
            source_suffix = Path(file.filename or "scene.tif").suffix.lower()
            (state.scene_dir / f"{asset_id}.source{source_suffix}").write_bytes(content)
        except ValueError as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(422, str(exc)) from exc
        return asset.model_dump(mode="json")

    @app.post("/internal/processors")
    async def stage_processor(
        file: UploadFile = File(...), processor_id: str | None = Query(default=None)
    ) -> dict[str, Any]:
        content = await file.read()
        try:
            definition, digest = inspect_processor_bundle(content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if definition.stage != ProcessorStage.L0:
            raise HTTPException(422, "Optical accepts only L0 processors")
        target = state.processor_dir / f"{processor_id or definition.id}.zip"
        target.write_bytes(content)
        return {"id": definition.id, "sha256": digest, "definition": definition}

    @app.get("/internal/missions/{mission_id}/snapshot")
    async def snapshot(mission_id: str) -> NodeSnapshot:
        try:
            return state.snapshot(mission_id)
        except KeyError as exc:
            raise HTTPException(404, "mission not found") from exc

    @app.get("/internal/missions/{mission_id}/nodes/optical", response_model=NodeSnapshot)
    async def node_snapshot(mission_id: str) -> NodeSnapshot:
        try:
            return state.snapshot(mission_id)
        except KeyError as exc:
            raise HTTPException(404, "mission not found") from exc

    @app.get("/internal/missions/{mission_id}/artifacts/{key}")
    async def artifact(mission_id: str, key: str):
        snapshot_value = state.snapshot(mission_id)
        if key not in {item.key for item in snapshot_value.artifacts}:
            raise HTTPException(404, "artifact not found")
        job = state.jobs[mission_id]
        if key == "raw_quicklook":
            path = Path(job["quicklook"])
        else:
            manifest = next(
                ProductManifest.model_validate(item)
                for item in job["products"].values()
                if item["id"] == key
            )
            path = Path(str(manifest.artifact_path))
        resolved = path.resolve()
        if state.product_dir.resolve() not in resolved.parents or not resolved.is_file():
            raise HTTPException(404, "artifact not found")
        return FileResponse(resolved)

    @app.get("/internal/missions/{mission_id}/nodes/optical/artifacts/{key}")
    async def node_artifact(mission_id: str, key: str):
        return await artifact(mission_id, key)

    return app


app = create_app()
