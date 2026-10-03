"""
utils/credentials.py

Saves and loads connection credentials to/from .credentials.json
in the working directory. Passwords are stored in plain text —
this is intended for local development use only.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CREDENTIALS_FILE = Path(".credentials.json")

# Every session-state key that holds a credential value.
# These map 1:1 to the keys used in ui_components.py form fields.
CREDENTIAL_KEYS = [
    # Systems
    "source_system",
    "target_system",
    # Odoo — source
    "source_odoo_url",
    "source_odoo_db",
    "source_odoo_username",
    "source_odoo_password",
    "source_odoo_auth_mode",
    # Odoo — target
    "target_odoo_url",
    "target_odoo_db",
    "target_odoo_username",
    "target_odoo_password",
    "target_odoo_auth_mode",
    # Salesforce — source
    "source_salesforce_username",
    "source_salesforce_password",
    "source_salesforce_token",
    "source_salesforce_domain",
    "source_salesforce_custom_domain",
    # Salesforce — target
    "target_salesforce_username",
    "target_salesforce_password",
    "target_salesforce_token",
    "target_salesforce_domain",
    "target_salesforce_custom_domain",
    # Oracle — source
    "source_oracle_url",
    "source_oracle_username",
    "source_oracle_password",
    # Oracle — target
    "target_oracle_url",
    "target_oracle_username",
    "target_oracle_password",
    # AI
    "groq_api_key",
]


def load_credentials() -> dict:
    """Return saved credentials dict, or {} if file does not exist."""
    if not CREDENTIALS_FILE.exists():
        return {}
    try:
        with open(CREDENTIALS_FILE) as f:
            data = json.load(f)
        logger.debug("Credentials loaded from %s", CREDENTIALS_FILE)
        return data
    except Exception as exc:
        logger.warning("Could not load credentials: %s", exc)
        return {}


def save_credentials(session_state) -> None:
    """Write non-empty credential keys from session_state to .credentials.json."""
    data = {}
    for key in CREDENTIAL_KEYS:
        val = session_state.get(key)
        if val not in (None, "", [], False):
            data[key] = val
    try:
        with open(CREDENTIALS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Credentials saved to %s", CREDENTIALS_FILE)
    except Exception as exc:
        logger.error("Could not save credentials: %s", exc)
        raise


def clear_credentials() -> None:
    """Delete the credentials file."""
    if CREDENTIALS_FILE.exists():
        CREDENTIALS_FILE.unlink()
        logger.info("Credentials file deleted.")