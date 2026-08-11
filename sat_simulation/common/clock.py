from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4

from sat_simulation.common.models import SimulationClockState


class SimulationClock:
    """Thread-safe scaled clock used by all simulated timing paths."""

    def __init__(self, epoch: datetime | None = None, rate: int = 1) -> None:
        self._run_id = str(uuid4())
        self._base_simulated = (epoch or datetime.now(UTC)).astimezone(UTC)
        self._base_monotonic = monotonic()
        self._rate = rate
        self._paused = True
        self._revision = 0
        self._condition = asyncio.Condition()

    def now(self) -> datetime:
        if self._paused:
            return self._base_simulated
        elapsed = monotonic() - self._base_monotonic
        return self._base_simulated + timedelta(seconds=elapsed * self._rate)

    def state(self) -> SimulationClockState:
        return SimulationClockState(
            run_id=self._run_id,
            simulated_at=self.now(),
            rate=self._rate,
            paused=self._paused,
            revision=self._revision,
        )

    async def start(self) -> SimulationClockState:
        return await self.resume()

    async def pause(self) -> SimulationClockState:
        async with self._condition:
            if not self._paused:
                self._base_simulated = self.now()
                self._paused = True
                self._revision += 1
            self._condition.notify_all()
            return self.state()

    async def resume(self) -> SimulationClockState:
        async with self._condition:
            if self._paused:
                self._base_monotonic = monotonic()
                self._paused = False
                self._revision += 1
            self._condition.notify_all()
            return self.state()

    async def set_rate(self, rate: int) -> SimulationClockState:
        if rate not in {1, 10, 100}:
            raise ValueError("rate must be one of 1, 10, 100")
        async with self._condition:
            current = self.now()
            self._base_simulated = current
            self._base_monotonic = monotonic()
            self._rate = rate
            self._revision += 1
            self._condition.notify_all()
            return self.state()

    async def step(self, seconds: float = 1) -> SimulationClockState:
        async with self._condition:
            if not self._paused:
                raise RuntimeError("clock must be paused before stepping")
            self._base_simulated += timedelta(seconds=seconds)
            self._revision += 1
            self._condition.notify_all()
            return self.state()

    async def reset(self, epoch: datetime | None = None) -> SimulationClockState:
        async with self._condition:
            self._run_id = str(uuid4())
            self._base_simulated = (epoch or datetime.now(UTC)).astimezone(UTC)
            self._base_monotonic = monotonic()
            self._paused = True
            self._revision += 1
            self._condition.notify_all()
            return self.state()

    async def sleep(self, simulated_seconds: float) -> None:
        if simulated_seconds <= 0:
            return
        target = self.now() + timedelta(seconds=simulated_seconds)
        while self.now() < target:
            async with self._condition:
                while self._paused:
                    await self._condition.wait()
                wall_remaining = (target - self.now()).total_seconds() / self._rate
            await asyncio.sleep(max(0, min(wall_remaining, 0.1)))
