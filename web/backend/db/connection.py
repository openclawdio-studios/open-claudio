import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://claudio:claudio_dev@postgres:5432/claudio")

engine = create_async_engine(DATABASE_URL, pool_size=5, pool_pre_ping=True, echo=False)
AsyncSessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
