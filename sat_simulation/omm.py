"""KeepTrack OMM normalization and standards-compliant TLE export."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sgp4.api import Satrec
from sgp4.exporter import export_tle
from sgp4.omm import initialize

REQUIRED_OMM_FIELDS = {
    "NORAD_CAT_ID", "OBJECT_NAME", "OBJECT_ID", "EPOCH", "MEAN_MOTION",
    "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER",
    "MEAN_ANOMALY", "EPHEMERIS_TYPE", "CLASSIFICATION_TYPE", "ELEMENT_SET_NO",
    "REV_AT_EPOCH", "BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT",
}


def _value(payload: dict[str, Any], field: str) -> Any:
    aliases = {
        "NORAD_CAT_ID": ("noradCatId", "norad_id", "sccNum"),
        "OBJECT_NAME": ("objectName", "name"),
        "OBJECT_ID": ("objectId",),
        "RA_OF_ASC_NODE": ("raOfAscNode",),
        "ARG_OF_PERICENTER": ("argOfPericenter",),
        "MEAN_ANOMALY": ("meanAnomaly",),
        "MEAN_MOTION": ("meanMotion",),
        "MEAN_MOTION_DOT": ("meanMotionDot",),
        "MEAN_MOTION_DDOT": ("meanMotionDdot",),
        "EPHEMERIS_TYPE": ("ephemerisType",),
        "CLASSIFICATION_TYPE": ("classificationType",),
        "ELEMENT_SET_NO": ("elementSetNo",),
        "REV_AT_EPOCH": ("revAtEpoch",),
    }
    if field in payload:
        return payload[field]
    return next((payload[key] for key in aliases.get(field, ()) if key in payload), None)


def _epoch(value: Any) -> str:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text).astimezone(UTC)
    except ValueError as exc:
        raise ValueError("OMM EPOCH is invalid") from exc
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.%f")


def extract_omm(payload: Any, norad_id: int) -> dict[str, Any]:
    """Accept common KeepTrack response envelopes and return canonical OMM fields."""
    candidates: list[Any]
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        nested = payload.get("omm") or payload.get("data") or payload.get("result")
        candidates = nested if isinstance(nested, list) else [nested or payload]
    else:
        raise ValueError("KeepTrack returned an invalid OMM response")
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        current = {field: _value(candidate, field) for field in REQUIRED_OMM_FIELDS}
        if str(current["NORAD_CAT_ID"] or "").strip() != str(norad_id):
            continue
        missing = [
            field for field, value in current.items() if value is None or str(value).strip() == ""
        ]
        if missing:
            raise ValueError(f"OMM is missing required fields: {', '.join(sorted(missing))}")
        current["EPOCH"] = _epoch(current["EPOCH"])
        return {field: str(value).strip() for field, value in current.items()}
    raise LookupError(f"NORAD {norad_id} was not found in KeepTrack response")


def omm_to_tle(omm: dict[str, Any]) -> tuple[str, str]:
    satellite = Satrec()
    try:
        initialize(satellite, omm)
        tle_line1, tle_line2 = export_tle(satellite)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"OMM cannot be converted to TLE: {exc}") from exc
    if satellite.error:
        raise ValueError(f"OMM conversion produced SGP4 error code {satellite.error}")
    return tle_line1, tle_line2


def omm_hash(omm: dict[str, Any]) -> str:
    encoded = json.dumps(omm, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
