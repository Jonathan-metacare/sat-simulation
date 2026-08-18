from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np
import rasterio
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from rasterio.shutil import copy as raster_copy

from sat_simulation import __version__
from sat_simulation.common.clock import SimulationClock
from sat_simulation.common.link import TCPReceiver, TCPTransport
from sat_simulation.common.models import (
    AIMode,
    LinkProfile,
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
    utc_now,
)
from sat_simulation.common.protocol import Frame, MessageType
from sat_simulation.common.wire import (
    pack_json,
    pack_product_bundle,
    unpack_json,
    unpack_product_bundle,
)
from sat_simulation.config import Settings, settings
from sat_simulation.optical.pipeline import (
    OpticalPipeline,
    OpticalProducts,
    SensorConfig,
    sha256_file,
)
from sat_simulation.payload.providers import (
    OpenAICompatibleLanguageProvider,
    YOLOHTTPProvider,
)
from sat_simulation.processors import ProcessorBlocked, ProcessorRunner, inspect_processor_bundle


class ProviderBlocked(RuntimeError):
    code = "provider_blocked"


class GPUState:
    def __init__(self, app_settings: Settings) -> None:
        self.settings = app_settings
        self.data_dir = app_settings.data_dir / "gpu"
        self.jobs_dir = self.data_dir / "jobs"
        self.processor_dir = self.data_dir / "processors"
        self.receiver = TCPReceiver(self.handle_job)
        self.jobs: dict[str, dict[str, Any]] = {}
        self.runner = ProcessorRunner(
            runtime=app_settings.oci_runtime, image=app_settings.processor_image
        )

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

    async def start(self) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.processor_dir.mkdir(parents=True, exist_ok=True)
        await self.receiver.start(self.settings.host, self.settings.gpu_gtx_port)
        for state_path in self.jobs_dir.glob("*/job.json"):
            try:
                self.jobs[state_path.parent.name] = json.loads(state_path.read_text("utf-8"))
            except (OSError, ValueError):
                continue

    async def close(self) -> None:
        await self.receiver.close()

    def save_job(self, mission_id: str) -> None:
        mission_dir = self.jobs_dir / mission_id
        mission_dir.mkdir(parents=True, exist_ok=True)
        (mission_dir / "job.json").write_text(
            json.dumps(self.jobs[mission_id], ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def make_thumbnail(source: Path, destination: Path) -> None:
        with rasterio.open(source) as dataset:
            data = dataset.read(out_shape=(min(3, dataset.count), 256, 256)).astype(np.float32)
        if data.shape[0] == 1:
            data = np.repeat(data, 3, axis=0)
        low, high = np.percentile(data, [2, 98])
        rgb = np.transpose(np.clip((data - low) / max(float(high - low), 1e-9), 0, 1), (1, 2, 0))
        cv2.imwrite(
            str(destination),
            cv2.cvtColor(np.round(rgb * 255).astype(np.uint8), cv2.COLOR_RGB2BGR),
        )

    async def run_custom_l1(
        self,
        *,
        processor_id: str,
        mission_id: str,
        mission_dir: Path,
        l0_manifest: ProductManifest,
        l0_path: Path,
        context: dict[str, Any],
    ) -> OpticalProducts:
        bundle = self.processor_dir / f"{processor_id}.zip"
        if not bundle.is_file():
            raise ProcessorBlocked(f"GPU 未安装 L1 处理器 {processor_id}")
        definition, _bundle_sha = inspect_processor_bundle(bundle.read_bytes())
        context_path = mission_dir / f"{mission_id}_processor_context.json"
        context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2), "utf-8")
        execution = ProcessorExecution(
            mission_id=mission_id,
            processor_id=processor_id,
            stage=ProcessorStage.L1,
            input_summary={
                "l0_sha256": l0_manifest.sha256,
                "ancillary_sha256": sha256_file(context_path),
            },
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
                    "stage": "l1",
                    "mission_id": mission_id,
                    "captured_at": context["captured_at"],
                    "raster": context["scene"],
                    "sensor": context.get("sensor", {}),
                    "spacecraft": context["spacecraft"],
                },
                input_files={"l0": l0_path, "ancillary": context_path},
                execution_dir=mission_dir / "l1-execution",
            )
        except ProcessorBlocked as exc:
            execution.status = (
                ProcessorRuntimeStatus.UNAVAILABLE
                if any(word in str(exc) for word in ("Docker", "Runtime", "镜像"))
                else ProcessorRuntimeStatus.FAILED
            )
            execution.error = str(exc)
            execution.finished_at = utc_now()
            await self.report_execution(execution)
            raise
        outputs = run.result["outputs"]
        if not outputs.get("l1a") or not outputs.get("l1b"):
            execution.status = ProcessorRuntimeStatus.FAILED
            execution.error = "L1 处理器必须输出 outputs.l1a 和 outputs.l1b"
            execution.finished_at = utc_now()
            await self.report_execution(execution)
            raise ProcessorBlocked("L1 处理器必须输出 outputs.l1a 和 outputs.l1b")
        l1a_path = mission_dir / f"{mission_id}_l1a.tif"
        l1b_path = mission_dir / f"{mission_id}_l1b.tif"
        shutil.copyfile(run.output_dir / str(outputs["l1a"]), l1a_path)
        try:
            raster_copy(
                run.output_dir / str(outputs["l1b"]),
                l1b_path,
                driver="COG",
                compress="DEFLATE",
            )
        except Exception as exc:
            execution.status = ProcessorRuntimeStatus.FAILED
            execution.error = f"L1B 无法转换为 COG: {exc}"
            execution.finished_at = utc_now()
            await self.report_execution(execution)
            raise ProcessorBlocked(execution.error) from exc
        for level, path in ((ProductLevel.L1A, l1a_path), (ProductLevel.L1B, l1b_path)):
            with rasterio.open(path) as dataset:
                if dataset.width != int(context["scene"]["width"]) or dataset.height != int(
                    context["scene"]["height"]
                ):
                    execution.status = ProcessorRuntimeStatus.FAILED
                    execution.error = f"{level.value} 尺寸与冻结场景不一致"
                    execution.finished_at = utc_now()
                    await self.report_execution(execution)
                    raise ProcessorBlocked(f"{level.value} 尺寸与冻结场景不一致")
                if dataset.count != int(context["scene"]["bands"]) or not dataset.crs:
                    execution.status = ProcessorRuntimeStatus.FAILED
                    execution.error = f"{level.value} 波段或 CRS 无效"
                    execution.finished_at = utc_now()
                    await self.report_execution(execution)
                    raise ProcessorBlocked(execution.error)
                if level == ProductLevel.L1A and any(dtype != "uint16" for dtype in dataset.dtypes):
                    execution.status = ProcessorRuntimeStatus.FAILED
                    execution.error = "L1A 必须保留 uint16 DN"
                    execution.finished_at = utc_now()
                    await self.report_execution(execution)
                    raise ProcessorBlocked(execution.error)
        execution.status = ProcessorRuntimeStatus.COMPLETED
        execution.finished_at = utc_now()
        execution.exit_code = run.exit_code
        execution.stdout = run.stdout
        execution.stderr = run.stderr
        execution.output_summary = {
            "l1a_sha256": sha256_file(l1a_path),
            "l1b_sha256": sha256_file(l1b_path),
        }
        await self.report_execution(execution)
        thumbnail_path = mission_dir / f"{mission_id}_thumbnail.png"
        self.make_thumbnail(l1b_path, thumbnail_path)
        stac_path = mission_dir / f"{mission_id}_stac-item.json"
        stac_path.write_text(
            json.dumps(
                {
                    "stac_version": "1.1.0",
                    "type": "Feature",
                    "id": mission_id,
                    "geometry": None,
                    "bbox": None,
                    "properties": {"datetime": context["captured_at"]},
                    "assets": {},
                },
                indent=2,
            ),
            "utf-8",
        )
        paths = {
            ProductLevel.L1A: l1a_path,
            ProductLevel.L1B: l1b_path,
            ProductLevel.THUMBNAIL: thumbnail_path,
            ProductLevel.STAC: stac_path,
        }
        mimes = {
            ProductLevel.L1A: "image/tiff; application=geotiff",
            ProductLevel.L1B: "image/tiff; application=geotiff; profile=cloud-optimized",
            ProductLevel.THUMBNAIL: "image/png",
            ProductLevel.STAC: "application/geo+json",
        }
        manifests = [
            ProductManifest(
                run_id=l0_manifest.run_id,
                mission_id=mission_id,
                level=level,
                name=path.name,
                mime_type=mimes[level],
                size_bytes=path.stat().st_size,
                sha256=sha256_file(path),
                processing_parameters={"processor_id": processor_id},
                quality={"processor_node": "gpu", "sandboxed": True},
                lineage=[l0_manifest.name],
                artifact_path=str(path),
            )
            for level, path in paths.items()
        ]
        return OpticalProducts(manifests=manifests, paths=paths, truth_path=l0_path)

    async def handle_job(
        self, message_type: MessageType, payload: bytes, frame: Frame
    ) -> dict[str, Any]:
        mission_id = str(frame.mission_id)
        if message_type == MessageType.L1_JOB:
            manifests, files = unpack_product_bundle(payload)
            l0_manifest = next((item for item in manifests if item.level == ProductLevel.L0), None)
            context_manifest = next(
                (item for item in manifests if item.level == ProductLevel.AUX_CONTEXT), None
            )
            if not l0_manifest or not context_manifest:
                raise ValueError("GPU L1_JOB requires L0 and auxiliary context")
            mission_id = l0_manifest.mission_id
            l0_content = files[l0_manifest.name]
            l0_digest = hashlib.sha256(l0_content).hexdigest()
            if l0_digest != l0_manifest.sha256:
                raise ValueError("GTX L0 SHA-256 mismatch")
            context_content = files[context_manifest.name]
            if hashlib.sha256(context_content).hexdigest() != context_manifest.sha256:
                raise ValueError("GTX L1 context SHA-256 mismatch")
            context = json.loads(context_content.decode("utf-8"))
            mission_dir = self.jobs_dir / mission_id
            mission_dir.mkdir(parents=True, exist_ok=True)
            l0_path = mission_dir / l0_manifest.name
            l0_path.write_bytes(l0_content)
            sensor = dict(context.get("sensor") or {})
            pipeline = OpticalPipeline(
                SensorConfig(seed=int(context.get("sensor_seed") or 20260811), **sensor)
            )
            processor_id = str(context.get("l1_processor_id") or "builtin-l1")
            if processor_id == "builtin-l1":
                products = await asyncio.to_thread(
                    pipeline.process_l1_from_l0,
                    l0_path=l0_path,
                    scene_path=None,
                    scene=None,
                    raster_context=context["scene"],
                    output_dir=mission_dir,
                    run_id=l0_manifest.run_id,
                    mission_id=mission_id,
                    captured_at=datetime.fromisoformat(context["captured_at"]),
                    spacecraft_state=context["spacecraft"],
                    input_manifests=[l0_manifest],
                )
            else:
                products = await self.run_custom_l1(
                    processor_id=processor_id,
                    mission_id=mission_id,
                    mission_dir=mission_dir,
                    l0_manifest=l0_manifest,
                    l0_path=l0_path,
                    context=context,
                )
            l1b_manifest = next(
                item for item in products.manifests if item.level == ProductLevel.L1B
            )
            self.jobs[mission_id] = {
                "l0_manifest": l0_manifest.model_dump(mode="json"),
                "manifest": l1b_manifest.model_dump(mode="json"),
                "products": {
                    item.level: item.model_dump(mode="json") for item in products.manifests
                },
                "path": str(products.paths[ProductLevel.L1B]),
                "thumbnail_path": str(products.paths[ProductLevel.THUMBNAIL]),
                "received_sha256": l0_digest,
                "l1b_sha256": l1b_manifest.sha256,
                "gtx_profile": context.get("gtx_profile"),
                "status": "l1_ready",
                "l1_processor_id": processor_id,
            }
            clock = SimulationClock(
                datetime.fromtimestamp(frame.simulated_time_ns / 1_000_000_000, tz=UTC), rate=1
            )
            transport = TCPTransport(
                profile=LinkProfile.model_validate(
                    context.get("gtx_profile")
                    or {"kind": "gtx", "bandwidth_bps": 2.5e9, "latency_ms": 0.2}
                ),
                clock=clock,
                trace_sink=self.report_trace,
                source_node=NodeKind.GPU,
                target_node=NodeKind.PLATFORM,
            )
            result = await transport.send(
                self.settings.platform_gtx_result_host,
                self.settings.platform_gtx_result_port,
                run_id=l0_manifest.run_id,
                mission_id=mission_id,
                message_type=MessageType.L1_PRODUCTS,
                payload=pack_product_bundle(
                    products.manifests,
                    {item.id: products.paths[item.level] for item in products.manifests},
                ),
            )
            self.save_job(mission_id)
            return {
                "received_sha256": l0_digest,
                "l1b_sha256": l1b_manifest.sha256,
                "l1_gtx_bytes": result.total_bytes,
                "job_status": "l1_ready",
            }

        if message_type != MessageType.AI_EXECUTE:
            raise ValueError(f"unsupported GTX message type {message_type.name}")
        request = unpack_json(payload)
        mission_id = str(request["mission_id"])
        job = self.jobs.get(mission_id)
        if not job:
            raise ValueError("GPU has no verified L1B for this mission")
        mode = AIMode(request["ai_mode"])
        manifest = ProductManifest.model_validate(job["manifest"])
        try:
            if mode == AIMode.YOLO:
                if not self.settings.yolo_api_url:
                    raise ProviderBlocked("YOLO 未配置：请设置 SAT_SIM_YOLO_API_URL 后重试本步")
                provider = YOLOHTTPProvider(
                    self.settings.yolo_api_url,
                    model=self.settings.yolo_model,
                    timeout=self.settings.provider_timeout_seconds,
                    api_key=self.settings.yolo_api_key,
                )
                model_result = await provider.detect(
                    manifest,
                    Path(job["path"]),
                    {
                        "thumbnail_path": job["thumbnail_path"],
                        "provider_options": request.get("options", {}),
                    },
                )
            else:
                if not self.settings.llm_api_url:
                    raise ProviderBlocked("LLM 未配置：请设置 SAT_SIM_LLM_API_URL 后重试本步")
                provider = OpenAICompatibleLanguageProvider(
                    self.settings.llm_api_url,
                    model=self.settings.llm_model,
                    timeout=self.settings.provider_timeout_seconds,
                    api_key=self.settings.llm_api_key,
                )
                model_result = await provider.analyze(
                    {
                        "thumbnail_path": job["thumbnail_path"],
                        "mission_id": mission_id,
                        "mode": mode,
                        **dict(request.get("options") or {}),
                    },
                    [manifest],
                )
        except ProviderBlocked:
            raise
        except Exception as exc:
            raise ProviderBlocked(
                f"{mode.value.upper()} Provider 健康检查或调用失败：{exc}"
            ) from exc

        result_body = {
            "mission_id": mission_id,
            "run_id": str(request["run_id"]),
            "ai_mode": mode,
            "result": model_result.model_dump(mode="json"),
            "l1b_sha256": manifest.sha256,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        result_path = self.jobs_dir / mission_id / "ai_result.json"
        canonical_result = pack_json(result_body)
        result_path.write_bytes(canonical_result)
        result_body["sha256"] = hashlib.sha256(canonical_result).hexdigest()
        clock = SimulationClock(
            datetime.fromtimestamp(frame.simulated_time_ns / 1_000_000_000, tz=UTC), rate=1
        )
        transport = TCPTransport(
            profile=LinkProfile.model_validate(
                job.get("gtx_profile") or {"kind": "gtx", "bandwidth_bps": 2.5e9, "latency_ms": 0.2}
            ),
            clock=clock,
            trace_sink=self.report_trace,
            source_node=NodeKind.GPU,
            target_node=NodeKind.PLATFORM,
        )
        transfer = await transport.send(
            self.settings.platform_gtx_result_host,
            self.settings.platform_gtx_result_port,
            run_id=str(request["run_id"]),
            mission_id=mission_id,
            message_type=MessageType.AI_RESULT,
            payload=pack_json(result_body),
        )
        job.update({"status": "completed", "result": result_body})
        self.save_job(mission_id)
        return {
            "job_status": "completed",
            "result_sha256": result_body["sha256"],
            "result_gtx_bytes": transfer.total_bytes,
        }

    def node_snapshot(self, mission_id: str) -> NodeSnapshot:
        job = self.jobs.get(mission_id)
        if not job:
            raise KeyError(mission_id)
        products = {
            ProductLevel(level): ProductManifest.model_validate(value)
            for level, value in dict(job.get("products") or {}).items()
        }
        artifacts = [
            NodeArtifact(
                key=level.value,
                name=manifest.name,
                level=level.value,
                mime_type=manifest.mime_type,
                size_bytes=manifest.size_bytes,
                sha256=manifest.sha256,
                previewable=level in {ProductLevel.THUMBNAIL, ProductLevel.STAC},
            )
            for level, manifest in products.items()
        ]
        result = self.jobs_dir / mission_id / "ai_result.json"
        if result.is_file():
            artifacts.append(
                NodeArtifact(
                    key="ai_result",
                    name=result.name,
                    level="ai_result",
                    mime_type="application/json",
                    size_bytes=result.stat().st_size,
                    sha256=hashlib.sha256(result.read_bytes()).hexdigest(),
                    previewable=True,
                )
            )
        return NodeSnapshot(
            node=NodeKind.GPU,
            mission_id=mission_id,
            status=str(job.get("status", "unknown")),
            observation_notice="仿真观察数据，未通过星地下传",
            state={
                "received_sha256": job.get("received_sha256"),
                "l0_sha256": job.get("received_sha256"),
                "l1b_sha256": job.get("l1b_sha256"),
                "provider_mode": job.get("result", {}).get("ai_mode"),
                "result": job.get("result"),
            },
            artifacts=artifacts,
        )

    def artifact(self, mission_id: str, key: str) -> tuple[Path, str, str]:
        job = self.jobs.get(mission_id)
        if not job:
            raise KeyError(mission_id)
        choices = {
            "ai_result": (self.jobs_dir / mission_id / "ai_result.json", "application/json"),
        }
        for level, value in dict(job.get("products") or {}).items():
            manifest = ProductManifest.model_validate(value)
            choices[str(level)] = (Path(str(manifest.artifact_path)), manifest.mime_type)
        if key not in choices:
            raise KeyError(key)
        path, mime = choices[key]
        path = path.resolve()
        if not path.is_file() or self.jobs_dir.resolve() not in path.parents:
            raise KeyError(key)
        return path, mime, path.name


def create_app(app_settings: Settings = settings) -> FastAPI:
    state = GPUState(app_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await state.start()
        yield
        await state.close()

    app = FastAPI(title="GPU Payload Node", version=__version__, lifespan=lifespan)
    app.state.gpu = state

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "gpu-node",
            "version": __version__,
            "gtx_listener": app_settings.gpu_gtx_port,
            "providers": {
                "detection": {
                    "status": "configured" if app_settings.yolo_api_url else "not_configured",
                    "api_url_configured": bool(app_settings.yolo_api_url),
                },
                "language": {
                    "status": "configured" if app_settings.llm_api_url else "not_configured",
                    "api_url_configured": bool(app_settings.llm_api_url),
                },
            },
            "processor_runtime": "ready" if await state.runner.available() else "unavailable",
        }

    @app.post("/internal/processors")
    async def stage_processor(
        file: UploadFile = File(...), processor_id: str | None = Query(default=None)
    ) -> dict[str, Any]:
        content = await file.read()
        try:
            definition, digest = inspect_processor_bundle(content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if definition.stage != ProcessorStage.L1:
            raise HTTPException(422, "GPU accepts only L1 processors")
        target = state.processor_dir / f"{processor_id or definition.id}.zip"
        target.write_bytes(content)
        return {"id": definition.id, "sha256": digest, "definition": definition}

    @app.get("/internal/jobs")
    async def jobs() -> dict[str, Any]:
        return state.jobs

    @app.get("/internal/missions/{mission_id}/nodes/gpu", response_model=NodeSnapshot)
    async def node_snapshot(mission_id: str) -> NodeSnapshot:
        try:
            return state.node_snapshot(mission_id)
        except KeyError as exc:
            raise HTTPException(404, "GPU job not found") from exc

    @app.get("/internal/missions/{mission_id}/nodes/gpu/artifacts/{key}")
    async def node_artifact(mission_id: str, key: str):
        try:
            path, mime, name = state.artifact(mission_id, key)
        except KeyError as exc:
            raise HTTPException(404, "artifact not found") from exc
        return FileResponse(path, media_type=mime, filename=name)

    return app


app = create_app()
