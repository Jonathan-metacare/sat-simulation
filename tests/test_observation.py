from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from sat_simulation.common.models import (
    NodeKind,
    ProductLevel,
    ProductManifest,
    ProtocolFrameTrace,
    ProtocolLinkKind,
    ProtocolTransaction,
)
from sat_simulation.common.observation import describe_payload, redact_sensitive
from sat_simulation.common.protocol import MessageType
from sat_simulation.common.wire import pack_json, pack_product, pack_product_bundle
from sat_simulation.storage import Repository


def test_recursive_redaction_and_json_payload_view() -> None:
    body = {
        "mission_id": "mission-demo",
        "options": {
            "api_token": "never-store-me",
            "nested": [{"password": "also-secret"}, {"value": 7}],
        },
    }
    clean, redacted = redact_sensitive(body)
    assert redacted is True
    assert clean["options"]["api_token"] == "[REDACTED]"
    assert clean["options"]["nested"][0]["password"] == "[REDACTED]"

    view = describe_payload(MessageType.AI_EXECUTE, pack_json(body))
    assert view.kind == "json"
    assert view.redacted is True
    assert view.decoded_json["options"]["api_token"] == "[REDACTED]"


def test_product_envelope_is_summarized_without_binary_hex(tmp_path) -> None:
    path = tmp_path / "l1b.tif"
    path.write_bytes(b"binary-geotiff-content")
    manifest = ProductManifest(
        run_id="run-test", mission_id="mission-test", level=ProductLevel.L1B,
        name=path.name, mime_type="image/tiff", size_bytes=path.stat().st_size,
        sha256="a" * 64,
    )
    view = describe_payload(MessageType.PRODUCT, pack_product(manifest, path))
    assert view.kind == "binary"
    assert view.summary["name"] == "l1b.tif"
    assert view.summary["content_bytes"] == path.stat().st_size
    assert "hex" not in view.summary


def test_product_bundle_is_summarized_without_binary_hex(tmp_path) -> None:
    path = tmp_path / "l0.npy"
    path.write_bytes(b"binary-l0-content")
    manifest = ProductManifest(
        run_id="run-test", mission_id="mission-test", level=ProductLevel.L0,
        name=path.name, mime_type="application/x-npy", size_bytes=path.stat().st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    view = describe_payload(
        MessageType.L1_JOB,
        pack_product_bundle([manifest], {manifest.id: path}),
    )
    assert view.kind == "binary"
    assert view.summary["envelope"] == "ProductBundle/1"
    assert view.summary["members"][0]["name"] == "l0.npy"
    assert "hex" not in view.summary


@pytest.mark.asyncio
async def test_protocol_transaction_and_frames_are_persistent(tmp_path) -> None:
    repo = Repository(f"sqlite+aiosqlite:///{tmp_path / 'protocol.db'}")
    await repo.init()
    try:
        transaction = ProtocolTransaction(
            id="tx-1", run_id="run-1", mission_id="mission-1",
            link=ProtocolLinkKind.GTX, message_type="L1_JOB",
            source_node=NodeKind.PLATFORM, target_node=NodeKind.GPU,
            direction="platform->gpu",
        )
        await repo.upsert_protocol_transaction(transaction)
        frame = ProtocolFrameTrace(
            transaction_id=transaction.id, sequence=0, total=1,
            message_type="L1_JOB", payload_bytes=64,
            simulated_at=datetime(2026, 8, 12, tzinfo=UTC), crc32c="1234abcd",
            ack_status="nak", missing_sequences=[0],
        )
        await repo.add_protocol_frame(frame)

        stored = await repo.get_protocol_transaction(transaction.id)
        assert stored is not None
        assert stored.direction == "platform->gpu"
        frames = await repo.list_protocol_frames(transaction.id)
        assert frames[0].ack_status == "nak"
        assert frames[0].missing_sequences == [0]
    finally:
        await repo.close()
