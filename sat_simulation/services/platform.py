from __future__ import annotations

import hashlib
import json
import zipfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from sat_simulation import __version__
from sat_simulation.common.clock import SimulationClock
from sat_simulation.common.link import RemoteTransferError, TCPReceiver, TCPTransport
from sat_simulation.common.models import (
    FaultRule,
    LinkKind,
    MissionCommand,
    MissionPhase,
    MissionStatus,
    NodeArtifact,
    NodeKind,
    NodeSnapshot,
    ProductLevel,
    ProductManifest,
    ProtocolFrameTrace,
    ProtocolTransaction,
    ScenarioConfig,
    TransferRecord,
    TransferStatus,
    utc_now,
)
from sat_simulation.common.orbit import target_attitude
from sat_simulation.common.protocol import Frame, MessageType
from sat_simulation.common.wire import (
    pack_json,
    pack_product,
    pack_product_bundle,
    unpack_json,
    unpack_product,
    unpack_product_bundle,
)
from sat_simulation.config import Settings, settings
from sat_simulation.optical.pipeline import sha256_file


class PlatformState:
    def __init__(self, app_settings: Settings) -> None:
        self.settings = app_settings
        self.data_dir = app_settings.data_dir / "platform"
        self.product_dir = self.data_dir / "products"
        self.task_dir = self.data_dir / "tasks"
        self.uplink_receiver = TCPReceiver(self.handle_uplink)
        self.result_receiver = TCPReceiver(self.handle_gtx_result)
        self.payload_result_receiver = TCPReceiver(self.handle_payload_result)
        self.missions: dict[str, dict[str, Any]] = {}

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

    async def report_processor_execution(self, execution: dict[str, Any]) -> None:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                await client.post(
                    f"{self.settings.ground_http_url}/internal/processor-executions", json=execution
                )
        except Exception:
            return

    async def start(self) -> None:
        self.product_dir.mkdir(parents=True, exist_ok=True)
        self.task_dir.mkdir(parents=True, exist_ok=True)
        for path in self.task_dir.glob("*/state.json"):
            try:
                self.missions[path.parent.name] = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                continue
        await self.uplink_receiver.start(self.settings.host, self.settings.platform_uplink_port)
        await self.result_receiver.start(
            self.settings.platform_gtx_result_bind_host or self.settings.host,
            self.settings.platform_gtx_result_port,
        )
        await self.payload_result_receiver.start(
            self.settings.host, self.settings.platform_payload_result_port
        )

    async def close(self) -> None:
        await self.uplink_receiver.close()
        await self.result_receiver.close()
        await self.payload_result_receiver.close()

    async def handle_payload_result(
        self, message_type: MessageType, payload: bytes, _frame: Frame
    ) -> dict[str, Any]:
        if message_type not in {MessageType.RAW_PRODUCT, MessageType.L0_PRODUCT}:
            raise ValueError(f"unsupported payload result type {message_type.name}")
        manifest, content = unpack_product(payload)
        if hashlib.sha256(content).hexdigest() != manifest.sha256:
            raise ValueError(f"payload product SHA-256 mismatch: {manifest.name}")
        state = self.missions.get(manifest.mission_id)
        if not state:
            raise ValueError("unknown mission in payload product")
        directory = self.product_dir / manifest.mission_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / manifest.name
        path.write_bytes(content)
        value = manifest.model_dump(mode="json")
        value["artifact_path"] = str(path)
        state["products"][manifest.level] = value
        self.persist(manifest.mission_id)
        return {"stored": manifest.level.value, "sha256": manifest.sha256}

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

    def update_analysis_prompt(self, mission_id: str, analysis_prompt: str) -> dict[str, Any]:
        """Update only the pre-AI instruction kept in the platform mission state."""
        state = self.missions.get(mission_id)
        if not state:
            raise KeyError("mission not found")
        if state.get("phase") in {MissionPhase.AI_COMPLETE, MissionPhase.COMPLETED}:
            raise RuntimeError("mission prompt is frozen after AI analysis starts")
        command = MissionCommand.model_validate(state["command"])
        command.analysis_prompt = analysis_prompt
        state["command"] = command.model_dump(mode="json")
        self.persist(mission_id)
        return {"mission_id": mission_id, "updated": True}

    async def handle_gtx_result(
        self, message_type: MessageType, payload: bytes, _frame: Frame
    ) -> dict[str, Any]:
        if message_type == MessageType.L1_PRODUCTS:
            manifests, files = unpack_product_bundle(payload)
            mission_id = manifests[0].mission_id if manifests else ""
            state = self.missions.get(mission_id)
            if not state:
                raise ValueError("unknown mission in L1_PRODUCTS")
            directory = self.product_dir / mission_id
            directory.mkdir(parents=True, exist_ok=True)
            stored: list[str] = []
            for manifest in manifests:
                content = files[manifest.name]
                if hashlib.sha256(content).hexdigest() != manifest.sha256:
                    raise ValueError(f"L1 product SHA-256 mismatch: {manifest.name}")
                path = directory / manifest.name
                path.write_bytes(content)
                value = manifest.model_dump(mode="json")
                value["artifact_path"] = str(path)
                state["products"][manifest.level] = value
                stored.append(manifest.level.value)
            self.persist(mission_id)
            return {"stored": stored, "count": len(stored)}

        if message_type != MessageType.AI_RESULT:
            raise ValueError(f"unsupported GTX result type {message_type.name}")
        return self.store_ai_result(payload)

    def store_ai_result(self, payload: bytes) -> dict[str, Any]:
        body = unpack_json(payload)
        mission_id = str(body["mission_id"])
        state = self.missions.get(mission_id)
        if not state:
            raise ValueError("unknown mission in AI_RESULT")
        expected = str(body.pop("sha256"))
        content = pack_json(body)
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError("AI_RESULT SHA-256 mismatch")
        l1b = ProductManifest.model_validate(state["products"][ProductLevel.L1B])
        if body.get("l1b_sha256") != l1b.sha256:
            raise ValueError("AI_RESULT L1B SHA-256 mismatch")
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

    async def recover_ai_result(self, mission_id: str) -> bool:
        """Recover a verified Jetson result when its reverse GTX ACK was lost."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.settings.gpu_http_url}/internal/missions/{mission_id}/nodes/gpu/"
                    "artifacts/ai_result"
                )
        except httpx.HTTPError:
            return False
        if response.status_code == 404:
            return False
        response.raise_for_status()
        body = unpack_json(response.content)
        body["sha256"] = hashlib.sha256(response.content).hexdigest()
        self.store_ai_result(pack_json(body))
        return True

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
            state["spacecraft"] = spacecraft.model_dump(mode="json")
            state["captured_at"] = simulated_at.isoformat()
            clock = self.clock_for(simulated_at)
            try:
                await TCPTransport(
                    profile=scenario.link_profile(LinkKind.PAYLOAD_BUS),
                    clock=clock,
                    trace_sink=self.report_trace,
                    source_node=NodeKind.PLATFORM,
                    target_node=NodeKind.OPTICAL,
                ).send(
                    self.settings.optical_payload_host,
                    self.settings.optical_payload_port,
                    run_id=command.run_id,
                    mission_id=mission_id,
                    message_type=MessageType.CAPTURE_REQUEST,
                    payload=pack_json(
                        {
                            "command": command.model_dump(mode="json"),
                            "scenario": scenario.model_dump(mode="json"),
                            "simulated_at": simulated_at.isoformat(),
                        }
                    ),
                )
            except RemoteTransferError as exc:
                raise HTTPException(423 if "processor" in exc.code else 502, str(exc)) from exc
            except OSError as exc:
                # A TCP connect failure (for example, a temporary route loss to
                # the Jetson) must remain a retryable GTX failure rather than
                # escaping FastAPI as an opaque 500.
                raise HTTPException(502, f"GPU GTX 链路不可达：{exc}") from exc
            if ProductLevel.RAW not in state["products"]:
                raise HTTPException(502, "Optical 未通过载荷总线返回 RAW")
            manifest = ProductManifest.model_validate(state["products"][ProductLevel.RAW])
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
                        "message": "曝光完成，光学载荷已将 RAW 分包数据返回星务平台。",
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
            clock = self.clock_for(simulated_at)
            try:
                await TCPTransport(
                    profile=scenario.link_profile(LinkKind.PAYLOAD_BUS),
                    clock=clock,
                    trace_sink=self.report_trace,
                    source_node=NodeKind.PLATFORM,
                    target_node=NodeKind.OPTICAL,
                ).send(
                    self.settings.optical_payload_host,
                    self.settings.optical_payload_port,
                    run_id=command.run_id,
                    mission_id=mission_id,
                    message_type=MessageType.L0_PROCESS_REQUEST,
                    payload=pack_json(
                        {
                            "command": command.model_dump(mode="json"),
                            "scenario": scenario.model_dump(mode="json"),
                            "simulated_at": simulated_at.isoformat(),
                        }
                    ),
                )
            except RemoteTransferError as exc:
                raise HTTPException(423 if "processor" in exc.code else 502, str(exc)) from exc
            if ProductLevel.L0 not in state["products"]:
                raise HTTPException(502, "Optical 未通过载荷总线返回 L0")
            l0_manifest = ProductManifest.model_validate(state["products"][ProductLevel.L0])
            asset = command.scene_asset
            if not asset:
                raise HTTPException(409, "任务缺少冻结的场景资产元数据")
            state["l1_context"] = {
                "scene": {
                    "scene_id": asset.scene_id,
                    "target_name": command.target_name,
                    "width": asset.width,
                    "height": asset.height,
                    "bands": asset.bands,
                    "crs": asset.crs,
                    "transform": list(asset.transform),
                },
                "captured_at": state["captured_at"],
                "spacecraft": state["spacecraft"],
                "sensor_seed": scenario.seed,
                "sensor": scenario.sensor.model_dump(mode="json"),
                "gtx_profile": scenario.link_profile(LinkKind.GTX).model_dump(mode="json"),
                "l0": l0_manifest.model_dump(mode="json"),
                "l1_processor_id": command.l1_processor_id,
                "processor_snapshots": command.processor_snapshots,
            }
            state["phase"] = MissionPhase.PROCESSING_COMPLETE
            events.append(
                {
                    "event_type": "l0_processing_completed",
                    "status": MissionStatus.L1A_PROCESSING,
                    "message": (
                        "光学载荷已完成 RAW 到 L0 重组并经载荷总线返回星务，"
                        "星务已组织 GPU L1 处理输入。"
                    ),
                    "data": {
                        "manifest": state["products"][ProductLevel.L0],
                        "context": state["l1_context"],
                    },
                }
            )

        elif stage == "gtx":
            if state["phase"] not in {MissionPhase.PROCESSING_COMPLETE, MissionPhase.GTX_COMPLETE}:
                raise HTTPException(409, "星务任务阶段不允许 GTX 传输")
            if ProductLevel.L1B in state["products"]:
                state["phase"] = MissionPhase.GTX_COMPLETE
                events.append(
                    {
                        "event_type": "l1_products_reused",
                        "status": MissionStatus.GTX_TRANSFER,
                        "message": "星务已持有 GPU 回传的 L1 产品，本次重试直接复用。",
                        "data": {
                            "products": [
                                state["products"][level]
                                for level in (
                                    ProductLevel.L1A,
                                    ProductLevel.L1B,
                                    ProductLevel.THUMBNAIL,
                                    ProductLevel.STAC,
                                )
                                if level in state["products"]
                            ]
                        },
                    }
                )
                self.persist(mission_id)
                return {
                    "events": events,
                    "phase": state["phase"],
                    "products": list(state["products"].values()),
                }
            l0_manifest = ProductManifest.model_validate(state["products"][ProductLevel.L0])
            l0_path = Path(str(l0_manifest.artifact_path))
            context_path = mission_dir / f"{mission_id}_l1_context.json"
            context_path.write_text(
                json.dumps(state["l1_context"], ensure_ascii=False, indent=2), "utf-8"
            )
            state["l1_context"]["gpu_reply"] = {
                "host": self.settings.platform_gtx_result_advertise_host,
                "port": self.settings.platform_gtx_result_port,
            }
            context_path.write_text(
                json.dumps(state["l1_context"], ensure_ascii=False, indent=2), "utf-8"
            )
            context_manifest = ProductManifest(
                run_id=command.run_id,
                mission_id=mission_id,
                level=ProductLevel.AUX_CONTEXT,
                name=context_path.name,
                mime_type="application/json",
                size_bytes=context_path.stat().st_size,
                sha256=sha256_file(context_path),
                processing_parameters={"purpose": "gpu_l1_context"},
                quality={"ancillary_context": True},
                lineage=[l0_manifest.name],
                artifact_path=str(context_path),
            )
            try:
                async with httpx.AsyncClient(timeout=3) as client:
                    health = (await client.get(f"{self.settings.gpu_http_url}/health"))
                    health.raise_for_status()
                    gpu_health = health.json()
            except httpx.HTTPError as exc:
                raise HTTPException(423, f"GPU Payload 离线，L1 已阻塞：{exc}") from exc
            if gpu_health.get("version") != __version__:
                raise HTTPException(
                    423,
                    "GPU Payload 版本不一致"
                    f"（桌面 {__version__}，Jetson {gpu_health.get('version')}），请升级对应端。",
                )
            if (
                command.l1_processor_id != "builtin-l1"
                and gpu_health.get("processor_runtime") != "ready"
            ):
                raise HTTPException(423, "GPU Processor runtime 不可用，无法执行自定义 L1。")
            processor_manifest: ProductManifest | None = None
            processor_path: Path | None = None
            if command.l1_processor_id != "builtin-l1":
                # Ground owns the source bundle. Fetching it locally is control
                # plane work; the subsequent L1_JOB carries it over GTX to the
                # Jetson alongside L0 and the frozen processing context.
                try:
                    async with httpx.AsyncClient(timeout=30) as client:
                        bundle = await client.get(
                            f"{self.settings.ground_http_url}/api/processors/"
                            f"{command.l1_processor_id}/download"
                        )
                        bundle.raise_for_status()
                except httpx.HTTPError as exc:
                    raise HTTPException(
                        423, f"L1 处理器准备失败（{command.l1_processor_id}）：{exc}"
                    ) from exc
                processor_path = mission_dir / f"{command.l1_processor_id}.zip"
                processor_path.write_bytes(bundle.content)
                processor_manifest = ProductManifest(
                    run_id=command.run_id,
                    mission_id=mission_id,
                    level=ProductLevel.PROCESSOR_BUNDLE,
                    name=processor_path.name,
                    mime_type="application/zip",
                    size_bytes=processor_path.stat().st_size,
                    sha256=sha256_file(processor_path),
                    processing_parameters={"processor_id": command.l1_processor_id},
                    quality={"gtx_delivered": True},
                    lineage=[],
                    artifact_path=str(processor_path),
                )
            gtx_manifests = [l0_manifest, context_manifest]
            gtx_paths = {l0_manifest.id: l0_path, context_manifest.id: context_path}
            if processor_manifest and processor_path:
                gtx_manifests.append(processor_manifest)
                gtx_paths[processor_manifest.id] = processor_path
            clock = self.clock_for(simulated_at)
            transport = TCPTransport(
                profile=scenario.link_profile(LinkKind.GTX),
                clock=clock,
                fault=self.fault_for(state, LinkKind.GTX),
                seed=scenario.seed,
                trace_sink=self.report_trace,
                source_node=NodeKind.PLATFORM,
                target_node=NodeKind.GPU,
            )
            try:
                transfer = await transport.send(
                    self.settings.gpu_gtx_host,
                    self.settings.gpu_gtx_port,
                    run_id=command.run_id,
                    mission_id=mission_id,
                    message_type=MessageType.L1_JOB,
                    payload=pack_product_bundle(gtx_manifests, gtx_paths),
                )
            except RemoteTransferError as exc:
                raise HTTPException(423 if "processor" in exc.code else 502, str(exc)) from exc
            if not transfer.response.get("l1b_sha256"):
                raise HTTPException(502, "GPU 未返回 L1B 产品确认")
            for execution in transfer.response.get("processor_executions", []):
                await self.report_processor_execution(execution)
            if ProductLevel.L1B not in state["products"]:
                raise HTTPException(502, "GPU 未通过 GTX 回传 L1_PRODUCTS")
            state["phase"] = MissionPhase.GTX_COMPLETE
            record = self.transfer_record(
                command, LinkKind.GTX, l0_manifest.name, l0_manifest.sha256, transfer
            )
            events.append(
                {
                    "event_type": "gtx_transfer_completed",
                    "status": MissionStatus.GTX_TRANSFER,
                    "message": "L0 与星务姿态辅助数据已通过 GTX 传至 GPU，GPU 完成 L1 并回传星务。",
                    "data": {
                        "record": record.model_dump(mode="json"),
                        "products": [
                            state["products"][level]
                            for level in (
                                ProductLevel.L1A,
                                ProductLevel.L1B,
                                ProductLevel.THUMBNAIL,
                                ProductLevel.STAC,
                            )
                            if level in state["products"]
                        ],
                    },
                }
            )

        elif stage == "ai":
            if state["phase"] not in {MissionPhase.GTX_COMPLETE, MissionPhase.AI_COMPLETE}:
                raise HTTPException(409, "星务任务阶段不允许智能分析")
            if "ai_result" in state:
                state["phase"] = MissionPhase.AI_COMPLETE
                events.append(
                    {
                        "event_type": "ai_result_reused",
                        "status": MissionStatus.AI_PROCESSING,
                        "message": "星务已持有经 GTX 校验的 AI 结果，本次重试直接复用。",
                        "data": {"result": state["ai_result"], "gtx_bytes": 0},
                    }
                )
                self.persist(mission_id)
                return {"events": events, "phase": state["phase"]}
            recovered = await self.recover_ai_result(mission_id)
            if recovered:
                transfer_bytes = 0
            else:
                clock = self.clock_for(simulated_at)
                transport = TCPTransport(
                    profile=scenario.link_profile(LinkKind.GTX),
                    clock=clock,
                    trace_sink=self.report_trace,
                    source_node=NodeKind.PLATFORM,
                    target_node=NodeKind.GPU,
                )
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
                                "ai_model": command.ai_model,
                                "options": {
                                    # The desktop-selected timeout is part of
                                    # the mission contract, not a hidden
                                    # default inside a long-running Jetson
                                    # container.
                                    "provider_timeout_seconds": self.settings.provider_timeout_seconds,
                                    "project_context": command.project_context,
                                    "analysis_prompt": command.analysis_prompt,
                                    "mission_name": command.name,
                                    "target_name": command.target_name,
                                    "target_latitude": command.target_latitude,
                                    "target_longitude": command.target_longitude,
                                    "scene_id": command.scene_id,
                                    # Agent settings remain desktop-local and are read only
                                    # when this AI stage is executed.  The GPU receives a
                                    # bounded, validated wire copy rather than direct access
                                    # to desktop configuration.
                                    "agent": self.settings.agent_configuration,
                                },
                            }
                        ),
                    )
                except RemoteTransferError as exc:
                    if exc.code == "provider_blocked":
                        raise HTTPException(423, str(exc)) from exc
                    # The GPU writes and hashes ai_result.json before attempting
                    # its reverse GTX callback.  If that callback loses a short
                    # platform-listener window, recover the same verified result
                    # immediately instead of requiring the user to run AI again.
                    recovered = await self.recover_ai_result(mission_id)
                    if not recovered:
                        raise HTTPException(502, f"GPU AI GTX 链路失败：{exc}") from exc
                    transfer_bytes = 0
                else:
                    transfer_bytes = transfer.total_bytes
                    inline_result = transfer.response.get("ai_result")
                    if isinstance(inline_result, dict):
                        self.store_ai_result(pack_json(inline_result))
            if "ai_result" not in state:
                raise HTTPException(502, "GPU 未通过 GTX 回传 AI_RESULT")
            state["phase"] = MissionPhase.AI_COMPLETE
            events.append(
                {
                    "event_type": "ai_result_stored",
                    "status": MissionStatus.AI_PROCESSING,
                    "message": (
                        "GPU 模型结果已通过 GTX 回传并由星务持久化。"
                        if not recovered
                        else "GPU GTX 回传未确认，星务已恢复并校验 Jetson 持久化结果。"
                    ),
                    "data": {
                        "result": state["ai_result"],
                        "gtx_bytes": transfer_bytes,
                        "recovered_from_gpu": recovered,
                    },
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
            protocol_transaction_id=result.transfer_id,
        )

    async def downlink_result_package(
        self, mission_id: str, state: dict[str, Any]
    ) -> tuple[TransferRecord, ProductManifest]:
        command = MissionCommand.model_validate(state["command"])
        scenario = ScenarioConfig.model_validate(state["scenario"])
        directory = self.product_dir / mission_id
        package_path = directory / f"{mission_id}_result_package.zip"
        include_levels = [
            ProductLevel.AI_RESULT,
            ProductLevel.L1B,
            ProductLevel.THUMBNAIL,
            ProductLevel.STAC,
        ]
        member_index: dict[str, str] = {}
        summary = {
            "mission_id": mission_id,
            "run_id": command.run_id,
            "ai_mode": command.ai_mode,
            "project_context": command.project_context,
            "analysis_prompt": command.analysis_prompt,
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
            profile=scenario.link_profile(LinkKind.DOWNLINK),
            clock=clock,
            fault=self.fault_for(state, LinkKind.DOWNLINK),
            seed=scenario.seed,
            trace_sink=self.report_trace,
            source_node=NodeKind.PLATFORM,
            target_node=NodeKind.GROUND,
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

    def node_snapshot(self, mission_id: str, node: NodeKind) -> NodeSnapshot:
        state = self.missions.get(mission_id)
        if not state:
            raise KeyError(mission_id)
        products = [
            ProductManifest.model_validate(value) for value in state.get("products", {}).values()
        ]
        public_state = {
            "phase": state.get("phase"),
            "spacecraft": state.get("spacecraft"),
            "clock": state.get("clock"),
            "received_at": state.get("received_at"),
            "ai_result": state.get("ai_result"),
        }
        artifacts = [
            NodeArtifact(
                key=item.id,
                name=item.name,
                level=item.level,
                mime_type=item.mime_type,
                size_bytes=item.size_bytes,
                sha256=item.sha256,
                previewable=item.level
                in {ProductLevel.THUMBNAIL, ProductLevel.STAC, ProductLevel.AI_RESULT},
            )
            for item in products
            if item.artifact_path
        ]
        return NodeSnapshot(
            node=node,
            mission_id=mission_id,
            status=str(state.get("phase", "unknown")),
            observation_notice="仿真观察数据，未通过星地下传",
            state=public_state,
            artifacts=artifacts,
        )

    def artifact(self, mission_id: str, key: str, node: NodeKind) -> tuple[Path, ProductManifest]:
        snapshot = self.node_snapshot(mission_id, node)
        if key not in {item.key for item in snapshot.artifacts}:
            raise KeyError(key)
        state = self.missions[mission_id]
        manifest = next(
            ProductManifest.model_validate(value)
            for value in state.get("products", {}).values()
            if value.get("id") == key
        )
        path = Path(str(manifest.artifact_path)).resolve()
        if not path.is_file() or self.product_dir.resolve() not in path.parents:
            raise KeyError(key)
        return path, manifest


def create_app(app_settings: Settings = settings) -> FastAPI:
    state = PlatformState(app_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await state.start()
        yield
        await state.close()

    app = FastAPI(title="Satellite OBC Node", version=__version__, lifespan=lifespan)
    app.state.platform = state

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "platform-node",
            "version": __version__,
            "uplink_listener": app_settings.platform_uplink_port,
            "gtx_result_listener": app_settings.platform_gtx_result_port,
            "payload_result_listener": app_settings.platform_payload_result_port,
            "payloads": {"optical": "remote", "infrared": "not_implemented"},
        }

    @app.post("/internal/missions/{mission_id}/advance")
    async def advance(mission_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await state.advance(mission_id, body)

    @app.patch("/internal/missions/{mission_id}/prompt")
    async def update_prompt(mission_id: str, body: dict[str, Any]) -> dict[str, Any]:
        prompt = str(body.get("analysis_prompt") or "").strip()
        if not prompt:
            raise HTTPException(422, "analysis_prompt must not be empty")
        if len(prompt) > 2000:
            raise HTTPException(422, "analysis_prompt exceeds 2000 characters")
        try:
            return state.update_analysis_prompt(mission_id, prompt)
        except KeyError as exc:
            raise HTTPException(404, "mission not found") from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/internal/missions/{mission_id}")
    async def mission_state(mission_id: str) -> dict[str, Any]:
        value = state.missions.get(mission_id)
        if not value:
            raise HTTPException(404, "mission not found")
        return value

    @app.get("/internal/missions/{mission_id}/nodes/{node}", response_model=NodeSnapshot)
    async def node_snapshot(mission_id: str, node: NodeKind) -> NodeSnapshot:
        if node != NodeKind.PLATFORM:
            raise HTTPException(404, "node not hosted by platform")
        try:
            return state.node_snapshot(mission_id, node)
        except KeyError as exc:
            raise HTTPException(404, "mission not found") from exc

    @app.get("/internal/missions/{mission_id}/nodes/{node}/artifacts/{key}")
    async def node_artifact(mission_id: str, node: NodeKind, key: str):
        try:
            path, manifest = state.artifact(mission_id, key, node)
        except KeyError as exc:
            raise HTTPException(404, "artifact not found") from exc
        return FileResponse(path, media_type=manifest.mime_type, filename=manifest.name)

    return app


app = create_app()
