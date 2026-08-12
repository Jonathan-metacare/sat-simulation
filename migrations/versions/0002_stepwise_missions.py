"""Persist the six-step mission orchestrator state.

Revision ID: 0002_stepwise_missions
Revises: 0001_initial
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_stepwise_missions"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("simulation_missions")}
    if "phase" not in columns:
        with op.batch_alter_table("simulation_missions") as batch:
            batch.add_column(
                sa.Column("phase", sa.String(40), nullable=False, server_default="initialized")
            )
            batch.add_column(
                sa.Column(
                    "execution_state", sa.String(40), nullable=False, server_default="waiting"
                )
            )
            batch.add_column(sa.Column("active_substage", sa.String(80), nullable=True))
            batch.add_column(
                sa.Column("ai_mode", sa.String(20), nullable=False, server_default="yolo")
            )
            batch.add_column(sa.Column("planned_windows_json", sa.Text(), nullable=True))
            batch.add_column(sa.Column("block_reason", sa.Text(), nullable=True))
            batch.add_column(
                sa.Column("legacy_terminal", sa.Boolean(), nullable=False, server_default=sa.true())
            )
            batch.create_index("ix_simulation_missions_phase", ["phase"])
            batch.create_index("ix_simulation_missions_execution_state", ["execution_state"])
            batch.create_index("ix_simulation_missions_legacy_terminal", ["legacy_terminal"])
        op.execute(
            sa.text(
                "UPDATE simulation_missions SET "
                "phase = CASE WHEN status = 'completed' "
                "THEN 'completed' ELSE 'initialized' END, "
                "execution_state = CASE WHEN status = 'completed' "
                "THEN 'completed' ELSE 'retryable_error' END, "
                "legacy_terminal = true"
            )
        )

    if "simulation_mission_step_attempts" in inspector.get_table_names():
        return
    op.create_table(
        "simulation_mission_step_attempts",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("mission_id", sa.String(80), nullable=False),
        sa.Column("from_phase", sa.String(40), nullable=False),
        sa.Column("target_phase", sa.String(40), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_simulation_mission_step_attempts_mission_id",
        "simulation_mission_step_attempts",
        ["mission_id"],
    )
    op.create_index(
        "ix_simulation_mission_step_attempts_idempotency_key",
        "simulation_mission_step_attempts",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_simulation_mission_step_attempts_state",
        "simulation_mission_step_attempts",
        ["state"],
    )


def downgrade() -> None:
    op.drop_table("simulation_mission_step_attempts")
    with op.batch_alter_table("simulation_missions") as batch:
        batch.drop_index("ix_simulation_missions_legacy_terminal")
        batch.drop_index("ix_simulation_missions_execution_state")
        batch.drop_index("ix_simulation_missions_phase")
        batch.drop_column("legacy_terminal")
        batch.drop_column("block_reason")
        batch.drop_column("planned_windows_json")
        batch.drop_column("ai_mode")
        batch.drop_column("active_substage")
        batch.drop_column("execution_state")
        batch.drop_column("phase")
