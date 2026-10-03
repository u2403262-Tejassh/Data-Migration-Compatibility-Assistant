"""Application configuration and secret lookup helpers."""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv


# Load local development values without overriding environment-provided values.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


def get_secret(key, default=None):
    """Read a setting from Streamlit secrets, the environment, or a default."""
    try:
        value = st.secrets.get(key)
    except Exception:
        # Streamlit raises when no secrets file/configuration is available.
        value = None

    if value not in (None, ""):
        return value

    return os.getenv(key, default)


GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

# Profiling configuration.
MAX_SAMPLE_VALUES = 3

# Filter noisy framework/internal models.
EXCLUDED_MODEL_PREFIXES = [
    "ir.",
    "mail.",
    "base.",
    "web.",
    "bus.",
    "digest.",
    "utm.",
    "iap.",
    "calendar.",
    "portal.",
]

# Optional allowlist keywords for business relevance.
BUSINESS_MODEL_HINTS = [
    "partner",
    "employee",
    "account",
    "sale",
    "purchase",
    "product",
    "stock",
    "crm",
    "project",
    "helpdesk",
    "fleet",
    "mrp",
]
