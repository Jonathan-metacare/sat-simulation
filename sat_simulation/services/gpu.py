from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np
import rasterio
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from sat_simulation import __version__
from sat_simulation.common.clock import SimulationClock
from sat_simulation.common.link import TCPReceiver, TCPTransport
from sat_simulation.common.models import (
    AIMode,
    LinkKind,
    NodeArtifact,
    NodeKind,
    NodeSnapshot,
    ProductManifest,
    ProductLevel,
    ProtocolFrameTrace,
    ProtocolTransaction,
    default_link_profiles,
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
    SceneMetadata,
    SensorConfig,
    ensure_demo_scene,
)
from sat_simulation.payload.providers import (
    OpenAICompatibleLanguageProvider,
    YOLOHTTPProvider,
)


class ProviderBlocked(RuntimeError):
    code = "provider_blocked"


class GPUState:
    def __init__(self, app_settings: Settings) -> None:
        self.settings = app_settings
        self.data_dir = app_settings.data_dir / "gpu"
        self.jobs_dir = self.data_dir / "jobs"
        self.scene_dir = self.data_dir / "scenes"
        self.receiver = TCPReceiver(self.handle_job)
        self.jobs: dict[str, dict[str, Any]] = {}

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

    async def start(self) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.scene_dir.mkdir(parents=True, exist_ok=True)
        ensure_demo_scene(self.scene_dir)
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

    async def handle_job(
        self, message_type: MessageType, payload: bytes, frame: Frame
    ) -> dict[str, Any]:
        mission_id = str(frame.mission_id)
        if message_type == MessageType.L1_JOB:
            manifests, files = unpack_product_bundle(payload)
            l0_manifest = next((item for item in manifests if item.level == ProductLevel.L0), None)
            context_manifest = next((item for item in manifests if item.level == ProductLevel.AUX_CONTEXT), None)
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
            scene_source = self.settings.data_dir / "platform" / "scenes" / f"{context['scene']['scene_id']}.tif"
            if not scene_source.exists():
                scene_source = self.scene_dir / f"{context['scene']['scene_id']}.tif"
            if not scene_source.exists():
                raise ValueError(f"GPU cannot access read-only scene {context['scene']['scene_id']}")
            pipeline = OpticalPipeline(SensorConfig(seed=int(context.get("sensor_seed") or 20260811)))
            products = await asyncio.to_thread(
                pipeline.process_l1_from_l0,
                l0_path=l0_path,
                scene_path=scene_source,
                scene=SceneMetadata(**context["scene"]),
                output_dir=mission_dir,
                run_id=l0_manifest.run_id,
                mission_id=mission_id,
                captured_at=datetime.fromisoformat(context["captured_at"]),
                spacecraft_state=context["spacecraft"],
                input_manifests=[l0_manifest],
            )
            l1b_manifest = next(item for item in products.manifests if item.level == ProductLevel.L1B)
            self.jobs[mission_id] = {
                "l0_manifest": l0_manifest.model_dump(mode="json"),
                "manifest": l1b_manifest.model_dump(mode="json"),
                "products": {item.level: item.model_dump(mode="json") for item in products.manifests},
                "path": str(products.paths[ProductLevel.L1B]),
                "thumbnail_path": str(products.paths[ProductLevel.THUMBNAIL]),
                "received_sha256": l0_digest,
                "l1b_sha256": l1b_manifest.sha256,
                "status": "l1_ready",
            }
            clock = SimulationClock(
                datetime.fromtimestamp(frame.simulated_time_ns / 1_000_000_000, tz=UTC), rate=1
            )
            transport = TCPTransport(
                profile=default_link_profiles()[LinkKind.GTX], clock=clock,
                trace_sink=self.report_trace, source_node=NodeKind.GPU,
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
            profile=default_link_profiles()[LinkKind.GTX], clock=clock,
            trace_sink=self.report_trace, source_node=NodeKind.GPU,
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
                key=level.value, name=manifest.name, level=level.value,
                mime_type=manifest.mime_type, size_bytes=manifest.size_bytes,
                sha256=manifest.sha256,
                previewable=level in {ProductLevel.THUMBNAIL, ProductLevel.STAC},
            )
            for level, manifest in products.items()
        ]
        result = self.jobs_dir / mission_id / "ai_result.json"
        if result.is_file():
            artifacts.append(NodeArtifact(
                key="ai_result", name=result.name, level="ai_result",
                mime_type="application/json", size_bytes=result.stat().st_size,
                sha256=hashlib.sha256(result.read_bytes()).hexdigest(), previewable=True,
            ))
        return NodeSnapshot(
            node=NodeKind.GPU, mission_id=mission_id, status=str(job.get("status", "unknown")),
            observation_notice="仿真观察数据，未通过星地下传",
            state={
                "received_sha256": job.get("received_sha256"),
                "l0_sha256": job.get("received_sha256"),
                "l1b_sha256": job.get("l1b_sha256"),
                "provider_mode": job.get("result", {}).get("ai_mode"),
                "result": job.get("result"),
            }, artifacts=artifacts,
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
        }

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
