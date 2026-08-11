from __future__ import annotations

from uuid import uuid4

import pytest

from sat_simulation.common.protocol import (
    Frame,
    LinkCode,
    MessageType,
    ProtocolError,
    crc32c,
)


def test_crc32c_known_vector() -> None:
    assert crc32c(b"123456789") == 0xE3069283


def test_frame_roundtrip_and_crc_failure() -> None:
    frame = Frame(
        link=LinkCode.GTX,
        message_type=MessageType.AI_JOB,
        transfer_id=uuid4(),
        run_id=uuid4(),
        mission_id=uuid4(),
        sequence=2,
        total=5,
        simulated_time_ns=123456,
        payload=b"payload",
    )
    encoded = frame.encode()
    assert Frame.decode(encoded) == frame
    damaged = encoded[:-1] + bytes([encoded[-1] ^ 1])
    with pytest.raises(ProtocolError, match="CRC32C"):
        Frame.decode(damaged)
