"""Utilities for database inspection and administration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence

from loguru import logger
from sqlalchemy import MetaData, Table, func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


@dataclass(slots=True)
class TableSummary:
    name: str
    columns: List[str]
    row_count: int
    sample_rows: List[Dict[str, object]]


def list_user_table_names(engine: Engine, *, exclude: Sequence[str]) -> List[str]:
    inspector = inspect(engine)
    tables = []
    for name in inspector.get_table_names():
        if name not in exclude:
            tables.append(name)
    return sorted(tables)


def load_table_summary(session: Session, table_name: str, *, sample_limit: int = 50) -> TableSummary:
    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=session.bind)

    row_count = session.execute(select(func.count()).select_from(table)).scalar() or 0
    rows = []
    if row_count:
        result = session.execute(select(table).limit(sample_limit))
        rows = [dict(row._mapping) for row in result]

    return TableSummary(
        name=table_name,
        columns=[column.name for column in table.columns],
        row_count=row_count,
        sample_rows=rows,
    )


def drop_table(engine: Engine, table_name: str) -> None:
    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=engine)
    table.drop(engine)


def execute_sql(session: Session, statement: str) -> dict:
    result_payload: dict = {"rows": [], "rowcount": 0}
    if not statement.strip():
        return result_payload
    try:
        result = session.execute(text(statement))
        if result.returns_rows:
            result_payload["rows"] = [dict(row._mapping) for row in result]
        result_payload["rowcount"] = result.rowcount or 0
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.exception("Failed to execute SQL statement: {}", exc)
        raise
    return result_payload

