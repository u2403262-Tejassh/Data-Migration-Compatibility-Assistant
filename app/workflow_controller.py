import logging
import tempfile
from pathlib import Path

import streamlit as st

from compatibility_analyzer.connectors.connector_factory import ConnectorFactory
from compatibility_analyzer.llm_client import LLMClient
from compatibility_analyzer.matching.entity_matcher import predict_target_entity
from compatibility_analyzer.planning.source_field_analyzer import (
    analyze_source_fields,
    filter_schema_fields,
    selected_field_names,
)
from compatibility_analyzer.planning.target_schema_analyzer import analyze_target_fields
from compatibility_analyzer.reasoning.compatibility_reasoner import analyze_compatibility
from compatibility_analyzer.reporting.report_generator import generate_report
from compatibility_analyzer.app.state_manager import (
    is_csv_source,
    is_same_erp,
    reset_analysis_state,
    reset_source_state,
)
from compatibility_analyzer.migration_catalog.catalog_manager import get_catalog

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────

def normalize_system(system_name: str) -> str:
    normalized = system_name.strip().lower()
    if normalized in {"csv/xlsx", "csv", "xlsx", "file"}:
        return "file"
    if normalized == "oracle fusion":
        return "oracle"
    return normalized


def write_uploaded_file(uploaded) -> str:
    suffix = Path(uploaded.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded.getbuffer())
        return tmp.name


def _to_dict(schema) -> dict:
    """Convert EntitySchema → dict, or pass a dict through unchanged."""
    if hasattr(schema, "to_dict"):
        return schema.to_dict()
    return schema


# ── Connector config builders ──────────────────────────────────────────────

def build_connector_config(prefix: str) -> dict:
    system_name = (
        st.session_state.source_system
        if prefix == "source"
        else st.session_state.target_system
    )

    if system_name == "Odoo":
        return {
            "url":       st.session_state.get(f"{prefix}_odoo_url"),
            "db":        st.session_state.get(f"{prefix}_odoo_db"),
            "username":  st.session_state.get(f"{prefix}_odoo_username"),
            "password":  st.session_state.get(f"{prefix}_odoo_password"),
            "auth_mode": (
                st.session_state
                .get(f"{prefix}_odoo_auth_mode", "Password")
                .lower()
                .replace(" ", "_")
            ),
        }

    if system_name == "Salesforce":
        return {
            "username":       st.session_state.get(f"{prefix}_salesforce_username"),
            "password":       st.session_state.get(f"{prefix}_salesforce_password"),
            "security_token": st.session_state.get(f"{prefix}_salesforce_token"),
            # "login" = Production + Developer Edition
            # "test"  = Sandboxes ONLY
            "domain":         st.session_state.get(f"{prefix}_salesforce_domain", "login"),
            # Optional My Domain hostname (e.g. mycompany.my.salesforce.com)
            "custom_domain":  (
                st.session_state.get(f"{prefix}_salesforce_custom_domain", "") or None
            ),
        }

    if system_name == "Oracle Fusion":
        return {
            "url":      st.session_state.get(f"{prefix}_oracle_url"),
            "username": st.session_state.get(f"{prefix}_oracle_username"),
            "password": st.session_state.get(f"{prefix}_oracle_password"),
        }

    raise ValueError(f"Unsupported connector config for {system_name}")


# ── Infrastructure init ────────────────────────────────────────────────────

def initialize_connections():
    """
    Initialize infrastructure.
    CSV source skips source connector initialization.
    Groq API key is mandatory.
    """
    api_key = st.session_state.get("groq_api_key")
    if not api_key:
        raise ValueError("Groq API key is required.")

    st.session_state.llm_client = LLMClient(api_key)

    target_connector = ConnectorFactory.create(
        normalize_system(st.session_state.target_system),
        build_connector_config("target"),
    )
    target_connector.test_connection()
    st.session_state.target_connector = target_connector
    st.session_state.target_models = target_connector.discover_models()

    if not is_csv_source():
        source_connector = ConnectorFactory.create(
            normalize_system(st.session_state.source_system),
            build_connector_config("source"),
        )
        source_connector.test_connection()
        st.session_state.source_connector = source_connector
        st.session_state.source_models = source_connector.discover_models()

    reset_source_state()


# ── Source initialization ──────────────────────────────────────────────────

def initialize_csv_source(uploaded):
    """Lazy file connector initialization."""
    if not uploaded:
        raise ValueError("Upload a CSV/XLSX file first.")

    file_path = write_uploaded_file(uploaded)
    source_connector = ConnectorFactory.create("file", {"file_path": file_path})

    st.session_state.source_connector = source_connector
    st.session_state.source_models = source_connector.discover_models()

    schema = _to_dict(source_connector.fetch_schema("uploaded_dataset"))

    st.session_state.source_schema = schema
    st.session_state.selected_source_schema = schema
    st.session_state.source_entity = "uploaded_dataset"


def prepare_erp_source(source_entity: str):
    """
    ERP source introspection workflow.

    For ERP sources the full schema is used — CSV-style population filtering
    is not applied because ERP fields are metadata-driven, not data-driven.
    """
    connector = st.session_state.source_connector
    schema = _to_dict(connector.fetch_schema(source_entity))
    samples = connector.sample_records(source_entity, limit=100)
    analysis = analyze_source_fields(schema, samples)

    all_fields = list(schema.get("fields", {}).keys())

    st.session_state.source_entity = source_entity
    st.session_state.source_schema = schema
    st.session_state.source_samples = samples
    st.session_state.source_field_analysis = analysis
    st.session_state.selected_source_fields = all_fields
    st.session_state.selected_source_schema = schema

    logger.debug(
        "ERP source prepared: entity=%s  fields=%d",
        source_entity,
        len(all_fields),
    )

    reset_analysis_state()


def update_selected_source_fields(selected_fields: list):
    """Update filtered schema when the user changes field selection (CSV only)."""
    st.session_state.selected_source_fields = selected_fields

    if is_csv_source():
        st.session_state.selected_source_schema = filter_schema_fields(
            st.session_state.source_schema,
            selected_fields,
        )
    else:
        # ERP: always use the full schema
        st.session_state.selected_source_schema = st.session_state.source_schema

    reset_analysis_state()


# ── AI prediction ──────────────────────────────────────────────────────────

def predict_target():
    """AI target entity prediction. No-op for same-ERP migrations."""
    if is_same_erp():
        st.session_state.prediction = None
        return

    source_schema = (
        st.session_state.selected_source_schema
        or st.session_state.source_schema
    )

    clean_target_models = [
        {"model": m["model"], "name": m.get("name", m["model"])}
        for m in st.session_state.target_models
    ]

    prediction = predict_target_entity(
        st.session_state.llm_client,
        source_schema,
        clean_target_models,
        source_system=st.session_state.source_system,
        target_system=st.session_state.target_system,
    )

    st.session_state.prediction = prediction
    st.session_state.target_confirmed = False


# ── Analysis ───────────────────────────────────────────────────────────────

def confirm_target(target_entity: str):
    st.session_state.target_entity = target_entity
    st.session_state.target_confirmed = True
    st.session_state.compatibility = None
    st.session_state.target_schema = None


def run_compatibility_analysis():
    """Execute full compatibility analysis."""
    if not st.session_state.target_confirmed:
        raise ValueError("Target must be confirmed first.")

    # CSV uses the field-filtered schema; ERP uses the full schema
    source_schema = (
        st.session_state.selected_source_schema
        if is_csv_source()
        else st.session_state.source_schema
    )

    raw_target_schema = _to_dict(
        st.session_state.target_connector.fetch_schema(st.session_state.target_entity)
    )

    # Same-entity same-system analysis: skip the target field filter so all
    # fields appear — useful for Odoo → Odoo field completeness checks.
    same_entity = (
        st.session_state.source_system == st.session_state.target_system
        and st.session_state.source_entity == st.session_state.target_entity
    )
    target_schema = raw_target_schema if same_entity else analyze_target_fields(raw_target_schema)

    # --- Catalog-based field filtering (reduces noise before analysis) ---
    source_system = normalize_system(st.session_state.source_system)
    target_system = normalize_system(st.session_state.target_system)
    source_entity = st.session_state.source_entity
    target_entity = st.session_state.target_entity

    catalog = get_catalog(source_system, target_system)
    if catalog and not same_entity:
        source_schema = catalog.filter_source_schema(
            source_schema,
            source_entity,
            target_entity,
        )
        target_schema = catalog.filter_target_schema(
            target_schema,
            target_entity,
            source_entity,
        )
        logger.info(
            "Catalog filter applied: source_fields=%d  target_fields=%d",
            len(source_schema.get("fields", {})),
            len(target_schema.get("fields", {})),
        )
    # -----------------------------------------------------------------------

    logger.debug(
        "Running analysis: source_fields=%d  target_fields=%d",
        len(source_schema.get("fields", {})),
        len(target_schema.get("fields", {})),
    )

    compatibility = analyze_compatibility(
        st.session_state.llm_client,
        source_schema,
        target_schema,
    )

    st.session_state.target_schema = target_schema
    st.session_state.compatibility = compatibility


# ── Reporting ──────────────────────────────────────────────────────────────

def generate_pdf_report():
    """Generate PDF report from current session state."""
    if not st.session_state.compatibility:
        raise ValueError("Run analysis first.")

    source_schema = (
        st.session_state.selected_source_schema
        or st.session_state.source_schema
    )

    prediction = st.session_state.prediction or {
        "dataset_type":         st.session_state.source_entity,
        "predicted_model":      st.session_state.target_entity,
        "predicted_model_name": st.session_state.target_entity,
        "confidence":           "manual",
        "reasoning":            [],
        "alternatives":         [],
    }

    report_path = generate_report(
        source_schema,
        prediction,
        st.session_state.target_schema,
        st.session_state.compatibility,
    )

    st.session_state.report_path = report_path