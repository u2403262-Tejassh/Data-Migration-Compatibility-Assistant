import hmac
from pathlib import Path

import pandas as pd
import streamlit as st

from compatibility_analyzer.config import get_secret
from compatibility_analyzer.app.state_manager import (
    initialize_state,
    is_csv_source,
    is_same_erp,
    reset_all_runtime_state,
)
from compatibility_analyzer.app.workflow_controller import (
    MissingRequiredSecretError,
    initialize_connections,
    initialize_csv_source,
    prepare_erp_source,
    predict_target,
    confirm_target,
    run_compatibility_analysis,
    generate_pdf_report,
    update_selected_source_fields,
)
from compatibility_analyzer.app.ui_components import (
    render_app_styles,
    render_hero,
    render_sidebar,
    render_entity_selector,
    render_source_sample,
)


st.set_page_config(
    page_title="ERP Migration Compatibility Analyzer",
    page_icon="sync",
    layout="wide",
)

_app_password = get_secret("APP_PASSWORD")
if _app_password:
    st.caption("This deployment is password protected.")
    submitted_password = st.text_input(
        "Application password",
        type="password",
        key="_app_password_input",
    )
    if not hmac.compare_digest(
        str(submitted_password or "").encode("utf-8"),
        str(_app_password).encode("utf-8"),
    ):
        st.error("Enter the configured APP_PASSWORD to continue.")
        st.stop()



def _run_compatibility_analysis_safely():
    try:
        run_compatibility_analysis()
    except Exception as exc:
        st.error(f"Compatibility analysis failed. Check Groq and data-source connectivity. Details: {exc}")
        st.stop()


SAMPLE_SOURCE_PATH = Path(__file__).resolve().parent.parent / "sample_data" / "source.csv"

render_app_styles()
initialize_state()
render_hero()
render_sidebar()


# ----------------------------
# Infrastructure initialization
# ----------------------------

if st.sidebar.button(
    "Initialize Connections",
    key="initialize_connections_btn",
):
    try:
        initialize_connections()
        st.success("Connections initialized successfully.")
    except MissingRequiredSecretError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:
        st.error(f"Connection setup failed. Check the configured credentials and network access. Details: {exc}")

if st.sidebar.button(
    "Clear All Entities",
    key="clear_all_entities_btn",
    help="Resets source/target entity selection, schemas, analysis, and report. Keeps your connection credentials.",
):
    reset_all_runtime_state()
    st.rerun()


# ----------------------------
# CSV workflow
# ----------------------------

if is_csv_source():
    if st.session_state.target_connector:
        uploaded = st.file_uploader(
            "Upload Source Dataset (CSV/XLSX)",
            type=["csv", "xlsx"],
            key="csv_upload",
        )

        use_sample = st.checkbox(
            "Use bundled sample dataset",
            key="use_sample_csv",
            help="Loads sample_data/source.csv from the repository using a path relative to this app file.",
        )

        if uploaded or use_sample:
            if not st.session_state.source_connector:

                try:

                    initialize_csv_source(
                        uploaded=uploaded,
                        source_path=None if uploaded else SAMPLE_SOURCE_PATH,
                    )

                    predict_target()

                    st.rerun()

                except Exception as exc:

                    st.error(str(exc))

            if st.session_state.source_schema:
                st.subheader("Target Entity Selection")


                if st.session_state.prediction:
                    predicted = (
                            st.session_state.prediction or {}
                    ).get("predicted_model")

                    if not predicted:
                        st.warning(
                            "Could not determine target entity."
                        )
                        st.stop()


                    st.info(
                        f"Predicted Target Entity: {predicted}"
                    )

                    c1, c2 = st.columns(2)

                    with c1:

                        if st.button(
                                "Accept Prediction",
                                key="accept_prediction_btn",
                        ):
                            confirm_target(predicted)

                            _run_compatibility_analysis_safely()

                            st.rerun()
                    with c2:

                        manual_target = render_entity_selector(
                            "Choose Different Target",
                            st.session_state.target_models,
                            "csv_manual_target",
                        )

                        if st.button(
                                "Use Selected Target",
                                key="csv_manual_target_btn",
                        ):
                            confirm_target(manual_target)

                            _run_compatibility_analysis_safely()

                            st.rerun()


# ----------------------------
# ERP workflow
# ----------------------------

else:
    if (
        st.session_state.source_connector
        and st.session_state.target_connector
    ):
        st.subheader("1. Select Source Entity")

        source_entity = render_entity_selector(
            "Source Entity",
            st.session_state.source_models,
            "erp_source_entity",
        )

        if (
                source_entity
                and source_entity != st.session_state.get("source_entity")
        ):
            try:
                prepare_erp_source(source_entity)

                if not is_same_erp():
                    predict_target()

                st.rerun()

            except Exception as exc:
                st.error(str(exc))


        if st.session_state.source_field_analysis:
            st.subheader(
                "Source Data Preview"
            )

            render_source_sample(
                st.session_state.source_samples
            )

            st.subheader("Target Entity")

            if is_same_erp():
                st.info(
                    "Same-system migration detected. "
                    "Select a target entity — defaults to the source entity."
                )
                same_erp_target = render_entity_selector(
                    "Target Entity",
                    st.session_state.target_models,
                    "same_erp_target_selector",
                )
                # Pre-select source_entity on first render
                if st.session_state.get("same_erp_target_selector") is None:
                    st.session_state["same_erp_target_selector"] = source_entity

                if st.button("Analyze Compatibility", key="same_erp_analyze_btn"):
                    try:
                        confirm_target(same_erp_target)
                        _run_compatibility_analysis_safely()
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            else:

                if (
                        st.session_state.prediction
                        and not st.session_state.target_confirmed
                ):

                    prediction = st.session_state.prediction

                    if prediction is None:
                        st.stop()

                    predicted = prediction.get(
                        "predicted_model"
                    )

                    if not predicted:
                        st.warning(
                            "Could not determine target entity."
                        )
                        st.stop()

                    st.info(
                        f"Predicted Target Entity: {predicted}"
                    )

                    col1, col2 = st.columns(2)

                    with col1:

                        if st.button(
                                "Accept Prediction",
                                key="erp_accept_prediction",
                        ):
                            confirm_target(predicted)

                            _run_compatibility_analysis_safely()

                            st.rerun()

                    with col2:

                        manual_target = render_entity_selector(
                            "Choose Different Target",
                            st.session_state.target_models,
                            "erp_manual_target",
                        )

                        if st.button(
                                "Use Selected Target",
                                key="erp_manual_target_btn",
                        ):
                            confirm_target(manual_target)

                            _run_compatibility_analysis_safely()

                            st.rerun()

# ----------------------------
# Compatibility analysis
# ----------------------------

if st.session_state.compatibility:
    st.success(
        f"Confirmed target entity: "
        f"{st.session_state.target_entity}"
    )


# ----------------------------
# Results
# ----------------------------



    compatibility = st.session_state.compatibility

    # ==================================
    # KPI HEADER
    # ==================================

    mapping_count = len(
        compatibility.get(
            "mapping_suggestions",
            []
        )
    )

    unmapped_count = compatibility.get(
        "unmapped_source_count",
        0,
    )

    critical_count = len([
        issue
        for issue in compatibility.get(
            "compatibility_issues",
            []
        )
        if issue.get("severity") == "high"
    ])

    coverage_score = (
                             mapping_count
                             / max(
                         1,
                         mapping_count + unmapped_count
                     )
                     ) * 100

    medium_count = len([
        issue
        for issue in compatibility.get(
            "compatibility_issues",
            []
        )
        if issue.get("severity") == "medium"
    ])

    low_count = len([
        issue
        for issue in compatibility.get(
            "compatibility_issues",
            []
        )
        if issue.get("severity") == "low"
    ])

    compatibility_score = round(
        compatibility.get(
            "compatibility_score",
            0,
        )
    )

    predicted_model = getattr(
        st.session_state,
        "target_entity",
        "Unknown",
    )

    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        st.metric(
            "Compatibility Score",
            f"{compatibility_score}%"
        )

    with c2:
        st.metric(
            "Mapped Fields",
            mapping_count
        )

    with c3:
        st.metric(
            "Unmapped Fields",
            unmapped_count
        )

    with c4:
        st.metric(
            "Critical Issues",
            critical_count
        )

    with c5:
        st.metric(
            "Target Model",
            predicted_model
        )

    st.divider()

    # ==================================
    # TABS
    # ==================================

    (
        overview_tab,
        mappings_tab,
        issues_tab,
        schema_tab,
        report_tab,
    ) = st.tabs(
        [
            "Overview",
            "Mappings",
            "Issues",
            "Schema",
            "Report",
        ]
    )

    # ==================================
    # OVERVIEW
    # ==================================

    with overview_tab:

        st.subheader(
            "Executive Summary"
        )

        st.info(
            compatibility.get(
                "overall_assessment",
                "No assessment available."
            )
        )

        source_samples = getattr(
            st.session_state,
            "source_samples",
            None,
        )

        if source_samples:

            st.subheader(
                "Source Data Preview"
            )

            preview_df = (
                pd.DataFrame(source_samples)
                .head(10)
                .copy()
            )

            for col in preview_df.columns:
                preview_df[col] = preview_df[col].astype(str)

            st.dataframe(
                preview_df,
                use_container_width=True,
                height=350,
            )

    # ==================================
    # MAPPINGS
    # ==================================

    with mappings_tab:

        st.subheader(
            "Field Mapping Suggestions"
        )

        mappings = compatibility.get(
            "mapping_suggestions",
            []
        )

        if mappings:

            if mappings:

                mapping_df = pd.DataFrame(
                    mappings
                )

                st.dataframe(
                    mapping_df,
                    use_container_width=True,
                    hide_index=True,
                )

                # Show "Apply" button for ERP sources only.
                # Filters the source entity down to only the fields that have a
                # suggested mapping, then re-runs analysis.
                if not is_csv_source():
                    if st.button(
                            "Apply Suggested Fields to ERP Source",
                            key="apply_suggested_fields_btn",
                            help=(
                                    "Narrows the source entity to only the fields that have "
                                    "a suggested mapping, then re-runs compatibility analysis."
                            ),
                    ):
                        suggested = [m["source_field"] for m in mappings]
                        try:
                            update_selected_source_fields(suggested)
                            _run_compatibility_analysis_safely()
                            st.success(
                                f"Re-ran analysis with {len(suggested)} suggested field(s)."
                            )
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

        unmapped = compatibility.get(
            "unmapped_source_fields",
            []
        )

        if unmapped:

            st.subheader(
                "Unmapped Source Fields"
            )

            unmapped_df = pd.DataFrame(
                unmapped
            )

            st.dataframe(
                unmapped_df,
                use_container_width=True,
                hide_index=True,
            )

    # ==================================
    # ISSUES
    # ==================================

    with issues_tab:

        st.subheader(
            "Compatibility Issues"
        )

        issues = compatibility.get(
            "compatibility_issues",
            []
        )

        if not issues:
            st.success(
                "No compatibility issues detected."
            )

        for issue in issues:

            severity = (
                issue.get(
                    "severity",
                    "low",
                )
                .upper()
            )

            issue_text = issue.get(
                "issue",
                ""
            )

            recommendation = issue.get(
                "recommendation",
                ""
            )

            content = f"""
**{severity}**

{issue_text}

*{recommendation}*
"""

            if severity == "HIGH":

                st.error(content)

            elif severity == "MEDIUM":

                st.warning(content)

            else:

                st.info(content)

    # ==================================
    # SCHEMA
    # ==================================

    with schema_tab:

        st.subheader(
            "Target Schema"
        )

        target_schema = getattr(
            st.session_state,
            "target_schema",
            None,
        )

        if target_schema:

            rows = []

            for (
                field_name,
                metadata,
            ) in target_schema[
                "fields"
            ].items():

                rows.append(
                    {
                        "Field":
                            field_name,
                        "Type":
                            metadata.get(
                                "type"
                            ),
                        "Required":
                            metadata.get(
                                "required"
                            ),
                        "Relation":
                            metadata.get(
                                "relation"
                            ),
                    }
                )

            schema_df = pd.DataFrame(
                rows
            )

            st.dataframe(
                schema_df,
                use_container_width=True,
                height=500,
                hide_index=True,
            )

    # ==================================
    # REPORT
    # ==================================

    with report_tab:

        st.subheader(
            "Migration Report"
        )

        recommendations = (
            compatibility.get(
                "export_recommendations",
                []
            )
        )

        if recommendations:

            st.subheader(
                "Recommendations"
            )

            for rec in recommendations:

                st.markdown(
                    f"• {rec}"
                )

        st.divider()

        if st.button(
            "Generate PDF Report",
            key="generate_report_btn",
        ):

            try:

                generate_pdf_report()

                st.rerun()

            except Exception as exc:

                st.error(
                    str(exc)
                )

        report_bytes = st.session_state.report_bytes
        if report_bytes:
            st.download_button(
                label="Download Report",
                data=report_bytes,
                file_name="migration_report.pdf",
                mime="application/pdf",
                key="download_report_btn",
            )
