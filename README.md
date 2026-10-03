# Data Migration Compatibility Assistant

The Data Migration Compatibility Assistant is a Streamlit application for comparing source and target schemas, suggesting entity and field mappings, identifying compatibility issues, and generating a downloadable PDF assessment report.

## Features

- Connect to Salesforce, Odoo, and Oracle Fusion, or analyze an uploaded CSV/XLSX dataset.
- Inspect source and target schemas and sample data.
- Run deterministic compatibility analysis with Groq-assisted mapping and recommendations.
- Generate and download a PDF migration assessment report.
- Use the bundled `sample_data/source.csv` example when a target connection has been initialized.

## Project layout

```text
.
├── streamlit_app.py                 # Root Streamlit entry point
├── compatibility_analyzer/         # Import-path shim for the flat source layout
│   └── __init__.py
├── app/
│   ├── migration_analyzer_streamlit_app.py  # Real Streamlit application
│   ├── workflow_controller.py
│   ├── state_manager.py
│   └── ui_components.py
├── connectors/                      # File, Odoo, Oracle, and Salesforce connectors
├── migration_catalog/               # Static migration catalogs
├── matching/ planning/ profiling/ reasoning/ reporting/ models/ utils/
├── sample_data/source.csv
└── output/.gitkeep
```

## Local installation and run

Use Python 3.11 or 3.12:

```bash
python -m venv venv
# Linux/macOS
source venv/bin/activate
# Windows PowerShell: venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
streamlit run streamlit_app.py
```

Edit `.env` with your local Groq and Salesforce values. `python-dotenv` loads it for local development. Alternatively, configure Streamlit secrets. Odoo and Oracle connection details can be entered in the sidebar. Credentials entered in the UI are held in Streamlit session state only; the application does not save them to a credentials file.

`APP_PASSWORD` is optional. When configured, the app displays a password gate before showing the analysis UI.

## Deploy to Streamlit Community Cloud

1. Push this repository to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io/) and choose **New app**.
3. Select this repository and the branch to deploy.
4. Set **Main file path** to `streamlit_app.py`.
5. In **Advanced settings**, choose Python **3.11** or **3.12** and paste your values into the Secrets editor in TOML format. For example:

   ```toml
   GROQ_API_KEY = "your_api_key"
   SALESFORCE_USERNAME = "your_username"
   SALESFORCE_PASSWORD = "your_password"
   SALESFORCE_SECURITY_TOKEN = "your_security_token"
   SALESFORCE_DOMAIN = "login"
   APP_PASSWORD = "your_app_password"
   ```

   `APP_PASSWORD` is optional; omit it to disable the password gate. Never commit `.env` or `.streamlit/secrets.toml`.
6. Click **Deploy**.

Streamlit Community Cloud uses an ephemeral filesystem. The app does not rely on files persisting between runs: uploaded datasets are read in memory, and generated PDF reports are built in memory and downloaded through the UI. The `output/` directory is retained only as an empty placeholder; reports are not written there.

## Connections and network access

The hosted app must be able to reach the configured Groq, Salesforce, Odoo, or Oracle endpoints from Streamlit Community Cloud. A private-network-only ERP endpoint, a firewall-restricted host, or a `localhost` URL on your own computer will not be reachable from the cloud app. Enter an endpoint that the deployed app can access and use appropriately restricted credentials.

Salesforce and Groq values may be supplied as Streamlit secrets/environment variables or entered in the sidebar. Odoo and Oracle credentials are entered in the sidebar. Missing required values are reported in the UI rather than as an application traceback.

## Reports

The current app generates a PDF compatibility assessment. It does not currently generate separate TDD, FSD, or UCD documents. Downloaded reports are not persisted on the Streamlit server.
