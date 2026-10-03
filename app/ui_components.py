import json
import pandas as pd
import streamlit as st


SOURCE_SYSTEMS = ["CSV/XLSX", "Odoo", "Salesforce", "Oracle Fusion"]
TARGET_SYSTEMS = ["Odoo", "Salesforce", "Oracle Fusion"]

_SF_DOMAIN_OPTIONS = ["login", "test"]
_SF_DOMAIN_LABELS = {
    "login": "login  (Production / Developer Edition)",
    "test":  "test   (Sandbox only)",
}


def render_app_styles():
    st.set_page_config(
        page_title="ERP Migration Compatibility Analyzer",
        page_icon="sync",
        layout="wide",
    )
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1rem; max-width: 1500px; }
        .metric-card {
            padding: 1rem; border-radius: 16px;
            border: 1px solid rgba(255,255,255,0.08);
            background: rgba(255,255,255,0.03);
        }
        .high   { border-left: 4px solid #ff4d4d; }
        .medium { border-left: 4px solid #ffc107; }
        .low    { border-left: 4px solid #28a745; }
        .hero {
            padding: 1.25rem; border-radius: 18px;
            background: linear-gradient(135deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02));
            border: 1px solid rgba(255,255,255,0.08); margin-bottom: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero():
    st.markdown(
        """
        <div class="hero">
            <h1>ERP Migration Compatibility Analyzer</h1>
            <p>User-guided migration planning with deterministic compatibility analysis and AI-assisted mapping.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_odoo_form(prefix):
    st.text_input("Odoo URL", value="http://localhost:8019", key=f"{prefix}_odoo_url")
    st.text_input("Database",  key=f"{prefix}_odoo_db")
    st.text_input("Username",  key=f"{prefix}_odoo_username")
    st.radio("Authentication Method", ["Password", "API Key"], key=f"{prefix}_odoo_auth_mode")
    auth_mode = st.session_state.get(f"{prefix}_odoo_auth_mode", "Password")
    st.text_input(
        "Password" if auth_mode == "Password" else "API Key",
        type="password",
        key=f"{prefix}_odoo_password",
    )


def render_salesforce_form(prefix):
    st.text_input("Username", key=f"{prefix}_salesforce_username")
    st.text_input("Password", type="password", key=f"{prefix}_salesforce_password")
    st.text_input(
        "Security Token",
        type="password",
        key=f"{prefix}_salesforce_token",
        help=(
            "Required when connecting from an untrusted IP.\n\n"
            "Reset at: Setup → My Personal Information → Reset My Security Token"
        ),
    )
    st.selectbox(
        "Domain",
        options=_SF_DOMAIN_OPTIONS,
        format_func=lambda d: _SF_DOMAIN_LABELS[d],
        key=f"{prefix}_salesforce_domain",
        help="**login** = Production / Developer Edition.  **test** = Sandbox only.",
    )
    with st.expander("My Domain (optional)", expanded=False):
        st.text_input(
            "Custom Instance URL",
            placeholder="mycompany.my.salesforce.com",
            key=f"{prefix}_salesforce_custom_domain",
        )


def render_oracle_form(prefix):
    st.text_input("Oracle Fusion URL",  key=f"{prefix}_oracle_url")
    st.text_input("Username",           key=f"{prefix}_oracle_username")
    st.text_input("Password", type="password", key=f"{prefix}_oracle_password")
    st.info("Oracle Fusion REST connection. Enter your Oracle Cloud URL and credentials.")


def render_connection_form(prefix, system_name):
    if system_name == "CSV/XLSX":
        return
    if system_name == "Odoo":
        render_odoo_form(prefix)
    elif system_name == "Salesforce":
        render_salesforce_form(prefix)
    elif system_name == "Oracle Fusion":
        render_oracle_form(prefix)


def render_sidebar():
    with st.sidebar:
        st.header("Source")
        st.selectbox("Source System", SOURCE_SYSTEMS, key="source_system")
        render_connection_form("source", st.session_state.source_system)

        st.header("Target")
        st.selectbox("Target System", TARGET_SYSTEMS, key="target_system")
        render_connection_form("target", st.session_state.target_system)

        st.header("AI")
        st.text_input("Groq API Key", type="password", key="groq_api_key")

        # ── Saved Credentials ──────────────────────────────────────────────
        st.divider()
        st.caption("Credentials are stored locally in `.credentials.json`")
        col_save, col_clear = st.columns(2)
        with col_save:
            if st.button("Save Credentials", use_container_width=True, key="save_creds_btn"):
                try:
                    from compatibility_analyzer.utils.credentials import save_credentials
                    save_credentials(st.session_state)
                    st.success("Saved!")
                except Exception as exc:
                    st.error(str(exc))
        with col_clear:
            if st.button("Clear Saved", use_container_width=True, key="clear_creds_btn"):
                try:
                    from compatibility_analyzer.utils.credentials import clear_credentials
                    clear_credentials()
                    st.success("Cleared!")
                except Exception as exc:
                    st.error(str(exc))


def model_options(models):
    model_names = [m["model"] for m in models]
    labels = {m["model"]: m.get("name", m["model"]) for m in models}
    return model_names, labels


def render_entity_selector(label, models, key):
    model_names, labels = model_options(models)
    return st.selectbox(
        label,
        model_names,
        format_func=lambda model: f"{labels[model]} ({model})",
        key=key,
    )


def render_source_field_selector(field_analysis):
    st.subheader("Exportable Source Fields")
    rows = []
    for field_name, metadata in field_analysis.items():
        rows.append({
            "Select":      metadata["selectable"],
            "Field":       field_name,
            "Label":       metadata["label"],
            "Type":        metadata["type"],
            "Populated %": metadata["populated_pct"],
            "Status":      metadata["reason"],
        })
    df = pd.DataFrame(rows)
    edited = st.data_editor(
        df,
        use_container_width=True,
        key="field_selector_editor",
        disabled=["Field", "Label", "Type", "Populated %", "Status"],
    )
    return edited[edited["Select"] == True]["Field"].tolist()


def render_source_sample(samples):
    if not samples:
        return
    with st.expander("Source Sample Data", expanded=False):
        df = pd.DataFrame(samples).head(10).copy()
        for col in df.columns:
            try:
                df[col] = df[col].astype(str)
            except Exception:
                pass
        st.dataframe(df, use_container_width=True, height=350)