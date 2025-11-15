"""Settings page with persistent configuration updates."""

from __future__ import annotations

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Sequence

import pandas as pd
import streamlit as st
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError

from app.config import AppConfig
from app.config_store import save_config
from app.db.init_db import get_engine, reset_engine, session_scope
from app.services.app_reset import backup_database, reset_application
from app.services.database_admin import (
    TableSummary,
    drop_table,
    execute_sql,
    fetch_table_data,
    list_user_table_names,
    load_table_summary,
    sync_table_changes,
    truncate_table,
)
from app.ui.state import AppState

EXCLUDED_TABLES: Sequence[str] = ("sqlite_sequence", "alembic_version")


def _as_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def render(state: AppState) -> None:
    if st.session_state.pop("__rerun", False):
        if hasattr(st, "rerun"):
            st.rerun()

    st.header("Settings")
    st.write("Configure local directories and database connection. Changes persist to `.env`.")

    with st.expander("Configuration", expanded=False):
        with st.form("settings_form"):
            input_dir = st.text_input(
                "Email Input Directory",
                value=str(state.config.input_dir),
                key="settings_input_dir",
            )
            cache_dir = st.text_input(
                "Pickle Cache Directory",
                value=str(state.config.pickle_cache_dir),
                key="settings_cache_dir",
            )
            output_dir = st.text_input(
                "Output Directory",
                value=str(state.config.output_dir),
                key="settings_output_dir",
            )
            scripts_dir = st.text_input(
                "Scripts Directory",
                value=str(state.config.scripts_dir),
                key="settings_scripts_dir",
            )
            log_dir = st.text_input(
                "Log Directory",
                value=str(state.config.log_dir),
                key="settings_log_dir",
            )
            db_url = st.text_input(
                "Database URL",
                value=state.config.database_url,
                key="settings_db_url",
                help="For SQLite, use format sqlite:///C:/path/to/email_handler.db",
            )

            submitted = st.form_submit_button("Save Settings")

    if submitted:
        try:
            new_config = AppConfig(
                database_url=db_url.strip(),
                pickle_cache_dir=_as_path(cache_dir),
                input_dir=_as_path(input_dir),
                output_dir=_as_path(output_dir),
                scripts_dir=_as_path(scripts_dir),
                log_dir=_as_path(log_dir),
                env_name=state.config.env_name,
            )

            new_config.input_dir.mkdir(parents=True, exist_ok=True)
            new_config.output_dir.mkdir(parents=True, exist_ok=True)
            new_config.pickle_cache_dir.mkdir(parents=True, exist_ok=True)
            new_config.scripts_dir.mkdir(parents=True, exist_ok=True)
            new_config.log_dir.mkdir(parents=True, exist_ok=True)

            env_path = save_config(new_config)
            reset_engine(new_config)

            state.config = new_config
            state.add_notification("Configuration updated and persisted.")

            st.success(f"Settings saved to {env_path} and database connection reloaded.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to save settings: {exc}")

    st.divider()

    st.subheader("Database Administration")

    engine = get_engine(config=state.config)
    table_names: List[str] = []
    try:
        table_names = list_user_table_names(engine, exclude=EXCLUDED_TABLES)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Unable to load table information: {exc}")

    table_buffers = st.session_state.setdefault("table_editor_buffers", {})

    if table_names:
        for table_name in table_names:
            with session_scope() as session:
                try:
                    summary = load_table_summary(session, table_name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to inspect table %s: %s", table_name, exc)
                    st.error(f"Failed to load table `{table_name}`: {exc}")
                    continue

            pk_columns = [col.name for col in summary.schema.columns if col.primary_key]
            with st.expander(f"{summary.name} ({summary.row_count} rows)", expanded=False):
                schema_df = pd.DataFrame(
                    [
                        {
                            "Column": col.name,
                            "Type": col.type,
                            "Nullable": col.nullable,
                            "Default": col.default,
                            "Primary Key": col.primary_key,
                        }
                        for col in summary.schema.columns
                    ]
                )
                st.markdown("**Schema**")
                st.dataframe(schema_df, use_container_width=True, hide_index=True)
                if summary.schema.foreign_keys:
                    st.caption("Foreign Keys: " + " • ".join(summary.schema.foreign_keys))
                if summary.schema.indexes:
                    st.caption("Indexes: " + " • ".join(summary.schema.indexes))

                with session_scope() as session:
                    limit = None if summary.row_count <= 500 else 500
                    data_rows = fetch_table_data(session, summary.name, limit=limit)

                st.markdown("**Data**")
                if pk_columns:
                    original_rows = table_buffers.setdefault(summary.name, data_rows)
                    data_df = pd.DataFrame(original_rows)
                    edited_df = st.data_editor(
                        data_df,
                        num_rows="dynamic",
                        use_container_width=True,
                        key=f"editor_{summary.name}",
                    )

                    cols = st.columns(4)
                    with cols[0]:
                        if st.button("Refresh", key=f"refresh_{summary.name}"):
                            with session_scope() as session:
                                refreshed_rows = fetch_table_data(session, summary.name, limit=limit)
                            table_buffers[summary.name] = refreshed_rows
                            st.session_state["__rerun"] = True
                            st.stop()
                    with cols[1]:
                        csv_bytes = edited_df.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            "Download CSV",
                            data=csv_bytes,
                            file_name=f"{summary.name}.csv",
                            mime="text/csv",
                            key=f"download_{summary.name}",
                        )
                    with cols[2]:
                        if st.button("Save Changes", key=f"save_{summary.name}"):
                            updated_rows = edited_df.to_dict(orient="records")
                            try:
                                with session_scope() as session:
                                    inserts, updates, deletes = sync_table_changes(
                                        session,
                                        summary.name,
                                        original_rows,
                                        updated_rows,
                                        pk_columns,
                                    )
                                table_buffers[summary.name] = updated_rows
                                st.success(
                                    f"Changes applied (inserted {inserts}, updated {updates}, deleted {deletes})."
                                )
                            except Exception as exc:  # noqa: BLE001
                                st.error(f"Failed to apply changes: {exc}")
                    with cols[3]:
                        if st.button("Truncate Table", key=f"truncate_{summary.name}"):
                            try:
                                with session_scope() as session:
                                    truncate_table(session, summary.name)
                                table_buffers[summary.name] = []
                                st.success(f"Table `{summary.name}` truncated.")
                                st.session_state["__rerun"] = True
                                st.stop()
                            except Exception as exc:  # noqa: BLE001
                                st.error(f"Failed to truncate table `{summary.name}`: {exc}")
                else:
                    st.info("Table editing requires a primary key. View-only mode.")
                    if summary.sample_rows:
                        st.dataframe(
                            pd.DataFrame(summary.sample_rows),
                            use_container_width=True,
                            hide_index=True,
                        )

                confirm = st.checkbox(
                    f"Enable delete for `{summary.name}`",
                    key=f"confirm_delete_{summary.name}",
                )
                if confirm:
                    if st.button(
                        f"Delete table `{summary.name}`",
                        key=f"delete_table_{summary.name}",
                    ):
                        try:
                            drop_table(engine, summary.name)
                            table_buffers.pop(summary.name, None)
                            st.success(f"Table `{summary.name}` deleted.")
                            st.session_state["__rerun"] = True
                            st.stop()
                        except Exception as exc:  # noqa: BLE001
                            st.error(f"Failed to delete table `{summary.name}`: {exc}")
    else:
        st.info("No user tables detected.")

    st.subheader("Bulk Table Operations")
    bulk_selection = st.multiselect("Select tables", options=table_names, key="bulk_tables")
    bulk_cols = st.columns(3)
    with bulk_cols[0]:
        if st.button("Truncate Selected", disabled=not bulk_selection):
            try:
                with session_scope() as session:
                    for table_name in bulk_selection:
                        truncate_table(session, table_name)
                st.success(f"Truncated {len(bulk_selection)} tables.")
                for table_name in bulk_selection:
                    table_buffers.pop(table_name, None)
                st.session_state["__rerun"] = True
                st.stop()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Bulk truncate failed: {exc}")
    with bulk_cols[1]:
        if st.button("Delete Selected", disabled=not bulk_selection):
            try:
                for table_name in bulk_selection:
                    drop_table(engine, table_name)
                    table_buffers.pop(table_name, None)
                st.success(f"Deleted {len(bulk_selection)} tables.")
                st.session_state["__rerun"] = True
                st.stop()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Bulk delete failed: {exc}")
    with bulk_cols[2]:
        if st.button("Download Selected CSVs", disabled=not bulk_selection):
            try:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                    with session_scope() as session:
                        for table_name in bulk_selection:
                            data_rows = fetch_table_data(session, table_name)
                            df = pd.DataFrame(data_rows)
                            archive.writestr(f"{table_name}.csv", df.to_csv(index=False))
                st.download_button(
                    "Download Archive",
                    data=zip_buffer.getvalue(),
                    file_name=f"tables_{datetime.now():%Y%m%dT%H%M%S}.zip",
                    mime="application/zip",
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Failed to export tables: {exc}")

    st.subheader("Maintenance & Diagnostics")
    maintenance_cols = st.columns(3)
    with maintenance_cols[0]:
        if st.button("Vacuum Database"):
            try:
                with engine.begin() as connection:
                    connection.exec_driver_sql("VACUUM")
                st.success("VACUUM completed successfully.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"VACUUM failed: {exc}")
    with maintenance_cols[1]:
        if st.button("Analyze Database"):
            try:
                with engine.begin() as connection:
                    connection.exec_driver_sql("ANALYZE")
                st.success("ANALYZE completed successfully.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"ANALYZE failed: {exc}")
    with maintenance_cols[2]:
        if st.button("Refresh Table List"):
            st.rerun()

    st.subheader("SQL Editor")
    st.write(
        "Execute SQL statements against the application database. Statements run within a transaction."
    )
    sql_command = st.text_area(
        "SQL Statement",
        key="sql_editor_statement",
        height=160,
        placeholder="SELECT * FROM input_emails LIMIT 10;",
    )
    history: List[str] = st.session_state.setdefault("sql_history", [])
    if st.button("Execute SQL", key="sql_editor_execute"):
        if not sql_command.strip():
            st.warning("Provide a SQL statement to execute.")
        else:
            try:
                with session_scope() as session:
                    result = execute_sql(session, sql_command)
                st.success(f"Statement executed. {result['rowcount']} rows affected.")
                if result["rows"]:
                    st.dataframe(pd.DataFrame(result["rows"]), use_container_width=True)
                history.insert(0, sql_command.strip())
                st.session_state["sql_history"] = history[:10]
            except SQLAlchemyError as exc:
                st.error(f"SQL execution failed: {exc}")

    if history:
        with st.expander("Recent SQL Statements", expanded=False):
            for idx, statement in enumerate(history, start=1):
                st.code(statement, language="sql")

    st.divider()

    st.subheader("Application Reset")
    with st.expander("Reset to first-run state", expanded=False):
        st.warning(
            "Use with caution. Choose which areas to reset. "
            "Type `RESET` to confirm."
        )
        reset_db = st.checkbox("Delete database file", value=True)
        reset_cache = st.checkbox("Clear cache directory", value=True)
        reset_output = st.checkbox("Clear output directory", value=True)
        reset_logs = st.checkbox("Clear log directory", value=True)
        create_backup = st.checkbox("Create database backup before reset", value=True)

        backup_message = None
        if create_backup and state.config.database_url.startswith("sqlite:///"):
            backup_dir = state.config.output_dir / "backups"
            backup_path = backup_dir / f"db_backup_{datetime.now():%Y%m%dT%H%M%S}.sqlite"
            backup_message = str(backup_path)
            st.caption(f"Backup will be stored at `{backup_message}`")

        reset_confirmation = st.text_input(
            "Type RESET to confirm", key="reset_confirmation"
        )
        reset_disabled = reset_confirmation.strip().upper() != "RESET"
        if st.button(
            "Reset Application",
            disabled=reset_disabled,
            type="primary",
        ):
            try:
                if create_backup and backup_message:
                    backup_database(state.config, Path(backup_message))
                    st.success(f"Database backup created at `{backup_message}`.")
                reset_application(
                    state.config,
                    reset_database=reset_db,
                    reset_cache=reset_cache,
                    reset_output=reset_output,
                    reset_logs=reset_logs,
                )
                reset_engine(state.config)
                st.success("Application reset successfully. Reloading...")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Failed to reset application: {exc}")
