"""Utilities for database inspection and administration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

from loguru import logger
from sqlalchemy import MetaData, Table, delete, func, inspect, insert, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


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
    inspector = inspect(engine)
    tables = [
        name for name in inspector.get_table_names() if name not in exclude
    ]
    return sorted(tables)


def _load_schema(engine: Engine, table_name: str) -> TableSchema:
    inspector = inspect(engine)
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


def _load_table(session: Session, table_name: str) -> Table:
    metadata = MetaData()
    return Table(table_name, metadata, autoload_with=session.bind)


def load_table_summary(
    session: Session,
    table_name: str,
    *,
    sample_limit: int = 100,
) -> TableSummary:
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


def drop_table(engine: Engine, table_name: str) -> None:
    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=engine)
    table.drop(engine)


def truncate_table(session: Session, table_name: str) -> None:
    table = _load_table(session, table_name)
    session.execute(delete(table))
    session.commit()


def fetch_table_data(session: Session, table_name: str, limit: int | None = None) -> List[Dict[str, object]]:
    table = _load_table(session, table_name)
    stmt = select(table)
    if limit:
        stmt = stmt.limit(limit)
    result = session.execute(stmt)
    return [dict(row._mapping) for row in result]


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

