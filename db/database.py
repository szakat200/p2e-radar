import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from config import config
from db.models import Base

logger = logging.getLogger(__name__)

# SQLite требует StaticPool + check_same_thread=False; PostgreSQL — NullPool
_is_sqlite = config.DATABASE_URL.startswith("sqlite")

engine = create_async_engine(
    config.DATABASE_URL,
    echo=config.DEBUG,
    **({
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    } if _is_sqlite else {
        "poolclass": NullPool,
    })
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized")


async def close_db() -> None:
    await engine.dispose()
    logger.info("Database connection closed")
