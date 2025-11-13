"""Database initialization and session management utilities."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, load_config

from .models import Base

_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def get_engine(database_url: Optional[str] = None, *, config: Optional[AppConfig] = None) -> Engine:
    global _ENGINE

    cfg = config or load_config()
    db_url = database_url or cfg.database_url

    if _ENGINE is None:
        _ENGINE = create_engine(db_url, echo=False, future=True)
    elif str(_ENGINE.url) != db_url:
        _ENGINE.dispose()
        _ENGINE = create_engine(db_url, echo=False, future=True)
    return _ENGINE


def _build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )


def get_session_factory(config: Optional[AppConfig] = None) -> sessionmaker[Session]:
    global _SESSION_FACTORY
    engine = get_engine(config=config)
    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = _build_session_factory(engine)
    return _SESSION_FACTORY


def reset_engine(config: AppConfig) -> None:
    """Rebuild the SQLAlchemy engine and session factory for the supplied config."""
    global _ENGINE, _SESSION_FACTORY

    if _ENGINE is not None:
        _ENGINE.dispose()

    _ENGINE = create_engine(config.database_url, echo=False, future=True)
    _SESSION_FACTORY = _build_session_factory(_ENGINE)
    init_db(engine=_ENGINE, config=config)


def init_db(*, engine: Optional[Engine] = None, config: Optional[AppConfig] = None) -> None:
    cfg = config or load_config()
    cfg.pickle_cache_dir.mkdir(parents=True, exist_ok=True)
    cfg.input_dir.mkdir(parents=True, exist_ok=True)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    cfg.log_dir.mkdir(parents=True, exist_ok=True)

    if engine is None:
        engine = get_engine(config=cfg)

    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

