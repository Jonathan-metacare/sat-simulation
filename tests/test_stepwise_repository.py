from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sat_simulation.common.clock import SimulationClock
from sat_simulation.common.models import (
    ExecutionState,
    MissionCommand,
    MissionPhase,
    MissionStatus,
    ScenarioConfig,
)
from sat_simulation.common.orbit import plan_mission_windows
from sat_simulation.services.ground import PHASE_FLOW
from sat_simulation.storage import Repository


@pytest.mark.asyncio
async def test_step_attempt_is_persistent_idempotent_and_does_not_jump_phase(tmp_path) -> None:
    repository = Repository(f"sqlite+aiosqlite:///{tmp_path / 'stepwise.db'}")
    await repository.init()
    try:
        scenario = ScenarioConfig(
            id="scenario-stepwise",
            epoch=datetime(2026, 5, 7, tzinfo=UTC),
        )
        clock = SimulationClock(scenario.epoch)
        await repository.create_scenario(scenario, clock.state())
        plan = plan_mission_windows(scenario, scenario.epoch)
        command = MissionCommand(
            run_id=clock.state().run_id,
            scenario_id=scenario.id,
            planned_windows=plan,
            target_name=plan.target_name,
            target_latitude=plan.target_latitude,
            target_longitude=plan.target_longitude,
        )
        await repository.create_mission(command)

        attempt, duplicate = await repository.begin_step(
            command.id,
            target_phase=MissionPhase.UPLINK_COMPLETE,
            idempotency_key=f"{command.id}:step-1",
            active_substage="uplink",
        )
        assert duplicate is False
        running = await repository.get_mission(command.id)
        assert running is not None
        assert running["phase"] == MissionPhase.INITIALIZED
        assert running["execution_state"] == ExecutionState.RUNNING

        same, duplicate = await repository.begin_step(
            command.id,
            target_phase=MissionPhase.UPLINK_COMPLETE,
            idempotency_key=f"{command.id}:step-1",
            active_substage="uplink",
        )
        assert duplicate is True
        assert same.id == attempt.id

        await repository.finish_step(
            command.id,
            attempt.id,
            phase=MissionPhase.UPLINK_COMPLETE,
            execution_state=ExecutionState.WAITING,
            status=MissionStatus.UPLINKING,
        )
        completed = await repository.get_mission(command.id)
        assert completed is not None
        assert completed["phase"] == MissionPhase.UPLINK_COMPLETE
        assert completed["execution_state"] == ExecutionState.WAITING
        assert await repository.active_mission_for_scenario(scenario.id) == command.id

        persisted = await repository.get_attempt_by_idempotency_key(f"{command.id}:step-1")
        assert persisted is not None
        assert persisted.id == attempt.id
        assert persisted.state == ExecutionState.WAITING

        await repository.begin_step(
            command.id,
            target_phase=MissionPhase.CAPTURE_COMPLETE,
            idempotency_key=f"{command.id}:step-2",
            active_substage="capture",
        )
        assert await repository.recover_running_missions() == 1
        recovered = await repository.get_mission(command.id)
        assert recovered is not None
        assert recovered["phase"] == MissionPhase.UPLINK_COMPLETE
        assert recovered["execution_state"] == ExecutionState.RETRYABLE_ERROR
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_cancelled_mission_releases_scenario_and_preserves_history(tmp_path) -> None:
    repository = Repository(f"sqlite+aiosqlite:///{tmp_path / 'cancel.db'}")
    await repository.init()
    try:
        scenario = ScenarioConfig(id="scenario-cancel", epoch=datetime(2026, 5, 7, tzinfo=UTC))
        clock = SimulationClock(scenario.epoch)
        await repository.create_scenario(scenario, clock.state())
        command = MissionCommand(run_id=clock.state().run_id, scenario_id=scenario.id)
        await repository.create_mission(command)

        assert await repository.active_mission_for_scenario(scenario.id) == command.id
        await repository.cancel_mission(command.id)

        cancelled = await repository.get_mission(command.id)
        assert cancelled is not None
        assert cancelled["status"] == MissionStatus.CANCELLED
        assert cancelled["execution_state"] == ExecutionState.CANCELLED
        assert cancelled["phase"] == MissionPhase.INITIALIZED
        assert await repository.active_mission_for_scenario(scenario.id) is None
        with pytest.raises(RuntimeError, match="任务已经结束"):
            await repository.begin_step(
                command.id,
                target_phase=MissionPhase.UPLINK_COMPLETE,
                idempotency_key=f"{command.id}:after-cancel",
                active_substage="uplink",
            )
    finally:
        await repository.close()


def test_processing_macro_finishes_with_l1b_status() -> None:
    target_phase, substage, _label, status = PHASE_FLOW[MissionPhase.CAPTURE_COMPLETE]

    assert target_phase == MissionPhase.PROCESSING_COMPLETE
    assert substage == "processing"
    assert status == MissionStatus.L1B_PROCESSING
