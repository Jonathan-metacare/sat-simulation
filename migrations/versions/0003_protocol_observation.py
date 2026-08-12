"""Persist protocol transaction and frame summaries.

Revision ID: 0003_protocol_observation
Revises: 0002_stepwise_missions
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_protocol_observation"
down_revision = "0002_stepwise_missions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    transfer_columns = {
        item["name"] for item in inspector.get_columns("simulation_transfers")
    }
    if "protocol_transaction_id" not in transfer_columns:
        with op.batch_alter_table("simulation_transfers") as batch:
            batch.add_column(
                sa.Column("protocol_transaction_id", sa.String(80), nullable=True)
            )
            batch.create_index(
                "ix_simulation_transfers_protocol_transaction_id",
                ["protocol_transaction_id"],
            )
    if "simulation_protocol_transactions" not in tables:
        op.create_table(
            "simulation_protocol_transactions",
            sa.Column("id", sa.String(80), primary_key=True),
            sa.Column("run_id", sa.String(80), nullable=False),
            sa.Column("mission_id", sa.String(80), nullable=False),
            sa.Column("link", sa.String(30), nullable=False),
            sa.Column("message_type", sa.String(50), nullable=False),
            sa.Column("transaction_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for column in ("run_id", "mission_id", "link", "message_type"):
            op.create_index(
                f"ix_simulation_protocol_transactions_{column}",
                "simulation_protocol_transactions",
                [column],
            )
    if "simulation_protocol_frames" not in tables:
        op.create_table(
            "simulation_protocol_frames",
            sa.Column("id", sa.String(80), primary_key=True),
            sa.Column("transaction_id", sa.String(80), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("frame_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_simulation_protocol_frames_transaction_id",
            "simulation_protocol_frames",
            ["transaction_id"],
        )


def downgrade() -> None:
    op.drop_table("simulation_protocol_frames")
    op.drop_table("simulation_protocol_transactions")
    with op.batch_alter_table("simulation_transfers") as batch:
        batch.drop_index("ix_simulation_transfers_protocol_transaction_id")
        batch.drop_column("protocol_transaction_id")
