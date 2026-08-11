from __future__ import annotations

from datetime import UTC, datetime

from sat_simulation.common.models import ScenarioConfig
from sat_simulation.common.orbit import propagate, target_attitude


def test_sgp4_and_attitude_state_are_bounded() -> None:
    scenario = ScenarioConfig(epoch=datetime(2026, 5, 7, tzinfo=UTC))
    latitude, longitude, altitude = propagate(scenario, scenario.epoch)
    assert -90 <= latitude <= 90
    assert -180 <= longitude <= 180
    assert 300 <= altitude <= 1000
    state = target_attitude(scenario, scenario.epoch, 39.9042, 116.4074)
    assert len(state.quaternion_wxyz) == 4
    assert state.in_contact is True
    assert state.pointing_error_deg <= 0.1
