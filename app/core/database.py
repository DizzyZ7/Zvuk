from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.core.config import settings

class Base(DeclarativeBase):
    pass

engine = create_async_engine(
    settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20,
)
session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
