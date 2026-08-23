"""AppContainer — 基础设施统一 DI 容器（阶段 1）。

- lazy getter：客户端首次访问才创建（可注入 fake，测试替换真实客户端）。
- `start()` / `close()` 幂等；close 统一 dispose（engine / redis pool / milvus / bge-m3 /
  LLM / event_bus），close 后置空可重建。
- 生产用 `get_container()`（deps.py）单例；测试用 `AppContainer(fakes={...})` 或
  `set_container(...)` 注入 fake。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.settings import Settings, get_settings


class AppContainer:
    def __init__(self, settings: Settings | None = None, fakes: dict | None = None):
        self._settings = settings
        self._fakes = fakes or {}
        # lazy 缓存
        self._engine = None
        self._sessionmaker = None
        self._redis = None
        self._es = None
        self._milvus = None
        self._minio = None
        self._mineru = None
        self._embedder = None
        self._llm = None
        self._vault = None
        self._quota_store = None
        self._queue = None
        self._event_bus = None
        self._ws = None
        self._key_manager = None
        self._checkpointer = None
        self._ingest_graph = None
        self._index_subgraph = None
        self._submission_service = None
        self._delete_service = None
        self._retry_service = None
        self._started = False
        self._closed = False

    def _fake(self, key):
        return self._fakes.get(key)

    # ── 配置 ──────────────────────────────────────────────

    def get_settings(self) -> Settings:
        return self._settings or get_settings()

    # ── DB ────────────────────────────────────────────────

    def get_db_engine(self):
        f = self._fake("engine")
        if f is not None:
            return f
        if self._engine is None:
            self._engine = create_async_engine(
                self.get_settings().resolved_database_url, echo=False, pool_size=10
            )
        return self._engine

    def get_db_sessionmaker(self):
        f = self._fake("sessionmaker")
        if f is not None:
            return f
        if self._sessionmaker is None:
            self._sessionmaker = async_sessionmaker(
                self.get_db_engine(), class_=AsyncSession, expire_on_commit=False
            )
        return self._sessionmaker

    # ── Redis ─────────────────────────────────────────────

    def get_redis(self):
        f = self._fake("redis")
        if f is not None:
            return f
        if self._redis is None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                self.get_settings().resolved_redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=10,
            )
        return self._redis

    def get_quota_store(self):
        f = self._fake("quota_store")
        if f is not None:
            return f
        if self._quota_store is None:
            from app.infrastructure.redis.quota_store_redis import QuotaStoreRedis

            self._quota_store = QuotaStoreRedis(self.get_redis())
        return self._quota_store

    def get_queue(self):
        f = self._fake("queue")
        if f is not None:
            return f
        if self._queue is None:
            from app.infrastructure.redis.queue_adapter import QueueAdapter

            s = self.get_settings()
            self._queue = QueueAdapter(
                self.get_redis(),
                stream=s.redis_queue,
                group=s.redis_queue_group,
                dlq=s.redis_queue_dlq,
                visibility_timeout=s.queue_visibility_timeout,
                max_delivery=s.queue_max_delivery,
            )
        return self._queue

    def get_event_bus(self):
        f = self._fake("event_bus")
        if f is not None:
            return f
        if self._event_bus is None:
            from app.infrastructure.redis.event_bus_redis import EventBusRedis

            self._event_bus = EventBusRedis(self.get_settings().resolved_redis_url)
        return self._event_bus

    # ── 客户端适配器 ───────────────────────────────────────

    def get_es(self):
        f = self._fake("es")
        if f is not None:
            return f
        if self._es is None:
            from app.infrastructure.adapters.elasticsearch_ import ElasticsearchAdapter

            self._es = ElasticsearchAdapter(self.get_settings())
        return self._es

    def get_milvus(self):
        f = self._fake("milvus")
        if f is not None:
            return f
        if self._milvus is None:
            from app.infrastructure.adapters.milvus import MilvusAdapter

            self._milvus = MilvusAdapter(self.get_settings())
        return self._milvus

    def get_minio(self):
        f = self._fake("minio")
        if f is not None:
            return f
        if self._minio is None:
            from app.infrastructure.adapters.minio import MinioAdapter

            self._minio = MinioAdapter(self.get_settings())
        return self._minio

    def get_mineru(self):
        f = self._fake("mineru")
        if f is not None:
            return f
        if self._mineru is None:
            from app.infrastructure.adapters.mineru import MineruClient

            self._mineru = MineruClient(self.get_settings())
        return self._mineru

    def get_embedder(self):
        f = self._fake("embedder")
        if f is not None:
            return f
        if self._embedder is None:
            s = self.get_settings()
            if s.embedding_mode == "remote":
                from app.infrastructure.adapters.embedding_http import HttpEmbeddingPort

                self._embedder = HttpEmbeddingPort(s.embedding_service_url)
            else:
                from app.infrastructure.adapters.embedding import EmbeddingFactory

                self._embedder = EmbeddingFactory()
        return self._embedder

    def get_llm(self):
        f = self._fake("llm")
        if f is not None:
            return f
        if self._llm is None:
            from app.infrastructure.adapters.llm_chat import LlmChatFactory

            self._llm = LlmChatFactory(self.get_settings())
        return self._llm

    def get_reranker(self, top_n: int = 20):
        f = self._fake("reranker")
        if f is not None:
            return f
        from app.infrastructure.adapters.rerank import SiliconFlowReranker

        return SiliconFlowReranker(top_n=top_n, settings=self.get_settings())

    # ── 业务门面 ───────────────────────────────────────────

    def get_token_vault(self):
        f = self._fake("vault")
        if f is not None:
            return f
        if self._vault is None:
            from app.infrastructure.vault import TokenVault

            self._vault = TokenVault(self.get_settings().mineru_token_list)
        return self._vault

    def get_key_manager(self):
        f = self._fake("key_manager")
        if f is not None:
            return f
        if self._key_manager is None:
            from src.key_manager import KeyManager

            s = self.get_settings()
            self._key_manager = KeyManager(
                self.get_token_vault(), s.mineru_max_pages_per_key, self.get_quota_store()
            )
        return self._key_manager

    def get_ws_registry(self):
        f = self._fake("ws_registry")
        if f is not None:
            return f
        if self._ws is None:
            from src.ws_manager import WSRegistry

            self._ws = WSRegistry(self.get_event_bus())
        return self._ws

    # ── 阶段 3：checkpoint 与入库图 ─────────────────────────

    def get_checkpointer(self):
        """AsyncPostgresSaver（start() 时创建；测试注入 fake/InMemorySaver 不经 start）。"""
        f = self._fake("checkpointer")
        if f is not None:
            return f
        if self._checkpointer is None:
            raise RuntimeError("checkpointer 未创建：请先 await container.start()")
        return self._checkpointer

    def get_ingest_graph(self):
        """批级入库图（compile 挂 checkpointer，C3）。"""
        f = self._fake("ingest_graph")
        if f is not None:
            return f
        if self._ingest_graph is None:
            from app.application.graphs.ingest_graph import build_ingest_graph

            self._ingest_graph = build_ingest_graph(self.get_checkpointer())
        return self._ingest_graph

    def get_index_subgraph(self):
        """index_document 子图（per-doc，同 checkpointer）。"""
        f = self._fake("index_subgraph")
        if f is not None:
            return f
        if self._index_subgraph is None:
            from app.application.graphs.subgraphs.index_document import (
                build_index_document_graph,
            )

            self._index_subgraph = build_index_document_graph(self.get_checkpointer())
        return self._index_subgraph

    # ── 阶段 3：应用服务 ─────────────────────────────────────

    def get_submission_service(self):
        f = self._fake("submission_service")
        if f is not None:
            return f
        if self._submission_service is None:
            from app.application.services.document_submission import SubmissionService

            self._submission_service = SubmissionService(self)
        return self._submission_service

    def get_delete_service(self):
        f = self._fake("delete_service")
        if f is not None:
            return f
        if self._delete_service is None:
            from app.application.services.document_deletion import DeleteDocumentService

            self._delete_service = DeleteDocumentService(self)
        return self._delete_service

    def get_retry_service(self):
        f = self._fake("retry_service")
        if f is not None:
            return f
        if self._retry_service is None:
            from app.application.services.retry_service import RetryService

            self._retry_service = RetryService(self)
        return self._retry_service

    # ── 生命周期 ───────────────────────────────────────────

    async def start(self) -> None:
        """幂等启动：DB 连通性校验 + MinIO 建桶 + bge-m3 预热。"""
        if self._started:
            return
        self._closed = False

        from sqlalchemy import text

        engine = self.get_db_engine()
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        await self.get_minio().init_buckets()
        # 预热 bge-m3：local 模式启动加载一次常驻；
        # remote 模式只做 /health 探测（模型已在 embedding-service 端常驻，本进程不再加载）。
        if self.get_settings().embedding_mode == "remote":
            if self.get_embedder().check_health():
                print("[API] embedding-service 就绪")
            else:
                print("[API] 警告: embedding-service 不可达（检索/索引将失败，请先起 embedding-server）")
        else:
            self.get_embedder().get_hf_embeddings()
            print("[API] bge-m3 模型加载完成")

        # 阶段 3：checkpoint saver（AsyncPostgresSaver，表已由 Alembic 0002 建好）
        # 创建失败降级（如 Windows ProactorEventLoop 下 psycopg 不可用）——
        # get_ingest_graph 使用时会抛明确错误；API 本体仍可启动。
        if self._checkpointer is None and self._fake("checkpointer") is None:
            try:
                from app.infrastructure.checkpoint.pg_saver import create_pg_saver

                self._checkpointer = await create_pg_saver(
                    self.get_settings().resolved_database_url
                )
                print("[API] Postgres checkpointer 就绪")
            except Exception as e:
                print(f"[API] 警告: Postgres checkpointer 创建失败（图不可用）: {e}")

        self._started = True

    async def close(self) -> None:
        """幂等关闭：统一 dispose 全部基础设施。"""
        if self._closed:
            return

        # engine：真实 lazy 创建的优先；注入的 fake engine 同样 dispose（测试可断言）
        import inspect as _inspect

        engine = self._engine or self._fake("engine")
        if engine is not None:
            dispose = getattr(engine, "dispose", None)
            if dispose is not None:
                if _inspect.iscoroutinefunction(dispose):
                    await dispose()
                else:
                    dispose()
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
        if self._event_bus is not None:
            try:
                await self._event_bus.close()
            except Exception:
                pass
        if self._milvus is not None:
            self._milvus.close()
        if self._es is not None:
            self._es.close()
        # 真实 lazy 创建的与注入的 fake 一起释放（测试可断言释放回调）
        embedder = self._embedder or self._fake("embedder")
        if embedder is not None and hasattr(embedder, "release"):
            embedder.release()
        llm = self._llm or self._fake("llm")
        if llm is not None and hasattr(llm, "release"):
            llm.release()
        if self._checkpointer is not None:
            from app.infrastructure.checkpoint.pg_saver import close_pg_saver

            await close_pg_saver(self._checkpointer)

        self._engine = None
        self._sessionmaker = None
        self._redis = None
        self._es = None
        self._milvus = None
        self._minio = None
        self._mineru = None
        self._embedder = None
        self._llm = None
        self._vault = None
        self._quota_store = None
        self._queue = None
        self._event_bus = None
        self._ws = None
        self._key_manager = None
        self._checkpointer = None
        self._ingest_graph = None
        self._index_subgraph = None
        self._submission_service = None
        self._delete_service = None
        self._retry_service = None
        self._started = False
        self._closed = True
