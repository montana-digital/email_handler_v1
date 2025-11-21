"""Reusable date filter component for filtering records by date/time ranges."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Optional

import streamlit as st


def render_date_filter(
    available_date_fields: list[tuple[str, str]],
    session_state_key: str = "date_filters",
    default_field: Optional[str] = None,
) -> Optional[dict]:
    """Render a date filter component.
    
    Args:
        available_date_fields: List of (field_key, display_name) tuples for available date fields
        session_state_key: Key to store date filter state in session_state
        default_field: Default date field to select (first field if None)
        
    Returns:
        Dictionary with filter configuration:
        {
            "field": str,  # Selected date field key
            "start_date": Optional[datetime],  # Start of date range
            "end_date": Optional[datetime],  # End of date range
            "enabled": bool  # Whether filter is active
        }
        Returns None if no filter is configured
    """
    if not available_date_fields:
        return None
    
    # Initialize session state
    if session_state_key not in st.session_state:
        st.session_state[session_state_key] = {
            "field": default_field or available_date_fields[0][0],
            "start_date": None,
            "end_date": None,
            "enabled": False,
        }
    
    filter_state = st.session_state[session_state_key]
    
    # Date filter UI
    with st.container(border=True):
        st.markdown("**📅 Date Range Filter**")
        
        # Date field selection
        field_options = {name: key for key, name in available_date_fields}
        field_names = list(field_options.keys())
        
        # Find current field index
        current_field_name = next(
            (name for key, name in available_date_fields if key == filter_state.get("field")),
            available_date_fields[0][1]
        )
        current_index = field_names.index(current_field_name) if current_field_name in field_names else 0
        
        selected_field_name = st.selectbox(
            "Date/Time Field",
            options=field_names,
            index=current_index,
            key=f"{session_state_key}_field_select",
            help="Select which date/time field to filter by"
        )
        selected_field = field_options[selected_field_name]
        filter_state["field"] = selected_field
        
        # Enable/disable toggle
        filter_state["enabled"] = st.checkbox(
            "Enable date filter",
            value=filter_state.get("enabled", False),
            key=f"{session_state_key}_enabled",
            help="Check to apply date range filtering"
        )
        
        if filter_state["enabled"]:
            # Date range inputs
            date_col1, date_col2 = st.columns(2)
            
            with date_col1:
                # Get start date value
                start_date_value = None
                if filter_state.get("start_date"):
                    if isinstance(filter_state["start_date"], datetime):
                        start_date_value = filter_state["start_date"].date()
                    elif isinstance(filter_state["start_date"], date):
                        start_date_value = filter_state["start_date"]
                
                start_date = st.date_input(
                    "Start Date",
                    value=start_date_value,
                    key=f"{session_state_key}_start_date",
                    help="Records with dates on or after this date will be included"
                )
                
                # Get start time value
                start_time_value = time(0, 0, 0)
                if filter_state.get("start_date") and isinstance(filter_state["start_date"], datetime):
                    start_time_value = filter_state["start_date"].time()
                
                start_time = st.time_input(
                    "Start Time",
                    value=start_time_value,
                    key=f"{session_state_key}_start_time",
                    help="Time component for start date"
                )
                
                # Only combine if date is not None
                if start_date is not None:
                    filter_state["start_date"] = datetime.combine(start_date, start_time).replace(tzinfo=timezone.utc)
                else:
                    filter_state["start_date"] = None
            
            with date_col2:
                # Get end date value
                end_date_value = None
                if filter_state.get("end_date"):
                    if isinstance(filter_state["end_date"], datetime):
                        end_date_value = filter_state["end_date"].date()
                    elif isinstance(filter_state["end_date"], date):
                        end_date_value = filter_state["end_date"]
                
                end_date = st.date_input(
                    "End Date",
                    value=end_date_value,
                    key=f"{session_state_key}_end_date",
                    help="Records with dates on or before this date will be included"
                )
                
                # Get end time value
                end_time_value = time(23, 59, 59)
                if filter_state.get("end_date") and isinstance(filter_state["end_date"], datetime):
                    end_time_value = filter_state["end_date"].time()
                
                end_time = st.time_input(
                    "End Time",
                    value=end_time_value,
                    key=f"{session_state_key}_end_time",
                    help="Time component for end date"
                )
                
                # Only combine if date is not None
                if end_date is not None:
                    filter_state["end_date"] = datetime.combine(end_date, end_time).replace(tzinfo=timezone.utc)
                else:
                    filter_state["end_date"] = None
            
            # Validation
            if filter_state.get("start_date") and filter_state.get("end_date"):
                if filter_state["start_date"] > filter_state["end_date"]:
                    st.error("⚠️ Start date must be before or equal to end date")
                    filter_state["enabled"] = False
            
            # Clear button
            if st.button("Clear Date Filter", key=f"{session_state_key}_clear", use_container_width=True):
                filter_state["start_date"] = None
                filter_state["end_date"] = None
                filter_state["enabled"] = False
                st.rerun()
        else:
            # Clear dates when disabled
            filter_state["start_date"] = None
            filter_state["end_date"] = None
    
    if filter_state.get("enabled") and (filter_state.get("start_date") or filter_state.get("end_date")):
        return {
            "field": filter_state["field"],
            "start_date": filter_state.get("start_date"),
            "end_date": filter_state.get("end_date"),
            "enabled": True,
        }
    return None


def apply_date_filter(records: list[dict], date_filter: Optional[dict], date_field_accessor: callable) -> list[dict]:
    """Apply date filter to a list of records.
    
    Args:
        records: List of record dictionaries to filter
        date_filter: Date filter configuration from render_date_filter()
        date_field_accessor: Function to extract date value from a record (record -> Optional[datetime])
        
    Returns:
        Filtered list of records
    """
    if not date_filter or not date_filter.get("enabled"):
        return records
    
    start_date = date_filter.get("start_date")
    end_date = date_filter.get("end_date")
    
    if not start_date and not end_date:
        return records
    
    filtered = []
    for record in records:
        record_date = date_field_accessor(record)
        
        if record_date is None:
            # Skip records with no date value
            continue
        
        # Ensure record_date is timezone-aware for comparison
        if record_date.tzinfo is None:
            record_date = record_date.replace(tzinfo=timezone.utc)
        
        # Check if date is within range
        if start_date and record_date < start_date:
            continue
        if end_date and record_date > end_date:
            continue
        
        filtered.append(record)
    
    return filtered

