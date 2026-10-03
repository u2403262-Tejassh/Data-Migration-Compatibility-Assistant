"""Secret lookup helpers and session-state defaults.

Credentials are sourced from Streamlit secrets or environment variables and
kept in the user's Streamlit session. This module intentionally does not read
or write credential files.
"""

from compatibility_analyzer.config import get_secret as _get_secret


def get_secret(key, default=None):
    """Read a setting from Streamlit secrets, the environment, or a default."""
    return _get_secret(key, default)


def load_credentials() -> dict:
    """Return configured Groq/Salesforce credentials for session initialization."""
    credentials = {}
    secret_keys = {
        "groq_api_key": "GROQ_API_KEY",
    }

    for prefix in ("source", "target"):
        secret_keys.update({
            f"{prefix}_salesforce_username": "SALESFORCE_USERNAME",
            f"{prefix}_salesforce_password": "SALESFORCE_PASSWORD",
            f"{prefix}_salesforce_token": "SALESFORCE_SECURITY_TOKEN",
            f"{prefix}_salesforce_domain": "SALESFORCE_DOMAIN",
        })

    for session_key, secret_key in secret_keys.items():
        default = "login" if secret_key == "SALESFORCE_DOMAIN" else None
        value = get_secret(secret_key, default)
        if value not in (None, ""):
            credentials[session_key] = value

    return credentials
