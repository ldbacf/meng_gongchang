"""异步 SQLAlchemy 引擎 & session — 转发到 AppContainer（阶段 1）。

`engine` / `async_session` 变为**惰性代理**：模块名/导出名不变（30+ 调用点零改动），
首次访问才经容器创建真 engine/sessionmaker。容器 `close()` 统一 dispose。
测试注入 fake engine 即可替换真实 DB。
"""
from __future__ import annotations


def _container_engine():
    from app.interface.deps import get_container
    return get_container().get_db_engine()


def _container_sessionmaker():
    from app.interface.deps import get_container
    return get_container().get_db_sessionmaker()


class _EngineProxy:
    """`async with engine.begin()` / `engine.<attr>` → 容器 engine。"""

    def begin(self):
        return _container_engine().begin()

    def __getattr__(self, name):
        return getattr(_container_engine(), name)


class _SessionmakerProxy:
    """`async with async_session() as s` → 容器 sessionmaker 实例。"""

    def __call__(self, **kwargs):
        return _container_sessionmaker()(**kwargs)

    def __getattr__(self, name):
        return getattr(_container_sessionmaker(), name)


engine = _EngineProxy()
async_session = _SessionmakerProxy()


async def get_db():
    """FastAPI 依赖：请求级会话。"""
    async with async_session() as session:
        yield session
