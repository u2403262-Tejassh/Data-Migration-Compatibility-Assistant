# Data Migration Compatibility Assistant

## Overview

The Data Migration Compatibility Assistant is a Python-based application developed to analyze and assess migration compatibility between enterprise systems and Salesforce.

The application automates schema comparison, entity mapping, compatibility analysis, and report generation, helping teams identify migration risks and make informed decisions before implementation.

## Key Features

* Connect to Salesforce and external source systems
* Extract and analyze schema metadata
* Perform entity and field-level compatibility assessment
* Generate compatibility scores and migration recommendations
* Identify unsupported or mismatched fields
* Produce detailed migration reports
* Generate AI-assisted migration insights
* Interactive web interface built with Streamlit

## Technology Stack

| Component                | Technology        |
| ------------------------ | ----------------- |
| Programming Language     | Python 3.x        |
| Frontend                 | Streamlit         |
| Data Processing          | Pandas, NumPy     |
| Salesforce Integration   | Simple Salesforce |
| AI Integration           | Groq API          |
| Documentation Generation | Python-Docx       |
| Configuration Management | Python-Dotenv     |

## Project Structure

```text
compatibility_analyzer/
├── __init__.py
├── config.py                    # Global settings
├── llm_client.py                # Groq SDK wrapper
├── app/
│   ├── migration_analyzer_streamlit_app.py  # Entry point
│   ├── workflow_controller.py
│   ├── state_manager.py
│   └── ui_components.py
├── connectors/
│   ├── base_connector.py
│   ├── odoo_connector.py
│   ├── salesforce_connector.py
│   ├── oracle_fusion_connector.py
│   ├── file_connector.py
│   └── connector_factory.py
├── migration_catalog/
│   ├── catalog_manager.py
│   └── data/
│       ├── odoo_salesforce.json
│       ├── salesforce_odoo.json
│       ├── oracle_odoo.json
│       ├── oracle_salesforce.json
│       ├── salesforce_oracle.json
│       └── odoo_oracle.json
├── matching/
│   ├── entity_matcher.py
│   └── dataset_matcher.py       # Deprecated shim
├── reasoning/
│   └── compatibility_reasoner.py
├── planning/
│   ├── source_field_analyzer.py
│   ├── target_schema_analyzer.py
│   └── field_classifier.py
├── profiling/
│   └── source_profiler.py
├── reporting/
│   └── report_generator.py
├── models/
│   ├── entity_schema.py
│   └── migration_context.py
├── utils/
│   ├── credentials.py
│   ├── schema_utils.py
│   ├── schema_adapter.py
│   └── context_utils.py
├── sample_data/
│   └── source.csv
└── output/

```

## Installation

### 1. Create a Virtual Environment

```bash
python -m venv venv
```

### 2. Activate the Environment

**Windows**

```bash
venv\Scripts\activate
```

**Linux/macOS**

```bash
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

## Environment Configuration

Create a `.env` file in the project root directory.

Example:

```env
GROQ_API_KEY=your_api_key

SALESFORCE_USERNAME=your_username
SALESFORCE_PASSWORD=your_password
SALESFORCE_SECURITY_TOKEN=your_security_token
SALESFORCE_DOMAIN=login
```

## Running the Application

Start the Streamlit application:

```bash
streamlit run app.py
```

The application will launch locally and open in your default web browser.

## Workflow

1. Configure environment variables.
2. Connect to Salesforce and source systems.
3. Load source and target schemas.
4. Run compatibility analysis.
5. Review compatibility scores and recommendations.
6. Generate migration reports and documentation.

## Generated Documentation

The application can generate the following documents:

* Technical Design Document (TDD)
* Functional Specification Document (FSD)
* Use Case Document (UCD)
* Installation and Deployment Guide
* Source Code and Dependency Documentation

## Assumptions

* Salesforce credentials are valid.
* Required APIs are accessible.
* Source system metadata is available.
* Users have sufficient permissions to access schemas.

## Limitations

* Compatibility recommendations depend on available metadata.
* Complex business logic transformations may require manual validation.
* Large schema analyses may increase processing time.
* AI-generated recommendations should be reviewed before production use.

## Future Enhancements

* Support for additional ERP and CRM systems
* Automated migration script generation
* Advanced schema visualization
* Real-time migration monitoring
* Enhanced AI-assisted mapping recommendations

## 
