"""FastAPI 装配 — 应用组装 + lifespan + 少量运维端点。

文档/PDF 相关端点已拆到 `app/interface/routers/documents.py`；登录、会话、管理、
WS、metrics 各在自己的 router 里。本文件只保留：lifespan 装配、CORS、健康检查、
Token 额度查看，以及路由注册。

兼容说明：`_handle_one_file` / `_copy_across_kb` / `_pdf_range_bounds` /
`_find_pdf_object_name` 仍从本模块 re-export，因为既有测试与 `admin.py` 仍按
`from app.main import ...` 引用；新代码请直接从 `app.interface.routers.documents` 导入。
"""
import hashlib
import re
import traceback
import uuid
from contextlib import asynccontextmanager

import fitz  # PyMuPDF
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app.infrastructure.container import get_container
from app.infrastructure.db.models import DocumentTask, TaskStatus
from app.infrastructure.db.session import async_session
from app.infrastructure.key_manager import get_key_manager
from app.infrastructure.settings import get_settings
from app.interface.middleware import RequestLogMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 观测基建（O-5.2）：结构化 JSON 日志 + trace provider
    from app.infrastructure.observability.logger import setup_logging
    from app.infrastructure.observability.tracing import init_tracing

    setup_logging()
    init_tracing()

    # schema 演进由 Alembic 管理（backend/alembic/）：新建库 `alembic upgrade head`，
    # 已有库先 `alembic stamp 0002_checkpoint` 标记基线。此处仅做 DI 装配与启动。
    container = get_container()
    await container.start()  # DB 连通性校验 + MinIO 建桶 + bge-m3 预热（幂等）

    # 创建默认管理员
    # 凭据从配置读取（BOOTSTRAP_ADMIN_PASSWORD），**不再硬编码** admin123：
    # 源码里的公开默认密码等于把后台送人。留空则不建默认账号，由运维显式配置。
    from sqlalchemy import func as sql_func  # noqa: F811

    async with async_session() as session:
        from app.infrastructure.db.models import KnowledgeBase, User
        from app.interface.security import hash_password

        result = await session.execute(
            select(sql_func.count()).select_from(User)
        )
        count = result.scalar()
        if count == 0:
            _bs = get_settings()
            if _bs.bootstrap_admin_password:
                admin = User(
                    username=_bs.bootstrap_admin_username,
                    password_hash=hash_password(_bs.bootstrap_admin_password),
                    role="admin",
                    enabled=True,
                )
                session.add(admin)
                await session.commit()
                print(
                    f"[API] 已创建默认管理员: {_bs.bootstrap_admin_username}"
                    "（密码来自 BOOTSTRAP_ADMIN_PASSWORD，请登录后立即修改）"
                )
            else:
                print(
                    "[API] 警告: 用户表为空且未配置 BOOTSTRAP_ADMIN_PASSWORD，"
                    "未创建默认管理员。请设置该环境变量后重启。"
                )

    # 创建默认知识库 + 回填现有文档
    async with async_session() as session:
        from app.infrastructure.db.models import KnowledgeBase, DocumentTask

        kb_result = await session.execute(
            select(KnowledgeBase).where(KnowledgeBase.slug == "zhong_guo_quan_ke")
        )
        kb = kb_result.scalar_one_or_none()
        if not kb:
            kb = KnowledgeBase(
                name="中国全科医学",
                description="《中国全科医学》期刊文献库，收录1248篇论文，覆盖高血压、糖尿病、心血管、慢性病管理等全科医学领域",
                slug="zhong_guo_quan_ke",  # seed 标识（slug 仅此处使用，业务分支看 kb_kind）
                kb_kind="medical_default",
                es_index="chunks",
                milvus_collection="chunks",
            )
            session.add(kb)
            await session.commit()
            await session.refresh(kb)
            print(f"[API] 已创建默认知识库: {kb.name}")

        # 回填现有文档
        result = await session.execute(
            select(DocumentTask).where(DocumentTask.kb_id.is_(None))
        )
        orphan_docs = result.scalars().all()
        if orphan_docs:
            for doc in orphan_docs:
                doc.kb_id = kb.id
            await session.commit()
            print(f"[API] 已回填 {len(orphan_docs)} 份文档到默认知识库")

    # 预热 KeyManager（额度账本在 Redis）
    print("[API] KeyManager 启动:")
    print(await get_key_manager().usage_report())

    # worker 已剥离为独立进程（app.application.worker / pipeline-worker），
    # API 进程不再内嵌消费队列——入库管线由独立 worker 驱动 IngestionGraph。
    yield

    await container.close()  # 统一 dispose（engine/redis/milvus/bge-m3/checkpointer）


app = FastAPI(
    title="MedRAG API",
    version="2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 访问日志：每个请求一行 JSON（含 method/path/status/耗时）。
# uvicorn 自带的访问日志只有状态码、格式也不同，故在入口处替换。
app.add_middleware(RequestLogMiddleware)


# ── 注册路由 ──────────────────────────────────────────────

from app.interface.security import require_admin  # noqa: E402
from app.interface.routers.auth import router as auth_router  # noqa: E402
from app.interface.routers.chat import router as chat_router  # noqa: E402
from app.interface.routers.admin import router as admin_router  # noqa: E402
from app.interface.routers.documents import router as documents_router  # noqa: E402
from app.interface.routers.ws import router as ws_router  # noqa: E402
from app.interface.routers.metrics import router as metrics_router  # noqa: E402

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(admin_router)
app.include_router(documents_router)
app.include_router(ws_router)
app.include_router(metrics_router)


# ── 兼容 re-export（既有测试 / admin.py 仍按 app.main 引用）─────

from app.interface.routers.documents import (  # noqa: E402,F401
    _copy_across_kb,
    _find_pdf_object_name,
    _handle_one_file,
    _md5,
    _pdf_pages,
    _pdf_range_bounds,
    _submit_batches,
)


# ── 运维端点 ──────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/v1/tokens/usage")
async def token_usage(_admin=Depends(require_admin)):
    """查看各 Token 当日额度用量（admin only）"""
    mgr = get_key_manager()
    exhausted = await mgr.is_exhausted()
    return {
        "tokens": await mgr.usage_report(),
        "exhausted": exhausted,
        "all_exhausted": exhausted,
    }
