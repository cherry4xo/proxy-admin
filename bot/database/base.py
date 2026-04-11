from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        from bot.config import settings
        _engine = create_async_engine(settings.DATABASE_URL, echo=False)
    return _engine


def _get_session_factory() -> async_sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(_get_engine(), expire_on_commit=False)
    return _session_factory


def async_session_factory() -> AsyncSession:
    return _get_session_factory()()


def get_engine() -> AsyncEngine:
    return _get_engine()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with _get_session_factory()() as session:
        yield session


async def init_db() -> None:
    async with _get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
