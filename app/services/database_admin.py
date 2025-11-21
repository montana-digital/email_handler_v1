"""Utilities for database inspection and administration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from loguru import logger
from sqlalchemy import MetaData, Table, delete, func, inspect, insert, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.utils.error_handling import format_database_error
from app.utils.validation import validate_table_name


@dataclass(slots=True)
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    default: str | None
    primary_key: bool


@dataclass(slots=True)
class TableSchema:
    columns: List[ColumnInfo]
    foreign_keys: List[str]
    indexes: List[str]


@dataclass(slots=True)
class TableSummary:
    name: str
    schema: TableSchema
    row_count: int
    sample_rows: List[Dict[str, object]]


def list_user_table_names(engine: Engine, *, exclude: Sequence[str]) -> List[str]:
    """List user table names with error handling.
    
    Args:
        engine: Database engine
        exclude: Sequence of table names to exclude
        
    Returns:
        Sorted list of table names
        
    Raises:
        OperationalError: If database inspection fails
    """
    try:
        inspector = inspect(engine)
        tables = [
            name for name in inspector.get_table_names() if name not in exclude
        ]
        return sorted(tables)
    except Exception as exc:
        logger.error("Failed to list table names: %s", exc)
        error_msg = format_database_error(exc, "list tables")
        raise OperationalError(error_msg, None, None) from exc


def _load_schema(engine: Engine, table_name: str) -> TableSchema:
    """Load table schema with validation and error handling.
    
    Args:
        engine: Database engine
        table_name: Name of table to inspect
        
    Returns:
        TableSchema object
        
    Raises:
        ValueError: If table_name is invalid
        OperationalError: If table doesn't exist or inspection fails
    """
    is_valid, error_msg = validate_table_name(table_name)
    if not is_valid:
        raise ValueError(error_msg)
    
    try:
        inspector = inspect(engine)
        
        # Check if table exists
        if table_name not in inspector.get_table_names():
            raise OperationalError(
                f"Table '{table_name}' does not exist",
                None,
                None
            )
        
        columns = []
        pk_columns = set(inspector.get_pk_constraint(table_name).get("constrained_columns") or [])
        for column in inspector.get_columns(table_name):
            columns.append(
                ColumnInfo(
                    name=column["name"],
                    type=str(column["type"]),
                    nullable=column.get("nullable", True),
                    default=str(column.get("default")) if column.get("default") is not None else None,
                    primary_key=column["name"] in pk_columns,
                )
            )

        foreign_keys = []
        for fk in inspector.get_foreign_keys(table_name):
            if not fk.get("constrained_columns"):
                continue
            referred_table = fk.get("referred_table")
            constrained_columns = ", ".join(fk["constrained_columns"])
            foreign_keys.append(f"{constrained_columns} ➜ {referred_table}")

        indexes = [
            f"{idx['name']} ({', '.join(idx.get('column_names') or [])})"
            for idx in inspector.get_indexes(table_name)
        ]

        return TableSchema(columns=columns, foreign_keys=foreign_keys, indexes=indexes)
    except OperationalError:
        raise
    except Exception as exc:
        logger.error("Failed to load schema for table %s: %s", table_name, exc)
        error_msg = format_database_error(exc, f"load schema for table '{table_name}'")
        raise OperationalError(error_msg, None, None) from exc


def _load_table(session: Session, table_name: str) -> Table:
    """Load table object with validation.
    
    Args:
        session: Database session
        table_name: Name of table to load
        
    Returns:
        Table object
        
    Raises:
        ValueError: If table_name is invalid
        OperationalError: If table doesn't exist
    """
    is_valid, error_msg = validate_table_name(table_name)
    if not is_valid:
        raise ValueError(error_msg)
    
    try:
        metadata = MetaData()
        return Table(table_name, metadata, autoload_with=session.bind)
    except Exception as exc:
        logger.error("Failed to load table %s: %s", table_name, exc)
        error_msg = format_database_error(exc, f"load table '{table_name}'")
        raise OperationalError(error_msg, None, None) from exc


def load_table_summary(
    session: Session,
    table_name: str,
    *,
    sample_limit: int = 100,
) -> TableSummary:
    """Load table summary with validation and error handling.
    
    Args:
        session: Database session
        table_name: Name of table to summarize
        sample_limit: Maximum number of sample rows to return
        
    Returns:
        TableSummary object
        
    Raises:
        ValueError: If table_name is invalid
        OperationalError: If table doesn't exist or query fails
    """
    try:
        table = _load_table(session, table_name)

        row_count = session.execute(select(func.count()).select_from(table)).scalar() or 0
        rows: List[Dict[str, object]] = []
        if row_count:
            result = session.execute(select(table).limit(sample_limit))
            rows = [dict(row._mapping) for row in result]

        schema = _load_schema(session.bind, table_name)
        return TableSummary(
            name=table_name,
            schema=schema,
            row_count=row_count,
            sample_rows=rows,
        )
    except (ValueError, OperationalError):
        raise
    except Exception as exc:
        logger.error("Failed to load table summary for %s: %s", table_name, exc)
        error_msg = format_database_error(exc, f"load summary for table '{table_name}'")
        raise OperationalError(error_msg, None, None) from exc


def drop_table(engine: Engine, table_name: str) -> None:
    """Drop a table with validation and error handling.
    
    Args:
        engine: Database engine
        table_name: Name of table to drop
        
    Raises:
        ValueError: If table_name is invalid
        OperationalError: If table doesn't exist or drop fails
    """
    is_valid, error_msg = validate_table_name(table_name)
    if not is_valid:
        raise ValueError(error_msg)
    
    try:
        metadata = MetaData()
        table = Table(table_name, metadata, autoload_with=engine)
        table.drop(engine)
        logger.info("Dropped table %s", table_name)
    except Exception as exc:
        logger.error("Failed to drop table %s: %s", table_name, exc)
        error_msg = format_database_error(exc, f"drop table '{table_name}'")
        raise OperationalError(error_msg, None, None) from exc


def truncate_table(session: Session, table_name: str) -> None:
    """Truncate a table with validation and error handling.
    
    Args:
        session: Database session
        table_name: Name of table to truncate
        
    Raises:
        ValueError: If table_name is invalid
        OperationalError: If table doesn't exist or truncate fails
        
    Note:
        This function commits the transaction. Do not call from within session_scope().
    """
    try:
        table = _load_table(session, table_name)
        session.execute(delete(table))
        session.commit()
        logger.info("Truncated table %s", table_name)
    except (ValueError, OperationalError):
        raise
    except Exception as exc:
        session.rollback()
        logger.error("Failed to truncate table %s: %s", table_name, exc)
        error_msg = format_database_error(exc, f"truncate table '{table_name}'")
        raise OperationalError(error_msg, None, None) from exc


def fetch_table_data(session: Session, table_name: str, limit: int | None = None) -> List[Dict[str, object]]:
    """Fetch table data with validation and error handling.
    
    Args:
        session: Database session
        table_name: Name of table to fetch from
        limit: Optional limit on number of rows
        
    Returns:
        List of row dictionaries
        
    Raises:
        ValueError: If table_name is invalid
        OperationalError: If table doesn't exist or query fails
    """
    try:
        table = _load_table(session, table_name)
        stmt = select(table)
        if limit:
            stmt = stmt.limit(limit)
        result = session.execute(stmt)
        return [dict(row._mapping) for row in result]
    except (ValueError, OperationalError):
        raise
    except Exception as exc:
        logger.error("Failed to fetch data from table %s: %s", table_name, exc)
        error_msg = format_database_error(exc, f"fetch data from table '{table_name}'")
        raise OperationalError(error_msg, None, None) from exc


def _primary_keys(schema: TableSchema) -> List[str]:
    return [column.name for column in schema.columns if column.primary_key]


def sync_table_changes(
    session: Session,
    table_name: str,
    original_rows: Iterable[Dict[str, object]],
    updated_rows: Iterable[Dict[str, object]],
    primary_keys: Sequence[str],
) -> Tuple[int, int, int]:
    if not primary_keys:
        raise ValueError("Primary key required to synchronize changes.")

    table = _load_table(session, table_name)
    original_map = {tuple(row.get(pk) for pk in primary_keys): row for row in original_rows}
    updated_map = {tuple(row.get(pk) for pk in primary_keys): row for row in updated_rows}

    inserts = 0
    updates = 0
    deletes = 0

    for pk_tuple, original in original_map.items():
        if pk_tuple not in updated_map:
            condition = [table.c[pk] == original.get(pk) for pk in primary_keys]
            session.execute(delete(table).where(*condition))
            deletes += 1

    for pk_tuple, updated in updated_map.items():
        if None in pk_tuple:
            continue
        if pk_tuple not in original_map:
            session.execute(insert(table).values(**updated))
            inserts += 1
        else:
            original = original_map[pk_tuple]
            changes = {key: value for key, value in updated.items() if original.get(key) != value}
            if changes:
                condition = [table.c[pk] == pk_value for pk, pk_value in zip(primary_keys, pk_tuple)]
                session.execute(update(table).where(*condition).values(**changes))
                updates += 1

    session.commit()
    return inserts, updates, deletes


def execute_sql(session: Session, statement: str) -> dict:
    """Execute SQL statement with validation and error handling.
    
    Args:
        session: Database session
        statement: SQL statement to execute
        
    Returns:
        Dictionary with 'rows' and 'rowcount' keys
        
    Raises:
        ValueError: If statement is invalid
        OperationalError: If SQL execution fails
        
    Note:
        This function commits the transaction. Do not call from within session_scope().
        WARNING: This function does not prevent SQL injection. Use with caution.
    """
    result_payload: dict = {"rows": [], "rowcount": 0, "error": None}
    
    if not statement or not statement.strip():
        return result_payload
    
    # Basic safety check - warn about potentially dangerous operations
    statement_upper = statement.upper().strip()
    dangerous_keywords = ["DROP", "DELETE", "TRUNCATE", "ALTER", "CREATE", "INSERT", "UPDATE"]
    if any(keyword in statement_upper for keyword in dangerous_keywords):
        logger.warning("Potentially dangerous SQL statement detected: %s", statement[:100])
    
    try:
        result = session.execute(text(statement))
        if result.returns_rows:
            result_payload["rows"] = [dict(row._mapping) for row in result]
        result_payload["rowcount"] = result.rowcount or 0
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.exception("Failed to execute SQL statement: %s", exc)
        error_msg = format_database_error(exc, "execute SQL statement")
        result_payload["error"] = error_msg
        raise OperationalError(error_msg, None, None) from exc
    except Exception as exc:
        session.rollback()
        logger.exception("Unexpected error executing SQL statement: %s", exc)
        error_msg = format_database_error(exc, "execute SQL statement")
        result_payload["error"] = error_msg
        raise OperationalError(error_msg, None, None) from exc
    
    return result_payload

