from __future__ import annotations

from datetime import UTC, datetime

from sat_simulation.common.models import ScenarioConfig
from sat_simulation.common.orbit import orbit_track, propagate, target_attitude, visibility_radius_m


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


def test_orbit_track_uses_sgp4_and_predicts_contact_windows() -> None:
    scenario = ScenarioConfig(epoch=datetime(2026, 5, 7, tzinfo=UTC))
    track = orbit_track(scenario, scenario.epoch)

    assert len(track.history) == 40
    assert len(track.forecast) == 160
    assert track.current.sampled_at == scenario.epoch
    assert track.visibility_radius_m > 1_000_000
    assert track.contact_windows
    assert all(window.los > window.aos for window in track.contact_windows)
    assert visibility_radius_m(track.current.altitude_km) == track.visibility_radius_m
