import streamlit as st
from compatibility_analyzer.models import (
    MigrationContext,
)

DEFAULT_STATE = {
    "context": None,
    # infrastructure
    "source_connector": None,
    "target_connector": None,
    "llm_client": None,

    # system selections
    "source_system": "CSV/XLSX",
    "target_system": "Odoo",

    # discovered entities
    "source_models": None,
    "target_models": None,

    # workflow selections
    "source_entity": None,
    "target_entity": None,
    "target_confirmed": False,

    # uploaded file
    "uploaded_file": None,

    # schemas
    "source_schema": None,
    "target_schema": None,
    "selected_source_schema": None,

    # planning
    "source_samples": None,
    "source_field_analysis": None,
    "selected_source_fields": [],

    # AI
    "prediction": None,

    # analysis
    "compatibility": None,

    # reporting
    "report_path": None,
}


def initialize_state():
    """
    Ensure all required session state keys exist, then auto-fill any saved
    credentials that haven't been set yet this session.

    Credentials are loaded once per session (guarded by _creds_loaded flag)
    so that live edits in the sidebar are never overwritten on rerun.
    Widget-bound keys (source_system, target_system) are applied only if the
    key doesn't exist yet — before the widget is instantiated on first run.
    """
    for key, value in DEFAULT_STATE.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if st.session_state.context is None:
        st.session_state.context = MigrationContext(
            source_system="",
            target_system="",
        )

    # Auto-fill credentials exactly once per browser session
    if not st.session_state.get("_creds_loaded"):
        st.session_state["_creds_loaded"] = True
        try:
            from compatibility_analyzer.utils.credentials import load_credentials
            saved = load_credentials()
            for key, value in saved.items():
                # Only fill keys that are still at their default / empty value
                # so a live edit in the sidebar is never overwritten.
                current = st.session_state.get(key)
                if current in (None, "", [], False):
                    st.session_state[key] = value
        except Exception:
            pass  # Never crash startup because of a bad credentials file

def reset_analysis_state():
    """
    Reset compatibility analysis outputs while preserving connections.
    """

    keys = [
        "prediction",
        "compatibility",
        "report_path",
        "target_schema",
        "target_entity",
        "target_confirmed",
    ]

    for key in keys:
        st.session_state[key] = DEFAULT_STATE[key]


def reset_source_state():
    """
    Reset source-specific planning state.
    """

    keys = [
        "source_entity",
        "source_schema",
        "selected_source_schema",
        "source_samples",
        "source_field_analysis",
        "selected_source_fields",
    ]

    for key in keys:
        st.session_state[key] = DEFAULT_STATE[key]

    reset_analysis_state()


# Keys that are bound to sidebar widgets — Streamlit forbids writing to
# these after the widget is instantiated.  Any reset must skip them.
_WIDGET_BOUND_KEYS = frozenset({
    "source_system",
    "target_system",
})


def reset_all_runtime_state():
    """
    Reset everything except configured systems and widget-bound keys.

    source_system / target_system are owned by st.selectbox widgets in the
    sidebar; writing to them after instantiation raises StreamlitAPIException.
    They are intentionally preserved by simply not touching them.
    """
    for key, value in DEFAULT_STATE.items():
        if key not in _WIDGET_BOUND_KEYS:
            st.session_state[key] = value


def is_csv_source():
    return st.session_state.source_system == "CSV/XLSX"


def is_same_erp():
    source = st.session_state.source_system.strip().lower()
    target = st.session_state.target_system.strip().lower()
    return source == target