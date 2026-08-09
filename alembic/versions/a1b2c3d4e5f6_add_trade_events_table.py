"""add trade_events table

Revision ID: a1b2c3d4e5f6
Revises: 3420091b3f44
Create Date: 2026-08-09 07:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "3420091b3f44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trade_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trade_id", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trade_events_trade_id"), "trade_events", ["trade_id"], unique=False)
    op.create_index(op.f("ix_trade_events_symbol"), "trade_events", ["symbol"], unique=False)
    op.create_index(op.f("ix_trade_events_event_type"), "trade_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_trade_events_ts"), "trade_events", ["ts"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_trade_events_ts"), table_name="trade_events")
    op.drop_index(op.f("ix_trade_events_event_type"), table_name="trade_events")
    op.drop_index(op.f("ix_trade_events_symbol"), table_name="trade_events")
    op.drop_index(op.f("ix_trade_events_trade_id"), table_name="trade_events")
    op.drop_table("trade_events")
