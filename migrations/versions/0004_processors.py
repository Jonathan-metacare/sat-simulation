"""processor bundles and execution history

Revision ID: 0004_processors
Revises: 0003_protocol_observation
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_processors"
down_revision = "0003_protocol_observation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "simulation_processor_versions",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("definition_id", sa.String(80), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("version_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_processor_definition", "simulation_processor_versions", ["definition_id"])
    op.create_index("ix_processor_stage", "simulation_processor_versions", ["stage"])
    op.create_index("ix_processor_sha256", "simulation_processor_versions", ["sha256"])
    op.create_table(
        "simulation_processor_executions",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("mission_id", sa.String(80), nullable=False),
        sa.Column("processor_id", sa.String(80), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("execution_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_execution_mission", "simulation_processor_executions", ["mission_id"])
    op.create_index("ix_execution_processor", "simulation_processor_executions", ["processor_id"])
    op.create_index("ix_execution_stage", "simulation_processor_executions", ["stage"])
    op.create_index("ix_execution_status", "simulation_processor_executions", ["status"])


def downgrade() -> None:
    op.drop_table("simulation_processor_executions")
    op.drop_table("simulation_processor_versions")
