"""异步 SQLAlchemy 引擎 & session"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session
