"""TaskStatus 显式状态机 CHECK + knowledge_bases.kb_kind 策略列。

- `document_tasks.status`：先 UPDATE 归一化存量脏值（→ 'failed'），再建 CHECK 约束
  （用 CheckConstraint 而非原生 PG ENUM，避免 CREATE TYPE / USING 转换风险）。
- `knowledge_bases.kb_kind`：ADD COLUMN（server_default='medical_default'）→
  按 slug 回填（非默认库置 'generic'，默认期刊库保持 medical_default）→ 建 CHECK。
  回填与建约束同文件同事务，顺序不可颠倒（先建约束会在中间态被拦）。
- slug `zhong_guo_quan_ke` 在此作为 seed 标识出现（T-2.9 白名单：main.py seed + 本迁移）。
Revision ID: 0003_kb_kind_status_check
Revises: 0002_checkpoint
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_kb_kind_status_check"
down_revision = "0002_checkpoint"
branch_labels = None
depends_on = None

_VALID_STATUS = "('pending','processing','parsed','indexing','ready','failed')"
_VALID_KB_KIND = "('medical_default','generic')"


def upgrade() -> None:
    # 1) status 显式状态机：存量脏值兜底归一化 → CHECK
    op.execute(
        f"UPDATE document_tasks SET status = 'failed' WHERE status NOT IN {_VALID_STATUS}"
    )
    op.create_check_constraint(
        "ck_document_tasks_status", "document_tasks",
        f"status IN {_VALID_STATUS}",
    )

    # 2) kb_kind 策略列：ADD → 按 slug 回填 → CHECK
    op.add_column(
        "knowledge_bases",
        sa.Column("kb_kind", sa.String(32), nullable=False, server_default="medical_default"),
    )
    op.execute(
        "UPDATE knowledge_bases SET kb_kind = 'generic' "
        "WHERE slug IS DISTINCT FROM 'zhong_guo_quan_ke'"
    )
    op.create_check_constraint(
        "ck_knowledge_bases_kb_kind", "knowledge_bases",
        f"kb_kind IN {_VALID_KB_KIND}",
    )


def downgrade() -> None:
    op.drop_constraint("ck_knowledge_bases_kb_kind", "knowledge_bases", type_="check")
    op.drop_column("knowledge_bases", "kb_kind")
    op.drop_constraint("ck_document_tasks_status", "document_tasks", type_="check")
