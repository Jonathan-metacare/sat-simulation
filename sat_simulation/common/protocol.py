from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from uuid import UUID

MAGIC = b"SIMF"
PROTOCOL_VERSION = 1
HEADER = struct.Struct("!4sBBH16s16s16sIIIQI")


class ProtocolError(ValueError):
    pass


class LinkCode(IntEnum):
    GTX = 1
    UPLINK = 2
    DOWNLINK = 3


class MessageType(IntEnum):
    COMMAND = 1
    CONTROL = 2
    EVENT = 3
    PRODUCT = 4
    AI_JOB = 5
    AI_RESULT = 6
    EOF = 7
    ACK = 8
    NAK = 9
    AI_EXECUTE = 10
    RESULT_REQUEST = 11
    RESULT_PACKAGE = 12


def crc32c(data: bytes, crc: int = 0) -> int:
    """Castagnoli CRC-32C without a platform-specific dependency."""
    value = crc ^ 0xFFFFFFFF
    for byte in data:
        value ^= byte
        for _ in range(8):
            mask = -(value & 1)
            value = (value >> 1) ^ (0x82F63B78 & mask)
    return value ^ 0xFFFFFFFF


@dataclass(frozen=True)
class Frame:
    link: LinkCode
    message_type: MessageType
    transfer_id: UUID
    run_id: UUID
    mission_id: UUID
    sequence: int
    total: int
    simulated_time_ns: int
    payload: bytes

    def encode(self, *, corrupt_crc: bool = False) -> bytes:
        checksum = crc32c(self.payload)
        if corrupt_crc:
            checksum ^= 0xFFFFFFFF
        return (
            HEADER.pack(
                MAGIC,
                PROTOCOL_VERSION,
                int(self.link),
                int(self.message_type),
                self.transfer_id.bytes,
                self.run_id.bytes,
                self.mission_id.bytes,
                self.sequence,
                self.total,
                len(self.payload),
                self.simulated_time_ns,
                checksum,
            )
            + self.payload
        )

    @classmethod
    def decode(cls, data: bytes) -> Frame:
        if len(data) < HEADER.size:
            raise ProtocolError("truncated frame header")
        fields = HEADER.unpack(data[: HEADER.size])
        magic, version, link, msg_type = fields[:4]
        if magic != MAGIC:
            raise ProtocolError("invalid frame magic")
        if version != PROTOCOL_VERSION:
            raise ProtocolError(f"unsupported protocol version {version}")
        payload_len = fields[9]
        payload = data[HEADER.size :]
        if len(payload) != payload_len:
            raise ProtocolError("payload length mismatch")
        expected_crc = fields[11]
        if crc32c(payload) != expected_crc:
            raise ProtocolError("CRC32C mismatch")
        return cls(
            link=LinkCode(link),
            message_type=MessageType(msg_type),
            transfer_id=UUID(bytes=fields[4]),
            run_id=UUID(bytes=fields[5]),
            mission_id=UUID(bytes=fields[6]),
            sequence=fields[7],
            total=fields[8],
            simulated_time_ns=fields[10],
            payload=payload,
        )


async def read_frame(reader) -> Frame:
    header = await reader.readexactly(HEADER.size)
    fields = HEADER.unpack(header)
    payload = await reader.readexactly(fields[9])
    return Frame.decode(header + payload)
