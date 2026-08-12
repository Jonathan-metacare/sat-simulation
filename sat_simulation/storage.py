from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, delete, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from sat_simulation.common.models import (
    AIMode,
    ExecutionState,
    FaultRule,
    MissionCommand,
    MissionPhase,
    MissionStatus,
    MissionStepAttempt,
    ProductManifest,
    ScenarioConfig,
    SimulationClockState,
    TelemetryEvent,
    TransferRecord,
)


def now_utc() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ScenarioRow(Base):
    __tablename__ = "simulation_scenarios"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(160))
    config_json: Mapped[str] = mapped_column(Text)
    clock_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class MissionRow(Base):
    __tablename__ = "simulation_missions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(80), index=True)
    scenario_id: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40), index=True)
    command_json: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    phase: Mapped[str] = mapped_column(String(40), default=MissionPhase.INITIALIZED, index=True)
    execution_state: Mapped[str] = mapped_column(
        String(40), default=ExecutionState.WAITING, index=True
    )
    active_substage: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ai_mode: Mapped[str] = mapped_column(String(20), default=AIMode.YOLO)
    planned_windows_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    block_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    legacy_terminal: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class MissionStepAttemptRow(Base):
    __tablename__ = "simulation_mission_step_attempts"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(80), index=True)
    from_phase: Mapped[str] = mapped_column(String(40))
    target_phase: Mapped[str] = mapped_column(String(40))
    attempt_number: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(40), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class EventRow(Base):
    __tablename__ = "simulation_events"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(80), index=True)
    mission_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40))
    event_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ProductRow(Base):
    __tablename__ = "simulation_products"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(80), index=True)
    mission_id: Mapped[str] = mapped_column(String(80), index=True)
    level: Mapped[str] = mapped_column(String(30), index=True)
    manifest_json: Mapped[str] = mapped_column(Text)
    artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class TransferRow(Base):
    __tablename__ = "simulation_transfers"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(80), index=True)
    mission_id: Mapped[str] = mapped_column(String(80), index=True)
    link: Mapped[str] = mapped_column(String(30), index=True)
    record_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class FaultRow(Base):
    __tablename__ = "simulation_faults"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(80), index=True)
    rule_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SceneRow(Base):
    __tablename__ = "simulation_scenes"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Repository:
    def __init__(self, database_url: str) -> None:
        if database_url.startswith("sqlite"):
            Path(database_url.rsplit("/", 1)[-1]).parent.mkdir(parents=True, exist_ok=True)
        self.engine: AsyncEngine = create_async_engine(database_url)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    async def recover_running_missions(self) -> int:
        """Make an interrupted macro step explicitly retryable after restart."""
        recovered = 0
        async with self.session() as session:
            missions = (
                await session.scalars(
                    select(MissionRow).where(MissionRow.execution_state == ExecutionState.RUNNING)
                )
            ).all()
            for mission in missions:
                mission.execution_state = ExecutionState.RETRYABLE_ERROR
                mission.active_substage = None
                mission.error = "Ground 编排器重启中断了本步，请重试"
                mission.updated_at = now_utc()
                recovered += 1
            attempts = (
                await session.scalars(
                    select(MissionStepAttemptRow).where(
                        MissionStepAttemptRow.state == ExecutionState.RUNNING
                    )
                )
            ).all()
            for attempt in attempts:
                attempt.state = ExecutionState.RETRYABLE_ERROR
                attempt.error = "Ground 编排器重启中断了本步，请使用新幂等键重试"
                attempt.finished_at = now_utc()
        return recovered

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            yield session
            await session.commit()

    async def create_scenario(
        self, config: ScenarioConfig, clock: SimulationClockState
    ) -> ScenarioRow:
        row = ScenarioRow(
            id=config.id,
            run_id=clock.run_id,
            name=config.name,
            config_json=config.model_dump_json(),
            clock_json=clock.model_dump_json(),
        )
        async with self.session() as session:
            session.add(row)
        return row

    async def update_scenario_clock(self, scenario_id: str, clock: SimulationClockState) -> None:
        async with self.session() as session:
            row = await session.get(ScenarioRow, scenario_id)
            if row:
                row.run_id = clock.run_id
                row.clock_json = clock.model_dump_json()
                row.updated_at = now_utc()

    async def get_scenario(
        self, scenario_id: str
    ) -> tuple[ScenarioConfig, SimulationClockState] | None:
        async with self.session() as session:
            row = await session.get(ScenarioRow, scenario_id)
            if not row:
                return None
            return (
                ScenarioConfig.model_validate_json(row.config_json),
                SimulationClockState.model_validate_json(row.clock_json),
            )

    async def list_scenarios(self) -> list[dict[str, Any]]:
        async with self.session() as session:
            rows = (
                await session.scalars(select(ScenarioRow).order_by(ScenarioRow.created_at.desc()))
            ).all()
            return [
                {
                    "config": ScenarioConfig.model_validate_json(row.config_json),
                    "clock": SimulationClockState.model_validate_json(row.clock_json),
                }
                for row in rows
            ]

    async def create_mission(self, command: MissionCommand) -> None:
        row = MissionRow(
            id=command.id,
            run_id=command.run_id,
            scenario_id=command.scenario_id,
            name=command.name,
            status=MissionStatus.PLANNED,
            command_json=command.model_dump_json(),
            phase=MissionPhase.INITIALIZED,
            execution_state=ExecutionState.WAITING,
            ai_mode=command.ai_mode,
            planned_windows_json=(
                command.planned_windows.model_dump_json() if command.planned_windows else None
            ),
            legacy_terminal=False,
        )
        async with self.session() as session:
            session.add(row)

    async def update_mission(self, mission_id: str, status: str, error: str | None = None) -> None:
        async with self.session() as session:
            row = await session.get(MissionRow, mission_id)
            if row:
                row.status = status
                row.error = error
                row.updated_at = now_utc()

    async def active_mission_for_scenario(self, scenario_id: str) -> str | None:
        async with self.session() as session:
            return await session.scalar(
                select(MissionRow.id)
                .where(
                    MissionRow.scenario_id == scenario_id,
                    MissionRow.legacy_terminal.is_(False),
                    MissionRow.execution_state.not_in(
                        [ExecutionState.COMPLETED, ExecutionState.CANCELLED]
                    ),
                )
                .limit(1)
            )

    async def cancel_mission(self, mission_id: str) -> None:
        """End a paused mission without deleting its run, events, or products."""
        async with self.session() as session:
            row = await session.get(MissionRow, mission_id, with_for_update=True)
            if not row:
                raise KeyError(mission_id)
            if row.execution_state == ExecutionState.RUNNING:
                raise RuntimeError("任务阶段正在执行，不能结束；请等待本阶段停止")
            if row.execution_state in {ExecutionState.COMPLETED, ExecutionState.CANCELLED}:
                return
            row.status = MissionStatus.CANCELLED
            row.execution_state = ExecutionState.CANCELLED
            row.active_substage = None
            row.block_reason = None
            row.error = "用户结束任务并重新初始化"
            row.updated_at = now_utc()

    async def begin_step(
        self,
        mission_id: str,
        *,
        target_phase: MissionPhase,
        idempotency_key: str,
        active_substage: str,
    ) -> tuple[MissionStepAttempt, bool]:
        async with self.session() as session:
            existing = await session.scalar(
                select(MissionStepAttemptRow).where(
                    MissionStepAttemptRow.idempotency_key == idempotency_key
                )
            )
            if existing:
                return self._attempt_model(existing), True
            row = await session.get(MissionRow, mission_id, with_for_update=True)
            if not row:
                raise KeyError(mission_id)
            if row.legacy_terminal:
                raise RuntimeError("旧版任务只读，不能继续推进")
            if row.execution_state in {ExecutionState.COMPLETED, ExecutionState.CANCELLED}:
                raise RuntimeError("任务已经结束，不能继续推进")
            if row.execution_state == ExecutionState.RUNNING:
                raise RuntimeError("任务已有正在执行的单步")
            count = len(
                (
                    await session.scalars(
                        select(MissionStepAttemptRow).where(
                            MissionStepAttemptRow.mission_id == mission_id
                        )
                    )
                ).all()
            )
            attempt = MissionStepAttempt(
                mission_id=mission_id,
                from_phase=MissionPhase(row.phase),
                target_phase=target_phase,
                attempt_number=count + 1,
                idempotency_key=idempotency_key,
            )
            session.add(
                MissionStepAttemptRow(
                    id=attempt.id,
                    mission_id=mission_id,
                    from_phase=attempt.from_phase,
                    target_phase=attempt.target_phase,
                    attempt_number=attempt.attempt_number,
                    idempotency_key=idempotency_key,
                    state=attempt.state,
                    started_at=attempt.started_at,
                )
            )
            row.execution_state = ExecutionState.RUNNING
            row.active_substage = active_substage
            row.block_reason = None
            row.error = None
            row.updated_at = now_utc()
            return attempt, False

    async def get_attempt_by_idempotency_key(
        self, idempotency_key: str
    ) -> MissionStepAttempt | None:
        async with self.session() as session:
            row = await session.scalar(
                select(MissionStepAttemptRow).where(
                    MissionStepAttemptRow.idempotency_key == idempotency_key
                )
            )
            return self._attempt_model(row) if row else None

    async def finish_step(
        self,
        mission_id: str,
        attempt_id: str,
        *,
        phase: MissionPhase,
        execution_state: ExecutionState,
        status: MissionStatus,
        error: str | None = None,
    ) -> None:
        async with self.session() as session:
            mission = await session.get(MissionRow, mission_id, with_for_update=True)
            attempt = await session.get(MissionStepAttemptRow, attempt_id)
            if not mission or not attempt:
                raise KeyError(mission_id)
            if execution_state in {ExecutionState.WAITING, ExecutionState.COMPLETED}:
                mission.phase = phase
            mission.execution_state = execution_state
            mission.status = status
            mission.active_substage = None
            mission.error = error
            mission.block_reason = error if execution_state == ExecutionState.BLOCKED else None
            mission.updated_at = now_utc()
            attempt.state = execution_state
            attempt.error = error
            attempt.finished_at = now_utc()

    @staticmethod
    def _attempt_model(row: MissionStepAttemptRow) -> MissionStepAttempt:
        return MissionStepAttempt(
            id=row.id,
            mission_id=row.mission_id,
            from_phase=row.from_phase,
            target_phase=row.target_phase,
            attempt_number=row.attempt_number,
            idempotency_key=row.idempotency_key,
            state=row.state,
            started_at=row.started_at,
            finished_at=row.finished_at,
            error=row.error,
        )

    async def get_mission(self, mission_id: str) -> dict[str, Any] | None:
        async with self.session() as session:
            row = await session.get(MissionRow, mission_id)
            if not row:
                return None
            events = (
                await session.scalars(
                    select(EventRow)
                    .where(EventRow.mission_id == mission_id)
                    .order_by(EventRow.sequence)
                )
            ).all()
            products = (
                await session.scalars(
                    select(ProductRow)
                    .where(ProductRow.mission_id == mission_id)
                    .order_by(ProductRow.created_at)
                )
            ).all()
            transfers = (
                await session.scalars(
                    select(TransferRow)
                    .where(TransferRow.mission_id == mission_id)
                    .order_by(TransferRow.created_at)
                )
            ).all()
            attempts = (
                await session.scalars(
                    select(MissionStepAttemptRow)
                    .where(MissionStepAttemptRow.mission_id == mission_id)
                    .order_by(MissionStepAttemptRow.started_at)
                )
            ).all()
            return {
                "command": MissionCommand.model_validate_json(row.command_json),
                "status": row.status,
                "error": row.error,
                "phase": row.phase,
                "execution_state": row.execution_state,
                "active_substage": row.active_substage,
                "ai_mode": row.ai_mode,
                "planned_windows": json.loads(row.planned_windows_json)
                if row.planned_windows_json
                else None,
                "block_reason": row.block_reason,
                "legacy_terminal": row.legacy_terminal,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "events": [TelemetryEvent.model_validate_json(item.event_json) for item in events],
                "products": [
                    ProductManifest.model_validate_json(item.manifest_json) for item in products
                ],
                "transfers": [
                    TransferRecord.model_validate_json(item.record_json) for item in transfers
                ],
                "step_attempts": [self._attempt_model(item) for item in attempts],
            }

    async def list_missions(self) -> list[dict[str, Any]]:
        async with self.session() as session:
            rows = (
                await session.scalars(select(MissionRow).order_by(MissionRow.created_at.desc()))
            ).all()
            return [
                {
                    "command": MissionCommand.model_validate_json(row.command_json),
                    "status": row.status,
                    "error": row.error,
                    "phase": row.phase,
                    "execution_state": row.execution_state,
                    "active_substage": row.active_substage,
                    "ai_mode": row.ai_mode,
                    "planned_windows": json.loads(row.planned_windows_json)
                    if row.planned_windows_json
                    else None,
                    "block_reason": row.block_reason,
                    "legacy_terminal": row.legacy_terminal,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
                for row in rows
            ]

    async def append_event(self, event: TelemetryEvent) -> None:
        async with self.session() as session:
            if event.sequence <= 0:
                last = await session.scalar(
                    select(EventRow.sequence)
                    .where(EventRow.run_id == event.run_id)
                    .order_by(EventRow.sequence.desc())
                    .limit(1)
                )
                event.sequence = (last or 0) + 1
            session.add(
                EventRow(
                    id=event.id,
                    run_id=event.run_id,
                    mission_id=event.mission_id,
                    sequence=event.sequence,
                    event_type=event.event_type,
                    status=event.status,
                    event_json=event.model_dump_json(),
                )
            )

    async def events_after(self, run_id: str, sequence: int) -> list[TelemetryEvent]:
        async with self.session() as session:
            rows = (
                await session.scalars(
                    select(EventRow)
                    .where(EventRow.run_id == run_id, EventRow.sequence > sequence)
                    .order_by(EventRow.sequence)
                )
            ).all()
            return [TelemetryEvent.model_validate_json(row.event_json) for row in rows]

    async def add_product(self, manifest: ProductManifest, artifact_path: str) -> None:
        manifest.artifact_path = artifact_path
        async with self.session() as session:
            row = await session.get(ProductRow, manifest.id)
            if row:
                row.manifest_json = manifest.model_dump_json()
                row.artifact_path = artifact_path
            else:
                session.add(
                    ProductRow(
                        id=manifest.id,
                        run_id=manifest.run_id,
                        mission_id=manifest.mission_id,
                        level=manifest.level,
                        manifest_json=manifest.model_dump_json(),
                        artifact_path=artifact_path,
                    )
                )

    async def get_product(self, product_id: str) -> ProductManifest | None:
        async with self.session() as session:
            row = await session.get(ProductRow, product_id)
            return ProductManifest.model_validate_json(row.manifest_json) if row else None

    async def add_transfer(self, record: TransferRecord) -> None:
        async with self.session() as session:
            session.add(
                TransferRow(
                    id=record.id,
                    run_id=record.run_id,
                    mission_id=record.mission_id,
                    link=record.link,
                    record_json=record.model_dump_json(),
                )
            )

    async def list_transfers(self, run_id: str | None = None) -> list[TransferRecord]:
        async with self.session() as session:
            query = select(TransferRow).order_by(TransferRow.created_at.desc())
            if run_id:
                query = query.where(TransferRow.run_id == run_id)
            rows = (await session.scalars(query)).all()
            return [TransferRecord.model_validate_json(row.record_json) for row in rows]

    async def add_fault(self, scenario_id: str, rule: FaultRule) -> None:
        async with self.session() as session:
            session.add(
                FaultRow(id=rule.id, scenario_id=scenario_id, rule_json=rule.model_dump_json())
            )

    async def delete_fault(self, scenario_id: str, fault_id: str) -> bool:
        async with self.session() as session:
            result = await session.execute(
                delete(FaultRow).where(FaultRow.scenario_id == scenario_id, FaultRow.id == fault_id)
            )
            return bool(result.rowcount)

    async def list_faults(self, scenario_id: str) -> list[FaultRule]:
        async with self.session() as session:
            rows = (
                await session.scalars(select(FaultRow).where(FaultRow.scenario_id == scenario_id))
            ).all()
            return [FaultRule.model_validate_json(row.rule_json) for row in rows]

    async def add_scene(
        self,
        *,
        scene_id: str,
        name: str,
        path: str,
        sha256: str,
        metadata: dict[str, Any],
    ) -> None:
        async with self.session() as session:
            row = await session.get(SceneRow, scene_id)
            if row:
                row.name = name
                row.path = path
                row.sha256 = sha256
                row.metadata_json = json.dumps(metadata)
            else:
                session.add(
                    SceneRow(
                        id=scene_id,
                        name=name,
                        path=path,
                        sha256=sha256,
                        metadata_json=json.dumps(metadata),
                    )
                )
