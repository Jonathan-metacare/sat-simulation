from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import rasterio
from fastapi import FastAPI

from sat_simulation import __version__
from sat_simulation.common.clock import SimulationClock
from sat_simulation.common.link import TCPReceiver, TCPTransport
from sat_simulation.common.models import AIMode, LinkKind, ProductManifest, default_link_profiles
from sat_simulation.common.protocol import Frame, MessageType
from sat_simulation.common.wire import pack_json, unpack_json, unpack_product
from sat_simulation.config import Settings, settings
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
        self.receiver = TCPReceiver(self.handle_job)
        self.jobs: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
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
        if message_type == MessageType.AI_JOB:
            manifest, content = unpack_product(payload)
            mission_id = manifest.mission_id
            digest = hashlib.sha256(content).hexdigest()
            if digest != manifest.sha256:
                raise ValueError("GTX L1B SHA-256 mismatch")
            mission_dir = self.jobs_dir / mission_id
            mission_dir.mkdir(parents=True, exist_ok=True)
            path = mission_dir / manifest.name
            path.write_bytes(content)
            thumbnail = mission_dir / f"{mission_id}_gpu_thumbnail.png"
            self.make_thumbnail(path, thumbnail)
            self.jobs[mission_id] = {
                "manifest": manifest.model_dump(mode="json"),
                "path": str(path),
                "thumbnail_path": str(thumbnail),
                "received_sha256": digest,
                "status": "received",
            }
            self.save_job(mission_id)
            return {"received_sha256": digest, "job_status": "received"}

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
        transport = TCPTransport(profile=default_link_profiles()[LinkKind.GTX], clock=clock)
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

    return app


app = create_app()
