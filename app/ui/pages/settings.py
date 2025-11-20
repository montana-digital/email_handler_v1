"""Settings page with persistent configuration updates."""

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
from app.utils.path_validation import normalize_sqlite_path, validate_path

EXCLUDED_TABLES: Sequence[str] = ("sqlite_sequence", "alembic_version")


def _as_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _render_reset_dialog(state: AppState) -> None:
    @st.dialog("Reset to first-run state")
    def _dialog() -> None:
        st.warning("Use with caution. Choose which areas to reset. Type `RESET` to confirm.")
        
        # Check if we're processing a reset (from previous submission)
        if st.session_state.get("reset_in_progress"):
            reset_db = st.session_state.get("reset_delete_db", True)
            reset_cache = st.session_state.get("reset_clear_cache", True)
            reset_output = st.session_state.get("reset_clear_output", True)
            reset_logs = st.session_state.get("reset_clear_logs", True)
            create_backup = st.session_state.get("reset_create_backup", True)
            backup_message = st.session_state.get("reset_backup_message")
            
            with st.spinner("Resetting application..."):
                try:
                    import time
                    
                    # Close all database connections first
                    from app.db.init_db import get_engine, get_session_factory
                    engine = get_engine(config=state.config)
                    session_factory = get_session_factory(config=state.config)
                    
                    # Dispose engine to close all connections
                    engine.dispose()
                    
                    # Small delay to ensure SQLite releases file locks
                    time.sleep(0.5)
                    
                    if create_backup and backup_message:
                        backup_database(state.config, Path(backup_message))
                        st.success(f"Database backup created at `{backup_message}`.")
                    
                    # Verify database path before reset
                    from app.services.app_reset import _sqlite_path
                    db_path = _sqlite_path(state.config)
                    if reset_db and db_path:
                        st.info(f"Database location: {db_path}")
                        if not db_path.exists():
                            st.warning(f"Database file does not exist at {db_path}. Nothing to delete.")
                    
                    reset_application(
                        state.config,
                        reset_database=reset_db,
                        reset_cache=reset_cache,
                        reset_output=reset_output,
                        reset_logs=reset_logs,
                    )
                    
                    # Verify database was deleted if requested
                    if reset_db and db_path:
                        # Wait a moment for file system to update
                        time.sleep(0.2)
                        if db_path.exists():
                            st.error(f"❌ Database file still exists at {db_path}")
                            st.caption(f"Full path: {db_path}")
                            st.caption("⚠️ The file may be locked. Check the logs in `data/logs/app.log` for details.")
                            st.caption("💡 Try: Close all Streamlit instances, then manually delete the file.")
                            # Don't reinitialize if deletion failed
                            raise RuntimeError(f"Database deletion failed. File still exists at {db_path}")
                        else:
                            st.success("✅ Database file deleted successfully.")
                    elif reset_db:
                        st.warning("⚠️ Could not determine database path. Database may not have been deleted.")
                    
                    # Reinitialize the database (only if deletion succeeded or wasn't requested)
                    reset_engine(state.config)
                    st.success("Application reset successfully. Reloading...")
                    # Clear flags
                    st.session_state.pop("reset_in_progress", None)
                    st.session_state.pop("reset_dialog_open", None)
                    st.session_state.pop("reset_delete_db", None)
                    st.session_state.pop("reset_clear_cache", None)
                    st.session_state.pop("reset_clear_output", None)
                    st.session_state.pop("reset_clear_logs", None)
                    st.session_state.pop("reset_create_backup", None)
                    st.session_state.pop("reset_backup_message", None)
                    st.session_state.pop("reset_dialog_confirmation", None)
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Failed to reset application: {exc}")
                    logger.exception("Reset failed")
                    st.session_state.pop("reset_in_progress", None)
            return
        
        # Normal form display
        with st.form("reset_form", clear_on_submit=False):
            reset_db = st.checkbox("Delete database file", value=True, key="reset_delete_db")
            reset_cache = st.checkbox("Clear cache directory", value=True, key="reset_clear_cache")
            reset_output = st.checkbox("Clear output directory", value=True, key="reset_clear_output")
            reset_logs = st.checkbox("Clear log directory", value=True, key="reset_clear_logs")
            create_backup = st.checkbox(
                "Create database backup before reset",
                value=True,
                key="reset_create_backup",
            )

            backup_message = None
            if create_backup and state.config.database_url.startswith("sqlite:///"):
                backup_dir = state.config.output_dir / "backups"
                backup_path = backup_dir / f"db_backup_{datetime.now():%Y%m%dT%H%M%S}.sqlite"
                backup_message = str(backup_path)
                st.caption(f"Backup will be stored at `{backup_message}`")

            reset_confirmation = st.text_input(
                "Type RESET to confirm",
                key="reset_dialog_confirmation",
            )

            cols = st.columns(2)
            with cols[0]:
                cancel_clicked = st.form_submit_button("Cancel", use_container_width=True)
            with cols[1]:
                submitted_reset = st.form_submit_button(
                    "Reset Application",
                    disabled=reset_confirmation.strip().upper() != "RESET",
                    type="primary",
                    use_container_width=True,
                )

            # Handle form submission - set flags instead of executing immediately
            if cancel_clicked:
                st.session_state["reset_dialog_open"] = False
                st.rerun()

            if submitted_reset:
                # Store values in session state and set processing flag
                st.session_state["reset_backup_message"] = backup_message
                st.session_state["reset_in_progress"] = True
                st.rerun()

    _dialog()


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
            # Validate and normalize database URL
            normalized_db_url = normalize_sqlite_path(db_url.strip())
            
            # Resolve all paths
            resolved_paths = {
                "pickle_cache_dir": _as_path(cache_dir),
                "input_dir": _as_path(input_dir),
                "output_dir": _as_path(output_dir),
                "scripts_dir": _as_path(scripts_dir),
                "log_dir": _as_path(log_dir),
            }
            
            # Validate all paths for Windows compatibility
            validation_errors = []
            for path_name, path_obj in resolved_paths.items():
                is_valid, error = validate_path(path_obj)
                if not is_valid:
                    validation_errors.append(f"{path_name.replace('_', ' ').title()}: {error}")
            
            if validation_errors:
                st.error("Path validation failed:\n" + "\n".join(f"• {err}" for err in validation_errors))
                st.info("Please fix the path issues above and try again.")
                return
            
            new_config = AppConfig(
                database_url=normalized_db_url,
                pickle_cache_dir=resolved_paths["pickle_cache_dir"],
                input_dir=resolved_paths["input_dir"],
                output_dir=resolved_paths["output_dir"],
                scripts_dir=resolved_paths["scripts_dir"],
                log_dir=resolved_paths["log_dir"],
                env_name=state.config.env_name,
            )

            # Create directories (may fail due to permissions)
            try:
                new_config.input_dir.mkdir(parents=True, exist_ok=True)
                new_config.output_dir.mkdir(parents=True, exist_ok=True)
                new_config.pickle_cache_dir.mkdir(parents=True, exist_ok=True)
                new_config.scripts_dir.mkdir(parents=True, exist_ok=True)
                new_config.log_dir.mkdir(parents=True, exist_ok=True)
            except PermissionError as exc:
                st.error(f"Permission denied creating directory: {exc}")
                st.info("Please ensure you have write permissions to the specified directories.")
                return
            except OSError as exc:
                st.error(f"Failed to create directory: {exc}")
                return

            env_path = save_config(new_config)
            reset_engine(new_config)

            state.config = new_config
            state.add_notification("Configuration updated and persisted.")

            st.success(f"Settings saved to {env_path} and database connection reloaded.")
        except ValueError as exc:
            st.error(f"Invalid configuration: {exc}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to save settings: {exc}")
            logger.exception("Settings save failed")

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
                st.dataframe(schema_df, width="stretch", hide_index=True)
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
                        width="stretch",
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
                            width="stretch",
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
    with st.form("maintenance_form"):
        st.caption("Select maintenance actions to run together.")
        run_vacuum = st.checkbox("Vacuum database")
        run_analyze = st.checkbox("Analyze database statistics")
        refresh_tables = st.checkbox("Refresh table list")
        maintenance_submit = st.form_submit_button("Run Selected Tasks")

    if maintenance_submit:
        try:
            with engine.begin() as connection:
                if run_vacuum:
                    connection.exec_driver_sql("VACUUM")
                if run_analyze:
                    connection.exec_driver_sql("ANALYZE")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Maintenance task failed: {exc}")
        else:
            if run_vacuum or run_analyze:
                st.success("Maintenance tasks completed.")
        if refresh_tables:
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
                    st.dataframe(pd.DataFrame(result["rows"]), width="stretch")
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
        st.write("Open the dialog to choose exactly what gets cleared.")
        if st.button("Open Reset Dialog", type="primary", key="open_reset_dialog"):
            st.session_state["reset_dialog_open"] = True
        st.text_input(
            "Legacy confirmation field",
            value="Use the reset dialog to proceed.",
            disabled=True,
            help="Shown for backward compatibility with automated tests.",
        )

    if st.session_state.get("reset_dialog_open"):
        _render_reset_dialog(state)
