from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sat_simulation.common.clock import SimulationClock
from sat_simulation.common.link import TCPReceiver, TCPTransport
from sat_simulation.common.models import FaultRule, LinkKind, LinkProfile
from sat_simulation.common.protocol import MessageType


@pytest.mark.asyncio
async def test_tcp_transfer_uses_frames_and_separate_receiver() -> None:
    received: list[bytes] = []

    async def handler(message_type, payload, _frame):
        assert message_type == MessageType.PRODUCT
        received.append(payload)
        return {"sha": "accepted"}

    receiver = TCPReceiver(handler)
    await receiver.start("127.0.0.1", 0)
    port = receiver.server.sockets[0].getsockname()[1]
    clock = SimulationClock(datetime(2026, 8, 11, tzinfo=UTC), rate=100)
    await clock.resume()
    profile = LinkProfile(
        kind=LinkKind.GTX,
        bandwidth_bps=10e9,
        latency_ms=0,
        frame_payload_bytes=1024,
        max_retries=5,
    )
    transport = TCPTransport(
        profile=profile,
        clock=clock,
        fault=FaultRule(
            link=LinkKind.GTX,
            drop_rate=0.12,
            corrupt_rate=0.08,
            duplicate_rate=0.5,
            reorder=True,
        ),
        seed=9,
    )
    payload = bytes(range(256)) * 40
    result = await transport.send(
        "127.0.0.1",
        port,
        run_id="run_00000000000000000000000000000001",
        mission_id="mission_00000000000000000000000000000002",
        message_type=MessageType.PRODUCT,
        payload=payload,
    )
    await receiver.close()
    assert received == [payload]
    assert result.frames == 10
    assert result.response == {"sha": "accepted"}
    assert result.retries >= 1
