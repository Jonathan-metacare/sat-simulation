from __future__ import annotations

import pytest
from pydantic import ValidationError

from sat_simulation.common.models import SatelliteCreateRequest
from sat_simulation.services.ground import new_satellite_config


def request(**changes: object) -> SatelliteCreateRequest:
    values: dict[str, object] = {
        "satellite_name": "SAT-TEST-01",
        "tle_line1": "1 55244U 23006C   26126.66766851  .00004587  00000-0  24048-3 0  9998",
        "tle_line2": "2 55244  43.1978 352.6432 0015896 112.1710 248.0829 15.16807012183579",
        "ground_station_name": "GS-TEST",
        "latitude": 39.9042,
        "longitude": 116.4074,
        "altitude_m": 50,
    }
    values.update(changes)
    return SatelliteCreateRequest.model_validate(values)


def test_new_satellite_uses_safe_scenario_defaults() -> None:
    config = new_satellite_config(request())

    assert config.id.startswith("scenario_")
    assert config.name == "SAT-TEST-01"
    assert config.scene_id == f"{config.id}-scene"
    assert config.scene_ready is False
    assert config.l0_processor_id == "builtin-l0"
    assert config.l1_processor_id == "builtin-l1"
    assert config.clock_rate == 10


def test_new_satellite_rejects_invalid_tle() -> None:
    with pytest.raises(ValueError, match="TLE"):
        new_satellite_config(request(tle_line1="not a TLE"))


@pytest.mark.parametrize("field,value", [("satellite_name", "  "), ("latitude", 91), ("longitude", -181)])
def test_new_satellite_request_validates_user_fields(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        request(**{field: value})
