from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from sat_simulation.common.clock import SimulationClock
from sat_simulation.common.link import TCPReceiver, TCPTransport
from sat_simulation.common.models import LinkKind, MissionCommand, ProductLevel, ScenarioConfig
from sat_simulation.common.protocol import MessageType
from sat_simulation.common.wire import pack_json, unpack_product
from sat_simulation.config import Settings
from sat_simulation.services.optical import OpticalState


@pytest.mark.asyncio
async def test_independent_optical_node_returns_raw_and_l0_over_tcp(tmp_path) -> None:
    received = {}

    async def platform_result(message_type, payload, _frame):
        manifest, content = unpack_product(payload)
        assert hashlib.sha256(content).hexdigest() == manifest.sha256
        received[message_type] = (manifest, content)
        return {"sha256": manifest.sha256}

    result_receiver = TCPReceiver(platform_result)
    await result_receiver.start("127.0.0.1", 0)
    result_port = result_receiver.server.sockets[0].getsockname()[1]
    settings = Settings(
        data_dir=tmp_path,
        host="127.0.0.1",
        optical_payload_port=0,
        platform_payload_result_host="127.0.0.1",
        platform_payload_result_port=result_port,
        ground_http_url="http://127.0.0.1:1",
    )
    optical = OpticalState(settings)
    await optical.start()
    optical_port = optical.receiver.server.sockets[0].getsockname()[1]
    scenario = ScenarioConfig(
        id="scenario-optical-integration",
        scene_asset_id="demo-optical-scene",
    )
    command = MissionCommand(
        id="mission-optical-integration",
        run_id="run-optical-integration",
        scenario_id=scenario.id,
        scene_asset_id="demo-optical-scene",
        scenario_snapshot=scenario,
    )
    clock = SimulationClock(datetime(2026, 8, 18, tzinfo=UTC), rate=100)
    transport = TCPTransport(profile=scenario.link_profile(LinkKind.PAYLOAD_BUS), clock=clock)
    body = pack_json(
        {
            "command": command.model_dump(mode="json"),
            "scenario": scenario.model_dump(mode="json"),
            "simulated_at": clock.now().isoformat(),
        }
    )
    try:
        await transport.send(
            "127.0.0.1",
            optical_port,
            run_id=command.run_id,
            mission_id=command.id,
            message_type=MessageType.CAPTURE_REQUEST,
            payload=body,
        )
        await transport.send(
            "127.0.0.1",
            optical_port,
            run_id=command.run_id,
            mission_id=command.id,
            message_type=MessageType.L0_PROCESS_REQUEST,
            payload=body,
        )
    finally:
        await optical.close()
        await result_receiver.close()
    assert received[MessageType.RAW_PRODUCT][0].level == ProductLevel.RAW
    assert received[MessageType.L0_PRODUCT][0].level == ProductLevel.L0
    assert received[MessageType.RAW_PRODUCT][0].sha256 != received[MessageType.L0_PRODUCT][0].sha256


@pytest.mark.asyncio
async def test_builtin_l0_does_not_require_desktop_seatbelt(tmp_path) -> None:
    """The default mission path remains available if Seatbelt is unavailable."""
    received = {}

    async def platform_result(message_type, payload, _frame):
        manifest, content = unpack_product(payload)
        received[message_type] = (manifest, content)
        return {"sha256": manifest.sha256}

    result_receiver = TCPReceiver(platform_result)
    await result_receiver.start("127.0.0.1", 0)
    result_port = result_receiver.server.sockets[0].getsockname()[1]
    settings = Settings(
        data_dir=tmp_path,
        host="127.0.0.1",
        optical_payload_port=0,
        platform_payload_result_host="127.0.0.1",
        platform_payload_result_port=result_port,
        ground_http_url="http://127.0.0.1:1",
        oci_runtime="desktop-sandbox",
    )
    optical = OpticalState(settings)
    await optical.start()
    optical.runner.run = None  # type: ignore[method-assign]
    optical_port = optical.receiver.server.sockets[0].getsockname()[1]
    scenario = ScenarioConfig(id="scenario-desktop-builtin", scene_asset_id="demo-optical-scene")
    command = MissionCommand(
        id="mission-desktop-builtin",
        run_id="run-desktop-builtin",
        scenario_id=scenario.id,
        scene_asset_id="demo-optical-scene",
        scenario_snapshot=scenario,
    )
    clock = SimulationClock(datetime(2026, 8, 18, tzinfo=UTC), rate=100)
    transport = TCPTransport(profile=scenario.link_profile(LinkKind.PAYLOAD_BUS), clock=clock)
    body = pack_json(
        {
            "command": command.model_dump(mode="json"),
            "scenario": scenario.model_dump(mode="json"),
            "simulated_at": clock.now().isoformat(),
        }
    )
    try:
        await transport.send(
            "127.0.0.1",
            optical_port,
            run_id=command.run_id,
            mission_id=command.id,
            message_type=MessageType.CAPTURE_REQUEST,
            payload=body,
        )
        await transport.send(
            "127.0.0.1",
            optical_port,
            run_id=command.run_id,
            mission_id=command.id,
            message_type=MessageType.L0_PROCESS_REQUEST,
            payload=body,
        )
    finally:
        await optical.close()
        await result_receiver.close()
    assert received[MessageType.L0_PRODUCT][0].level == ProductLevel.L0
