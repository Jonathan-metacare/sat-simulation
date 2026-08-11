from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sat_simulation.common.clock import SimulationClock
from sat_simulation.common.models import FaultRule, LinkKind, LinkProfile
from sat_simulation.common.protocol import Frame, LinkCode, MessageType, ProtocolError, read_frame


def _uuid(value: str) -> UUID:
    raw = value.rsplit("_", 1)[-1]
    try:
        return UUID(raw)
    except ValueError:
        return UUID(int=abs(hash(value)) % (1 << 128))


def _sim_ns(clock: SimulationClock) -> int:
    return int(clock.now().timestamp() * 1_000_000_000)


def link_code(kind: LinkKind) -> LinkCode:
    return {
        LinkKind.GTX: LinkCode.GTX,
        LinkKind.UPLINK: LinkCode.UPLINK,
        LinkKind.DOWNLINK: LinkCode.DOWNLINK,
    }[kind]


@dataclass
class TransferResult:
    transfer_id: str
    total_bytes: int
    frames: int
    retries: int
    crc_failures: int
    response: dict[str, Any]


Handler = Callable[[MessageType, bytes, Frame], Awaitable[dict[str, Any]]]


class TCPTransport:
    def __init__(
        self,
        *,
        profile: LinkProfile,
        clock: SimulationClock,
        fault: FaultRule | None = None,
        seed: int = 0,
    ) -> None:
        self.profile = profile
        self.clock = clock
        self.fault = fault
        self.rng = random.Random(seed)

    async def send(
        self,
        host: str,
        port: int,
        *,
        run_id: str,
        mission_id: str,
        message_type: MessageType,
        payload: bytes,
    ) -> TransferResult:
        if self.fault and self.fault.enabled and self.fault.disconnected:
            raise ConnectionError(f"{self.profile.kind} link is disconnected by fault rule")
        if len(payload) > self.profile.queue_capacity_bytes:
            raise BufferError("transfer exceeds configured link queue capacity")

        transfer_id = uuid4()
        chunks = [
            payload[index : index + self.profile.frame_payload_bytes]
            for index in range(0, len(payload), self.profile.frame_payload_bytes)
        ] or [b""]
        pending = set(range(len(chunks)))
        retries = 0
        crc_failures = 0
        response: dict[str, Any] = {}

        reader, writer = await asyncio.open_connection(host, port)
        try:
            while pending:
                order = list(sorted(pending))
                if self.fault and self.fault.enabled and self.fault.reorder:
                    self.rng.shuffle(order)
                sent_any = False
                for sequence in order:
                    drop = bool(
                        self.fault
                        and self.fault.enabled
                        and self.rng.random() < self.fault.drop_rate
                    )
                    if drop:
                        continue
                    corrupt = bool(
                        self.fault
                        and self.fault.enabled
                        and self.rng.random() < self.fault.corrupt_rate
                    )
                    duplicate = bool(
                        self.fault
                        and self.fault.enabled
                        and self.rng.random() < self.fault.duplicate_rate
                    )
                    frame = Frame(
                        link=link_code(self.profile.kind),
                        message_type=message_type,
                        transfer_id=transfer_id,
                        run_id=_uuid(run_id),
                        mission_id=_uuid(mission_id),
                        sequence=sequence,
                        total=len(chunks),
                        simulated_time_ns=_sim_ns(self.clock),
                        payload=chunks[sequence],
                    )
                    encoded = frame.encode(corrupt_crc=corrupt)
                    writer.write(encoded)
                    if duplicate:
                        writer.write(encoded)
                    await writer.drain()
                    sent_any = True
                    if corrupt:
                        crc_failures += 1
                    serialization = len(encoded) * 8 / self.profile.bandwidth_bps
                    await self.clock.sleep(serialization)

                eof = Frame(
                    link=link_code(self.profile.kind),
                    message_type=MessageType.EOF,
                    transfer_id=transfer_id,
                    run_id=_uuid(run_id),
                    mission_id=_uuid(mission_id),
                    sequence=len(chunks),
                    total=len(chunks),
                    simulated_time_ns=_sim_ns(self.clock),
                    # Carries the original application type so an all-dropped
                    # first attempt can still receive a selective NAK.
                    payload=bytes([int(message_type)]),
                )
                writer.write(eof.encode())
                await writer.drain()
                extra_ms = self.fault.extra_latency_ms if self.fault and self.fault.enabled else 0
                await self.clock.sleep((self.profile.latency_ms + extra_ms) / 1000)

                reply = await read_frame(reader)
                response = json.loads(reply.payload.decode("utf-8"))
                missing = {int(item) for item in response.get("missing", [])}
                if not missing:
                    pending.clear()
                    break
                pending = missing
                retries += 1
                if retries > self.profile.max_retries:
                    raise ConnectionError(
                        f"transfer failed after {retries} retries: {sorted(missing)}"
                    )
                if not sent_any and self.fault and self.fault.drop_rate >= 1:
                    raise ConnectionError("all frames dropped by active fault rule")
        finally:
            writer.close()
            await writer.wait_closed()
        return TransferResult(
            transfer_id=str(transfer_id),
            total_bytes=len(payload),
            frames=len(chunks),
            retries=retries,
            crc_failures=crc_failures,
            response=response.get("result", {}),
        )


class TCPReceiver:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.server: asyncio.Server | None = None

    async def start(self, host: str, port: int) -> None:
        self.server = await asyncio.start_server(self._handle, host, port)

    async def close(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        chunks: dict[int, bytes] = {}
        first: Frame | None = None
        try:
            while True:
                try:
                    frame = await read_frame(reader)
                except ProtocolError:
                    # The fixed header can still be inspected only by read_frame; a corrupt
                    # payload consumes the complete frame and the next EOF requests retry.
                    continue
                if first is None and frame.message_type != MessageType.EOF:
                    first = frame
                if frame.message_type == MessageType.EOF:
                    if first is None:
                        if not frame.payload:
                            raise ProtocolError("EOF received before data")
                        first = Frame(
                            link=frame.link,
                            message_type=MessageType(frame.payload[0]),
                            transfer_id=frame.transfer_id,
                            run_id=frame.run_id,
                            mission_id=frame.mission_id,
                            sequence=0,
                            total=frame.total,
                            simulated_time_ns=frame.simulated_time_ns,
                            payload=b"",
                        )
                    missing = sorted(set(range(frame.total)) - set(chunks))
                    if missing:
                        await self._reply(writer, first, MessageType.NAK, {"missing": missing})
                        continue
                    payload = b"".join(chunks[index] for index in range(frame.total))
                    result = await self.handler(first.message_type, payload, first)
                    await self._reply(
                        writer,
                        first,
                        MessageType.ACK,
                        {"missing": [], "result": result},
                    )
                    break
                chunks[frame.sequence] = frame.payload
        except (asyncio.IncompleteReadError, ConnectionError, ProtocolError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def _reply(
        self,
        writer: asyncio.StreamWriter,
        source: Frame,
        message_type: MessageType,
        payload: dict[str, Any],
    ) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        reply = Frame(
            link=source.link,
            message_type=message_type,
            transfer_id=source.transfer_id,
            run_id=source.run_id,
            mission_id=source.mission_id,
            sequence=0,
            total=1,
            simulated_time_ns=int(datetime.now(UTC).timestamp() * 1_000_000_000),
            payload=encoded,
        )
        writer.write(reply.encode())
        await writer.drain()
