"""Database initialization and session management utilities."""

from __future__ import annotations

import os
import platform
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import inspect

from app.config import AppConfig, load_config
from app.utils.error_handling import format_connection_error, format_database_error

from .models import Base

_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def _get_engine_connect_args(database_url: str) -> dict:
    """Get connection arguments for SQLite engine, including Windows-specific optimizations."""
    connect_args = {}
    
    # Enable WAL mode on Windows for better concurrent access
    if platform.system() == "Windows" and database_url.startswith("sqlite:///"):
        # WAL mode improves concurrent read access and reduces locking issues
        connect_args["check_same_thread"] = False
        # Set timeout for locked database (30 seconds)
        connect_args["timeout"] = 30.0
    
    return connect_args


def _validate_database_accessibility(db_url: str) -> tuple[bool, Optional[str]]:
    """Validate that the database file is accessible.
    
    Args:
        db_url: Database URL
        
    Returns:
        Tuple of (is_accessible, error_message)
    """
    if not db_url.startswith("sqlite:///"):
        return True, None  # Non-SQLite databases are handled by SQLAlchemy
    
    # Extract file path from SQLite URL
    file_path = db_url.replace("sqlite:///", "")
    
    # Handle absolute Windows paths
    if file_path.startswith("/") and platform.system() == "Windows":
        # Remove leading slash for Windows absolute paths
        file_path = file_path[1:]
    
    db_file = Path(file_path)
    db_dir = db_file.parent
    
    # Check if directory exists and is writable
    if db_dir.exists():
        if not os.access(db_dir, os.W_OK):
            return False, f"Database directory is not writable: {db_dir}"
    else:
        # Try to create directory
        try:
            db_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as exc:
            return False, f"Cannot create database directory: {exc}"
    
    # If database file exists, check if it's readable
    if db_file.exists():
        if not os.access(db_file, os.R_OK):
            return False, f"Database file is not readable: {db_file}"
        if not os.access(db_file, os.W_OK):
            return False, f"Database file is not writable: {db_file}"
    
    return True, None


def get_engine(database_url: Optional[str] = None, *, config: Optional[AppConfig] = None) -> Engine:
    """Get or create the database engine with error handling.
    
    Raises:
        OperationalError: If database connection fails
        PermissionError: If database file is not accessible
    """
    global _ENGINE

    cfg = config or load_config()
    db_url = database_url or cfg.database_url

    # Validate database accessibility before creating engine
    is_accessible, error_msg = _validate_database_accessibility(db_url)
    if not is_accessible:
        logger.error("Database accessibility check failed: %s", error_msg)
        raise OperationalError(
            error_msg or "Database is not accessible",
            None,
            None
        )

    connect_args = _get_engine_connect_args(db_url)

    try:
        if _ENGINE is None:
            _ENGINE = create_engine(db_url, echo=False, future=True, connect_args=connect_args)
            # Enable WAL mode for SQLite on Windows
            if platform.system() == "Windows" and db_url.startswith("sqlite:///"):
                _enable_wal_mode(_ENGINE, db_url)
        elif str(_ENGINE.url) != db_url:
            _ENGINE.dispose()
            _ENGINE = create_engine(db_url, echo=False, future=True, connect_args=connect_args)
            # Enable WAL mode for new engine
            if platform.system() == "Windows" and db_url.startswith("sqlite:///"):
                _enable_wal_mode(_ENGINE, db_url)
    except (OperationalError, SQLAlchemyError) as exc:
        error_msg = format_connection_error(exc, db_url)
        logger.error("Failed to create database engine: %s", exc)
        raise OperationalError(error_msg, None, None) from exc
    except Exception as exc:
        error_msg = format_connection_error(exc, db_url)
        logger.exception("Unexpected error creating database engine: %s", exc)
        raise OperationalError(error_msg, None, None) from exc
    
    return _ENGINE


def _enable_wal_mode(engine: Engine, db_url: str) -> None:
    """Enable WAL mode for SQLite database.
    
    Args:
        engine: SQLAlchemy engine
        db_url: Database URL for error context
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.commit()
        logger.debug("Enabled WAL mode for SQLite database")
    except Exception as exc:
        # Log warning but don't fail - WAL mode is optional optimization
        logger.warning("Failed to enable WAL mode for SQLite database at %s: %s", db_url, exc)
        # Note: This error is logged but not raised, as WAL mode is an optimization
        # The database will still work without WAL mode, just with potentially worse concurrency


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
    """Rebuild the SQLAlchemy engine and session factory for the supplied config.
    
    Raises:
        OperationalError: If database connection fails
    """
    global _ENGINE, _SESSION_FACTORY

    # Validate database accessibility before resetting
    is_accessible, error_msg = _validate_database_accessibility(config.database_url)
    if not is_accessible:
        logger.error("Database accessibility check failed during reset: %s", error_msg)
        raise OperationalError(
            error_msg or "Database is not accessible",
            None,
            None
        )

    if _ENGINE is not None:
        _ENGINE.dispose()

    try:
        connect_args = _get_engine_connect_args(config.database_url)
        _ENGINE = create_engine(config.database_url, echo=False, future=True, connect_args=connect_args)
        
        # Enable WAL mode for SQLite on Windows
        if platform.system() == "Windows" and config.database_url.startswith("sqlite:///"):
            _enable_wal_mode(_ENGINE, config.database_url)
    except (OperationalError, SQLAlchemyError) as exc:
        error_msg = format_connection_error(exc, config.database_url)
        logger.error("Failed to reset database engine: %s", exc)
        raise OperationalError(error_msg, None, None) from exc
    except Exception as exc:
        error_msg = format_connection_error(exc, config.database_url)
        logger.exception("Unexpected error resetting database engine: %s", exc)
        raise OperationalError(error_msg, None, None) from exc
    
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
    _apply_schema_patches(engine)


def _apply_schema_patches(engine: Engine) -> None:
    inspector = inspect(engine)

    def _has_column(table: str, column: str) -> bool:
        try:
            return any(col["name"] == column for col in inspector.get_columns(table))
        except Exception:
            # Table doesn't exist yet, will be created by create_all
            return False
    
    def _table_exists(table: str) -> bool:
        try:
            return table in inspector.get_table_names()
        except Exception:
            return False

    patches = [
        (
            "input_emails",
            "parse_status",
            "ALTER TABLE input_emails ADD COLUMN parse_status VARCHAR(32) DEFAULT 'success'",
        ),
        (
            "input_emails",
            "parse_error",
            "ALTER TABLE input_emails ADD COLUMN parse_error TEXT",
        ),
        (
            "input_emails",
            "knowledge_data",
            "ALTER TABLE input_emails ADD COLUMN knowledge_data JSON",
        ),
        (
            "parser_runs",
            "error_message",
            "ALTER TABLE parser_runs ADD COLUMN error_message TEXT",
        ),
    ]

    with engine.begin() as connection:
        for table, column, ddl in patches:
            if _table_exists(table) and not _has_column(table, column):
                try:
                    connection.execute(text(ddl))
                    logger.info("Applied schema patch: added column %s.%s", table, column)
                except Exception as exc:
                    logger.warning("Failed to apply schema patch for %s.%s: %s", table, column, exc)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for database sessions with proper error handling.
    
    Yields:
        Session: SQLAlchemy session
        
    Raises:
        OperationalError: If session creation or database operations fail
        SQLAlchemyError: For other database-related errors
    """
    try:
        session_factory = get_session_factory()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.error("Failed to get session factory: %s", exc)
        raise
    except Exception as exc:
        error_msg = format_connection_error(exc)
        logger.exception("Unexpected error getting session factory: %s", exc)
        raise OperationalError(error_msg, None, None) from exc
    
    session = session_factory()
    try:
        yield session
        session.commit()
    except (OperationalError, SQLAlchemyError) as exc:
        session.rollback()
        logger.error("Database operation failed, rolling back transaction: %s", exc)
        raise
    except (ValueError, TypeError, AttributeError) as exc:
        # Preserve validation and type errors - these are not database errors
        session.rollback()
        logger.warning("Validation error in database session: %s", exc)
        raise
    except Exception as exc:
        session.rollback()
        logger.exception("Unexpected error in database session: %s", exc)
        # Wrap non-SQLAlchemy exceptions in OperationalError for consistency
        error_msg = format_database_error(exc)
        raise OperationalError(error_msg, None, None) from exc
    finally:
        session.close()

