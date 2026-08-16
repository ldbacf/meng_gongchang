"""阶段 3：DocumentTask.md5 全局唯一 → (md5, kb_id) 复合唯一。

- 现状：`ix_document_tasks_md5` 是 UNIQUE index（SQLAlchemy unique=True + index=True 产物）。
- 语义（O-3.7 秒传/查重冻结）：KB 内按 md5 查重；**跨 KB 复制新 task**（保留 parsed 引用）；
  禁止 reassign kb_id 归属漂移。全局唯一会阻止跨 KB 复制（A-3.5 硬阻塞）。
- Postgres 对 kb_id 为 NULL 的行互不冲突（多个 NULL 允许），存量无归属文档不受影响。
Revision ID: 0004_md5_kb_unique
Revises: 0003_kb_kind_status_check
"""
from alembic import op

revision = "0004_md5_kb_unique"
down_revision = "0003_kb_kind_status_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_document_tasks_md5", table_name="document_tasks")
    op.create_index(
        "uq_document_tasks_md5_kb_id", "document_tasks",
        ["md5", "kb_id"], unique=True,
    )
    # models.py 的 index=True 保留非 unique 单列索引（查询加速）
    op.create_index("ix_document_tasks_md5", "document_tasks", ["md5"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_document_tasks_md5", table_name="document_tasks")
    op.drop_index("uq_document_tasks_md5_kb_id", "document_tasks")
    op.create_index(
        "ix_document_tasks_md5", "document_tasks", ["md5"], unique=True,
    )
