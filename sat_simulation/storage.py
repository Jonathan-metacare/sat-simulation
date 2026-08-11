from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, delete, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from sat_simulation.common.models import (
    FaultRule,
    MissionCommand,
    MissionStatus,
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


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
            return {
                "command": MissionCommand.model_validate_json(row.command_json),
                "status": row.status,
                "error": row.error,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "events": [TelemetryEvent.model_validate_json(item.event_json) for item in events],
                "products": [
                    ProductManifest.model_validate_json(item.manifest_json) for item in products
                ],
                "transfers": [
                    TransferRecord.model_validate_json(item.record_json) for item in transfers
                ],
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
