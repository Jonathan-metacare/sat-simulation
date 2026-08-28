from __future__ import annotations

import pytest
from pydantic import ValidationError

from sat_simulation.common.models import AIMode, MissionCommand, MissionCreate


def test_new_missions_are_llm_only() -> None:
    request = MissionCreate(scenario_id="scenario")
    assert request.ai_mode == AIMode.LLM
    with pytest.raises(ValidationError):
        MissionCreate(scenario_id="scenario", ai_mode="yolo")


def test_historical_yolo_commands_remain_readable() -> None:
    command = MissionCommand(run_id="run", scenario_id="scenario", ai_mode="yolo")
    assert command.ai_mode == AIMode.LEGACY_YOLO
