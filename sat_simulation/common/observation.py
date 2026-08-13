from __future__ import annotations

import hashlib
import json
from zipfile import BadZipFile
from typing import Any

from sat_simulation.common.models import ProtocolPayloadView
from sat_simulation.common.protocol import MessageType
from sat_simulation.common.wire import unpack_product, unpack_product_bundle

SENSITIVE_PARTS = ("key", "token", "secret", "auth", "password")
JSON_MESSAGES = {
    MessageType.COMMAND,
    MessageType.CONTROL,
    MessageType.EVENT,
    MessageType.AI_EXECUTE,
    MessageType.AI_RESULT,
    MessageType.RESULT_REQUEST,
}


def redact_sensitive(value: Any) -> tuple[Any, bool]:
    redacted = False
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if any(part in key.lower() for part in SENSITIVE_PARTS):
                output[key] = "[REDACTED]"
                redacted = True
            else:
                output[key], child = redact_sensitive(item)
                redacted = redacted or child
        return output, redacted
    if isinstance(value, list):
        output = []
        for item in value:
            clean, child = redact_sensitive(item)
            output.append(clean)
            redacted = redacted or child
        return output, redacted
    return value, False


def describe_payload(message_type: MessageType, payload: bytes) -> ProtocolPayloadView:
    if message_type in JSON_MESSAGES:
        try:
            decoded = json.loads(payload.decode("utf-8"))
            clean, redacted = redact_sensitive(decoded)
            if isinstance(clean, dict):
                return ProtocolPayloadView(
                    kind="json",
                    mime_type="application/json",
                    decoded_json=clean,
                    summary={"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
                    redacted=redacted,
                )
        except (UnicodeDecodeError, ValueError):
            pass
    if message_type in {
        MessageType.PRODUCT,
        MessageType.AI_JOB,
        MessageType.RESULT_PACKAGE,
    }:
        try:
            manifest, content = unpack_product(payload)
            members = manifest.processing_parameters.get("members", {})
            return ProtocolPayloadView(
                kind="binary",
                mime_type=manifest.mime_type,
                summary={
                    "envelope": "ProductEnvelope/1",
                    "product_id": manifest.id,
                    "level": manifest.level,
                    "name": manifest.name,
                    "content_bytes": len(content),
                    "sha256": manifest.sha256,
                    "members": members,
                },
            )
        except ValueError:
            pass
    if message_type in {MessageType.L1_JOB, MessageType.L1_PRODUCTS}:
        try:
            manifests, files = unpack_product_bundle(payload)
            return ProtocolPayloadView(
                kind="binary",
                mime_type="application/zip",
                summary={
                    "envelope": "ProductBundle/1",
                    "members": [
                        {
                            "name": item.name,
                            "level": item.level,
                            "content_bytes": len(files[item.name]),
                            "sha256": item.sha256,
                        }
                        for item in manifests
                    ],
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
            )
        except (BadZipFile, KeyError, ValueError, OSError):
            pass
    return ProtocolPayloadView(
        kind="binary" if payload else "none",
        mime_type="application/octet-stream" if payload else None,
        summary={"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        if payload
        else {},
    )
