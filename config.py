
GROQ_API_KEY = "GROQ_API_KEY"
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

# ==========================================
# ODOO CONFIG
# ==========================================

ODOO_URL = "http://localhost:8019"
ODOO_DB = "odoo_dev"
ODOO_USERNAME = "admin"
ODOO_PASSWORD = "admin"

# ==========================================
# PROFILING CONFIG
# ==========================================

MAX_SAMPLE_VALUES = 3
OUTPUT_DIR = "output"

# Filter noisy framework/internal models
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

# Optional allowlist keywords for business relevance
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