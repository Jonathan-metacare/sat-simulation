from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from sat_simulation import __version__
from sat_simulation.common.link import TCPReceiver
from sat_simulation.common.protocol import Frame, MessageType
from sat_simulation.common.wire import unpack_product
from sat_simulation.config import Settings, settings
from sat_simulation.payload.providers import (
    PlaceholderDetectionProvider,
    PlaceholderLanguageProvider,
)


class GPUState:
    def __init__(self, app_settings: Settings) -> None:
        self.settings = app_settings
        self.data_dir = app_settings.data_dir / "gpu"
        self.jobs_dir = self.data_dir / "jobs"
        self.receiver = TCPReceiver(self.handle_job)
        self.detection = PlaceholderDetectionProvider()
        self.language = PlaceholderLanguageProvider()
        self.jobs: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        await self.receiver.start(self.settings.host, self.settings.gpu_gtx_port)

    async def close(self) -> None:
        await self.receiver.close()

    async def handle_job(
        self, message_type: MessageType, payload: bytes, frame: Frame
    ) -> dict[str, Any]:
        if message_type != MessageType.AI_JOB:
            raise ValueError(f"unsupported GTX message type {message_type.name}")
        manifest, content = unpack_product(payload)
        digest = hashlib.sha256(content).hexdigest()
        if digest != manifest.sha256:
            raise ValueError("GTX L1B SHA-256 mismatch")
        mission_dir = self.jobs_dir / manifest.mission_id
        mission_dir.mkdir(parents=True, exist_ok=True)
        path = mission_dir / manifest.name
        path.write_bytes(content)
        result = await self.detection.detect(manifest, path)
        self.jobs[manifest.mission_id] = {
            "manifest": manifest.model_dump(mode="json"),
            "path": str(path),
            "detection": result.model_dump(mode="json"),
        }
        return {
            "received_sha256": digest,
            "job_status": "skipped" if result.status == "not_configured" else result.status,
            "detection": result.model_dump(mode="json"),
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
                    "status": "not_configured",
                    "api_url_configured": bool(app_settings.yolo_api_url),
                },
                "language": {
                    "status": "not_configured",
                    "api_url_configured": bool(app_settings.llm_api_url),
                },
            },
        }

    @app.get("/internal/jobs")
    async def jobs() -> dict[str, Any]:
        return state.jobs

    return app


app = create_app()
