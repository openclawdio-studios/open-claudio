"""
Async SQLAlchemy engine and session factory.

DATABASE_URL defaults to the docker-compose service name.
If Postgres is unreachable, the module initializes in degraded mode
so the agent keeps running without instrumentation.
"""

import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql import text

logger = logging.getLogger("db.connection")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://claudio:claudio_dev@postgres:5432/claudio",
)

# pool_pre_ping=True: validates connection health before use
engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,
)

AsyncSessionFactory = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def check_connection() -> bool:
    """Return True if the database is reachable, False otherwise."""
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("Database not reachable: %s", exc)
        return False
