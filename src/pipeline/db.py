from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_settings

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_settings().database_url,
            echo=False,
            connect_args={
                "ssl": False,
                "timeout": 30,
                "command_timeout": 60,
            },
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=5,
            max_overflow=5,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def reset_engine() -> None:
    """Drop pooled connections so the next checkout opens a fresh socket."""
    global _engine, _session_factory
    engine = _engine
    _session_factory = None
    _engine = None
    if engine is not None:
        await engine.dispose()