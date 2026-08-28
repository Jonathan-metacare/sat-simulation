from __future__ import annotations

import pytest
from pydantic import ValidationError
from sgp4.api import Satrec

from sat_simulation.common.models import (
    ImportedScenarioYaml,
    LinkKind,
    MissionCommand,
    ScenarioConfig,
    default_link_profiles,
)


def valid_yaml_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "Imported scene",
        "seed": 42,
        "clock_rate": 10,
        "satellite": {
            "name": "SIM-OPTICAL-01",
            "tle_line1": "1 55244U 23006C   26126.66766851  .00004587  00000-0  24048-3 0  9998",
            "tle_line2": "2 55244  43.1978 352.6432 0015896 112.1710 248.0829 15.16807012183579",
        },
        "ground_station": {
            "id": "GS-DEMO-BEIJING",
            "simulated": True,
            "latitude": 39.9042,
            "longitude": 116.4074,
            "altitude_m": 50,
        },
        "links": {
            "gtx": {"bandwidth_bps": 2.5e9, "latency_ms": 0.2},
            "uplink": {"bandwidth_bps": 2e6, "latency_ms": 20},
            "downlink": {"bandwidth_bps": 150e6, "latency_ms": 20},
        },
        "sensor": {
            "bit_depth": 12,
            "gain": 1,
            "offset_dn": 32,
            "dark_current_dn": 4,
            "read_noise_dn": 0,
            "prnu_sigma": 0,
            "bad_pixel_rate": 0,
        },
    }


def test_yaml_rejects_unknown_and_nested_invalid_fields() -> None:
    payload = valid_yaml_payload()
    payload["unknown"] = "not accepted"
    with pytest.raises(ValidationError) as unknown:
        ImportedScenarioYaml.model_validate(payload)
    assert unknown.value.errors()[0]["loc"] == ("unknown",)

    payload = valid_yaml_payload()
    payload["links"]["gtx"]["bandwidth_bps"] = 0  # type: ignore[index]
    with pytest.raises(ValidationError) as invalid:
        ImportedScenarioYaml.model_validate(payload)
    assert invalid.value.errors()[0]["loc"] == ("links", "gtx", "bandwidth_bps")


def test_yaml_tle_and_scenario_snapshot_are_frozen() -> None:
    imported = ImportedScenarioYaml.model_validate(valid_yaml_payload())
    Satrec.twoline2rv(imported.satellite.tle_line1, imported.satellite.tle_line2)
    profiles = default_link_profiles()
    profiles[LinkKind.GTX] = profiles[LinkKind.GTX].model_copy(
        update={"bandwidth_bps": imported.links.gtx.bandwidth_bps}
    )
    scenario = ScenarioConfig(
        id="scenario-imported",
        scene_id="scene-imported",
        scene_ready=False,
        satellite_name=imported.satellite.name,
        tle_line1=imported.satellite.tle_line1,
        tle_line2=imported.satellite.tle_line2,
        links=profiles,
        sensor=imported.sensor,
    )
    command = MissionCommand(
        run_id="run-imported", scenario_id=scenario.id, scenario_snapshot=scenario
    )

    assert command.scenario_snapshot is not None
    assert command.scenario_snapshot.link_profile(LinkKind.GTX).bandwidth_bps == 2.5e9
    assert command.scenario_snapshot.sensor.bit_depth == 12
    assert command.scenario_snapshot.scene_ready is False
