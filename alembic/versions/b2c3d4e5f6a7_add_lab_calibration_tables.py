"""add score_snapshots calibration presets backtest_jobs incidents

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-09 07:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "score_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("breakdown", sa.JSON(), nullable=False),
        sa.Column("phase", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_score_snapshots_symbol", "score_snapshots", ["symbol"])
    op.create_index("ix_score_snapshots_ts", "score_snapshots", ["ts"])
    op.create_index("ix_score_snapshots_phase", "score_snapshots", ["phase"])

    op.create_table(
        "calibration_stats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("strategy_version", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("regime", sa.String(), nullable=False),
        sa.Column("score_bucket", sa.String(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False),
        sa.Column("sum_r", sa.Float(), nullable=False),
        sa.Column("ci_low", sa.Float(), nullable=True),
        sa.Column("ci_high", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "strategy_version", "side", "regime", "score_bucket",
            name="uq_calibration_key",
        ),
    )
    op.create_index("ix_calibration_stats_strategy_version", "calibration_stats", ["strategy_version"])
    op.create_index("ix_calibration_stats_updated_at", "calibration_stats", ["updated_at"])

    op.create_table(
        "presets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("preset_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("class_rule", sa.JSON(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("overlay", sa.Boolean(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=False),
        sa.Column("activated_paper", sa.Boolean(), nullable=False),
        sa.Column("activated_live", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_presets_preset_id", "presets", ["preset_id"])
    op.create_index("ix_presets_name", "presets", ["name"])
    op.create_index("ix_presets_created_at", "presets", ["created_at"])

    op.create_table(
        "backtest_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("preset_id", sa.String(), nullable=False),
        sa.Column("preset_version", sa.Integer(), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("date_from", sa.DateTime(), nullable=False),
        sa.Column("date_to", sa.DateTime(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("config_hash", sa.String(), nullable=False),
        sa.Column("data_checksum", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_backtest_jobs_job_id", "backtest_jobs", ["job_id"])
    op.create_index("ix_backtest_jobs_preset_id", "backtest_jobs", ["preset_id"])
    op.create_index("ix_backtest_jobs_status", "backtest_jobs", ["status"])
    op.create_index("ix_backtest_jobs_created_at", "backtest_jobs", ["created_at"])

    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_incidents_ts", "incidents", ["ts"])
    op.create_index("ix_incidents_severity", "incidents", ["severity"])


def downgrade() -> None:
    op.drop_table("incidents")
    op.drop_table("backtest_jobs")
    op.drop_table("presets")
    op.drop_table("calibration_stats")
    op.drop_table("score_snapshots")
