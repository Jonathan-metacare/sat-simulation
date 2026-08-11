from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sat_simulation.common.clock import SimulationClock


@pytest.mark.asyncio
async def test_clock_pause_step_and_reset() -> None:
    epoch = datetime(2026, 8, 11, tzinfo=UTC)
    clock = SimulationClock(epoch, rate=10)
    assert clock.state().paused is True
    stepped = await clock.step(5)
    assert stepped.simulated_at == datetime(2026, 8, 11, 0, 0, 5, tzinfo=UTC)
    await clock.resume()
    with pytest.raises(RuntimeError):
        await clock.step(1)
    paused = await clock.pause()
    assert paused.paused is True
    old_run = paused.run_id
    reset = await clock.reset(epoch)
    assert reset.run_id != old_run
    assert reset.simulated_at == epoch


@pytest.mark.asyncio
async def test_clock_rejects_unsupported_rate() -> None:
    clock = SimulationClock()
    with pytest.raises(ValueError):
        await clock.set_rate(5)
