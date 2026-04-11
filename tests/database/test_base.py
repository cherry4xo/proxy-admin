import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@pytest.fixture(autouse=True)
def _reset_db_singletons():
    import bot.database.base as db
    db._engine = None
    db._session_factory = None
    yield
    db._engine = None
    db._session_factory = None


@pytest.fixture()
def db_url(tmp_path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"


def test_engine_uses_database_url_from_settings(db_url, mocker):
    mocker.patch("bot.config.settings", DATABASE_URL=db_url)

    from bot.database.base import _get_engine

    engine = _get_engine()

    assert str(engine.url) == db_url


def test_engine_is_cached_across_calls(db_url, mocker):
    mocker.patch("bot.config.settings", DATABASE_URL=db_url)

    from bot.database.base import _get_engine

    first = _get_engine()
    second = _get_engine()

    assert first is second


def test_engine_not_created_before_first_call():
    import bot.database.base as db

    assert db._engine is None


def test_async_session_factory_returns_async_session(db_url, mocker):
    mocker.patch("bot.config.settings", DATABASE_URL=db_url)

    from bot.database.base import async_session_factory

    session = async_session_factory()

    assert isinstance(session, AsyncSession)


def test_get_engine_returns_async_engine(db_url, mocker):
    mocker.patch("bot.config.settings", DATABASE_URL=db_url)

    from bot.database.base import get_engine

    engine = get_engine()

    assert isinstance(engine, AsyncEngine)


@pytest.mark.asyncio
async def test_init_db_creates_tables(db_url, mocker):
    mocker.patch("bot.config.settings", DATABASE_URL=db_url)

    from bot.database.base import Base, init_db
    from bot.database import models  # noqa: F401

    await init_db()

    from pathlib import Path
    db_path = Path(db_url.replace("sqlite+aiosqlite:///", ""))
    assert db_path.exists()
    assert db_path.stat().st_size > 0


@pytest.mark.asyncio
async def test_get_session_yields_async_session(db_url, mocker):
    mocker.patch("bot.config.settings", DATABASE_URL=db_url)

    from bot.database.base import Base, _get_engine, get_session
    from bot.database import models  # noqa: F401

    async with _get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async for session in get_session():
        assert isinstance(session, AsyncSession)
