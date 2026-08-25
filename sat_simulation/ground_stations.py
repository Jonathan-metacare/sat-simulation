"""SatNOGS station catalog payload validation for local use."""

from __future__ import annotations

import json
from typing import Any


def _number(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"station {field} is invalid") from exc


def normalize_satnogs_station(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("station name is missing")
    try:
        station_id = int(payload["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Station id is invalid") from exc
    latitude = _number(payload.get("lat"), "latitude")
    longitude = _number(payload.get("lng"), "longitude")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Station coordinates are out of range")
    min_horizon = payload.get("min_horizon")
    return {
        "station_id": station_id,
        "name": name,
        "latitude": latitude,
        "longitude": longitude,
        "altitude_m": _number(payload.get("altitude"), "altitude"),
        "min_horizon": _number(min_horizon, "min_horizon") if min_horizon not in (None, "") else None,
        "status": str(payload.get("status") or "unknown").strip(),
        "created": str(payload.get("created") or "").strip() or None,
        "last_seen": str(payload.get("last_seen") or "").strip() or None,
        "raw_json": json.dumps(payload, sort_keys=True),
    }
