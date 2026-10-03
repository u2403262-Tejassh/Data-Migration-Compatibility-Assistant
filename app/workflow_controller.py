import logging
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from compatibility_analyzer.config import get_secret
from compatibility_analyzer.profiling.source_profiler import load_source_file

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
            "username": (
                st.session_state.get(f"{prefix}_salesforce_username")
                or get_secret("SALESFORCE_USERNAME")
            ),
            "password": (
                st.session_state.get(f"{prefix}_salesforce_password")
                or get_secret("SALESFORCE_PASSWORD")
            ),
            "security_token": (
                st.session_state.get(f"{prefix}_salesforce_token")
                or get_secret("SALESFORCE_SECURITY_TOKEN")
            ),
            # "login" = Production + Developer Edition; "test" = Sandbox.
            "domain": (
                st.session_state.get(f"{prefix}_salesforce_domain")
                or get_secret("SALESFORCE_DOMAIN", "login")
            ),
            # Optional My Domain hostname (e.g. mycompany.my.salesforce.com).
            "custom_domain": (
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


class MissingRequiredSecretError(ValueError):
    """Raised when a required deployment secret or connection value is absent."""


# ── Infrastructure init ────────────────────────────────────────────────────

def _require_salesforce_credentials(config):
    required = {
        "username": "SALESFORCE_USERNAME",
        "password": "SALESFORCE_PASSWORD",
        "security_token": "SALESFORCE_SECURITY_TOKEN",
    }
    missing = [secret_name for field, secret_name in required.items() if not config.get(field)]
    if missing:
        names = ", ".join(missing)
        raise MissingRequiredSecretError(
            f"Missing required Salesforce credential(s): {names}. "
            "Set them in Streamlit secrets/environment variables or enter them "
            "in the Salesforce connection form."
        )


def _initialize_connector(system_name, prefix):
    config = build_connector_config(prefix)
    if system_name == "Salesforce":
        _require_salesforce_credentials(config)

    try:
        connector = ConnectorFactory.create(normalize_system(system_name), config)
        connector.test_connection()
        models = connector.discover_models()
        return connector, models
    except MissingRequiredSecretError:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"Could not connect to the {system_name} {prefix}. Check its URL, "
            f"credentials, network access, and required permissions. Details: {exc}"
        ) from exc


def initialize_connections():
    """Initialize per-session Groq and ERP clients, without shared caching."""
    api_key = st.session_state.get("groq_api_key") or get_secret("GROQ_API_KEY")
    if not api_key:
        raise MissingRequiredSecretError(
            "Missing required secret: GROQ_API_KEY. Add it to Streamlit secrets "
            "or environment variables, or enter it in the AI section of the sidebar."
        )

    try:
        llm_client = LLMClient(api_key)
    except Exception as exc:
        raise RuntimeError(
            "Could not initialize Groq. Check GROQ_API_KEY and network access. "
            f"Details: {exc}"
        ) from exc

    target_system = st.session_state.target_system
    target_connector, target_models = _initialize_connector(target_system, "target")

    source_connector = None
    source_models = None
    if not is_csv_source():
        source_system = st.session_state.source_system
        source_connector, source_models = _initialize_connector(source_system, "source")

    # Keep clients and connector schemas in this browser session only. They may
    # contain user credentials or private organization metadata.
    st.session_state.llm_client = llm_client
    st.session_state.target_connector = target_connector
    st.session_state.target_models = target_models
    st.session_state.source_connector = source_connector
    st.session_state.source_models = source_models
    reset_source_state()


# ── Source initialization ──────────────────────────────────────────────────

def initialize_csv_source(uploaded=None, source_path=None):
    """Initialize a CSV/XLSX connector from memory or a bundled sample path."""
    if uploaded is not None:
        suffix = Path(uploaded.name).suffix.lower()
        content = BytesIO(uploaded.getvalue())
        try:
            if suffix == ".csv":
                dataframe = pd.read_csv(content)
            elif suffix == ".xlsx":
                dataframe = pd.read_excel(content)
            else:
                raise ValueError("Unsupported file format. Use CSV or XLSX.")
        except Exception as exc:
            raise ValueError(f"Could not read the uploaded source file: {exc}") from exc
    elif source_path is not None:
        dataframe = load_source_file(str(source_path))
    else:
        raise ValueError("Upload a CSV/XLSX file or choose the bundled sample CSV.")

    source_connector = ConnectorFactory.create("file", {"dataframe": dataframe})
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
    try:
        schema = _to_dict(connector.fetch_schema(source_entity))
        samples = connector.sample_records(source_entity, limit=100)
    except Exception as exc:
        raise RuntimeError(
            f"Could not load {source_entity} from {st.session_state.source_system}. "
            f"Check the connection and access permissions. Details: {exc}"
        ) from exc
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

    try:
        prediction = predict_target_entity(
            st.session_state.llm_client,
            source_schema,
            clean_target_models,
            source_system=st.session_state.source_system,
            target_system=st.session_state.target_system,
        )
    except Exception as exc:
        raise RuntimeError(
            "Groq could not predict a target entity. Check GROQ_API_KEY and "
            f"network access. Details: {exc}"
        ) from exc

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

    try:
        raw_target_schema = _to_dict(
            st.session_state.target_connector.fetch_schema(st.session_state.target_entity)
        )
    except Exception as exc:
        raise RuntimeError(
            f"Could not load target entity {st.session_state.target_entity} from "
            f"{st.session_state.target_system}. Check the connection and access "
            f"permissions. Details: {exc}"
        ) from exc

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

    try:
        compatibility = analyze_compatibility(
            st.session_state.llm_client,
            source_schema,
            target_schema,
        )
    except Exception as exc:
        raise RuntimeError(
            "Compatibility analysis failed. Check that Groq and the connected "
            f"data source are available. Details: {exc}"
        ) from exc

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

    report_bytes = generate_report(
        source_schema,
        prediction,
        st.session_state.target_schema,
        st.session_state.compatibility,
    )

    st.session_state.report_bytes = report_bytes