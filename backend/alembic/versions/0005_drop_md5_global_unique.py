"""删除 0001 遗留的 document_tasks_md5_key 唯一约束。

背景（真机复现的新库缺陷）：
- 0001 用 `sa.Column("md5", ..., unique=True)` 建表，Postgres 落成 **UNIQUE 约束**
  `document_tasks_md5_key`（不是普通索引）。
- 0004 只 `op.drop_index("ix_document_tasks_md5")` 并建 `(md5, kb_id)` 复合唯一，
  **没有删这个约束**。
- 于是全新库按 0001→0004 迁移后，单列唯一仍在，`md5` 依然全局唯一：
  跨 KB 复制同一篇文献（O-3.7 秒传/查重的核心场景）必然
  `duplicate key value violates unique constraint "document_tasks_md5_key"`。

开发库因历史原因（当年用 create_all 建表、约束名不同）没有该约束，
所以长期未暴露；只有**从零迁移**的新部署会中招 —— 测试隔离库正是这样发现的。

`IF EXISTS` 是必需的：已存在的旧库本来就没有该约束，升级不能因此失败。

Revision ID: 0005_drop_md5_global_unique
Revises: 0004_md5_kb_unique
"""
from alembic import op

revision = "0005_drop_md5_global_unique"
down_revision = "0004_md5_kb_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 的 unique=True 产物；只在"从零迁移"的库上存在
    op.execute("ALTER TABLE document_tasks DROP CONSTRAINT IF EXISTS document_tasks_md5_key")


def downgrade() -> None:
    # 恢复全局唯一需要保证现存数据无重复 md5；若有跨 KB 复制副本，这里会失败。
    # 这是有意的：降级到"md5 全局唯一"语义本身与该数据的业务含义冲突。
    op.execute(
        "ALTER TABLE document_tasks ADD CONSTRAINT document_tasks_md5_key UNIQUE (md5)"
    )
