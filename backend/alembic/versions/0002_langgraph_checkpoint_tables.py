"""langgraph-checkpoint-postgres 所需的 checkpoint 表。

DDL 与 langgraph-checkpoint-postgres 3.1.2 的 AsyncPostgresSaver 期望一致。
由 Alembic 版本化管理，**不依赖** saver 的 `.setup()` 运行时建表。 预置（休眠表）， 图落地后启用。
Revision ID: 0002_checkpoint
Revises: 0001_baseline
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_checkpoint"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "checkpoint_migrations",
        sa.Column("v", sa.Integer(), primary_key=True),
    )

    op.create_table(
        "checkpoints",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("parent_checkpoint_id", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("checkpoint", postgresql.JSONB(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "checkpoint_id"),
    )

    op.create_table(
        "checkpoint_blobs",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), nullable=False, server_default=""),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("blob", sa.LargeBinary(), nullable=True),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "channel", "version"),
    )

    op.create_table(
        "checkpoint_writes",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("blob", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"),
    )


def downgrade() -> None:
    op.drop_table("checkpoint_writes")
    op.drop_table("checkpoint_blobs")
    op.drop_table("checkpoints")
    op.drop_table("checkpoint_migrations")
