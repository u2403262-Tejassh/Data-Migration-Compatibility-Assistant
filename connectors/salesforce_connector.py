import logging

from compatibility_analyzer.config import get_secret
from compatibility_analyzer.connectors.base_connector import ERPConnector
from compatibility_analyzer.models import EntitySchema, FieldSchema

logger = logging.getLogger(__name__)

SALESFORCE_TYPE_MAP = {
    "address":         "text",
    "base64":          "binary",
    "boolean":         "boolean",
    "combobox":        "selection",
    "currency":        "monetary",
    "date":            "date",
    "datetime":        "datetime",
    "double":          "float",
    "email":           "char",
    "encryptedstring": "char",
    "id":              "char",
    "int":             "integer",
    "multipicklist":   "selection",
    "percent":         "float",
    "phone":           "char",
    "picklist":        "selection",
    "reference":       "many2one",
    "string":          "char",
    "textarea":        "text",
    "time":            "char",
    "url":             "char",
}

# ── Auth error guidance ────────────────────────────────────────────────────
_AUTH_HELP = """
Salesforce authentication failed. Common causes:

  1. Wrong Domain
     • Developer Edition and Production orgs → use "login"
     • "test" is ONLY for Sandbox orgs.
     Symptom: INVALID_LOGIN when your password is correct.

  2. Missing or stale Security Token
     • Required when connecting from an IP not on your org's trusted list.
     • Reset at: Setup → My Personal Information → Reset My Security Token
     • A new token is emailed to you; it also resets when you change your password.

  3. My Domain / custom instance
     • If your org has My Domain enabled (e.g. mycompany.my.salesforce.com),
       enter that URL in the "My Domain" field instead of using the Domain dropdown.

  4. Locked account
     • Too many failed attempts locks the account temporarily.
     • Wait a few minutes or reset your password at login.salesforce.com.
"""


def _build_auth_error(original: str, custom_domain: str = None) -> ValueError:
    """Return a ValueError with actionable guidance based on the raw SF error."""
    msg = f"Salesforce authentication failed: {original}\n{_AUTH_HELP}"
    if custom_domain:
        msg += f"\n  Custom domain used: {custom_domain}"
    return ValueError(msg)


class SalesforceConnector(ERPConnector):

    def __init__(self, config: dict):
        super().__init__(config)
        self.sf = None

    # ── Authentication ─────────────────────────────────────────────────────

    def authenticate(self):
        if self.sf is not None:
            return self.sf

        try:
            from simple_salesforce import Salesforce, SalesforceAuthenticationFailed
        except ImportError as exc:
            raise ImportError(
                "Salesforce connector requires simple-salesforce. "
                "Install with: pip install simple-salesforce"
            ) from exc

        # ── Session-based auth (token + instance URL) ──────────────────────
        if self.config.get("session_id") and self.config.get("instance_url"):
            self.sf = Salesforce(
                instance_url=self.config["instance_url"],
                session_id=self.config["session_id"],
            )
            return self.sf

        # ── Username / password auth ───────────────────────────────────────
        credentials = {
            "username": self.config.get("username") or get_secret("SALESFORCE_USERNAME"),
            "password": self.config.get("password") or get_secret("SALESFORCE_PASSWORD"),
            "security_token": (
                self.config.get("security_token")
                or get_secret("SALESFORCE_SECURITY_TOKEN")
            ),
        }
        secret_names = {
            "username": "SALESFORCE_USERNAME",
            "password": "SALESFORCE_PASSWORD",
            "security_token": "SALESFORCE_SECURITY_TOKEN",
        }
        missing = [secret_names[key] for key, value in credentials.items() if not value]
        if missing:
            raise ValueError(
                "Missing required Salesforce credential(s): " + ", ".join(missing)
            )

        kwargs = credentials.copy()

        custom_domain = (self.config.get("custom_domain") or "").strip()

        if custom_domain:
            # My Domain:  instance = "mycompany.my.salesforce.com"
            # simple_salesforce uses this to build the auth endpoint directly.
            kwargs["instance"] = custom_domain
            logger.debug("Salesforce auth via custom domain: %s", custom_domain)
        else:
            # Standard: "login" (Production / Developer Edition) or "test" (Sandbox)
            domain = self.config.get("domain") or get_secret("SALESFORCE_DOMAIN", "login")
            kwargs["domain"] = domain
            logger.debug("Salesforce auth via domain: %s", domain)

        try:
            self.sf = Salesforce(**kwargs)
        except SalesforceAuthenticationFailed as exc:
            raise _build_auth_error(str(exc), custom_domain or None) from exc
        except Exception as exc:
            # Catch network errors, SSL issues, etc. and surface clearly
            raise ValueError(f"Salesforce connection error: {exc}") from exc

        return self.sf

    # ── Connector contract ─────────────────────────────────────────────────

    def test_connection(self) -> dict:
        sf = self.authenticate()
        user_info = sf.query("SELECT Id, Name FROM User LIMIT 1")
        return {
            "status": "connected",
            "user": user_info.get("records", [{}])[0].get("Name"),
        }

    def discover_models(self) -> list:
        sf = self.authenticate()
        objects = sf.describe().get("sobjects", [])
        models = []
        for obj in objects:
            if obj.get("deprecatedAndHidden") or not obj.get("queryable"):
                continue
            models.append({
                "model": obj["name"],
                "name":  obj.get("label") or obj["name"],
            })
        return sorted(models, key=lambda m: m["name"].lower())

    def fetch_schema(self, model_name: str) -> EntitySchema:
        description = self._describe_object(model_name)
        fields = {}
        for sf_field in description.get("fields", []):
            field_name = sf_field["name"]
            salesforce_type = sf_field.get("type") or "string"
            fields[field_name] = FieldSchema(
                name=field_name,
                label=sf_field.get("label") or field_name,
                field_type=SALESFORCE_TYPE_MAP.get(
                    salesforce_type,
                    salesforce_type,
                ),
                required=self._is_required(sf_field),
                readonly=not sf_field.get("createable", False),
                relation=self._relation(sf_field),
                help_text=sf_field.get("inlineHelpText") or None,
                source_dtype=salesforce_type,
            )
        return EntitySchema(
            system="salesforce",
            entity=model_name,
            label=description.get("label") or model_name,
            fields=fields,
        )

    def sample_records(self, model_name: str, limit: int = 20) -> list:
        schema = self.fetch_schema(model_name)
        queryable_fields = [
            name for name, f in schema.fields.items()
            if f.field_type != "binary"
        ][:50]

        if not queryable_fields:
            return []

        query = (
            f"SELECT {', '.join(queryable_fields)} "
            f"FROM {model_name} "
            f"LIMIT {int(limit)}"
        )
        records = self.authenticate().query(query).get("records", [])
        for rec in records:
            rec.pop("attributes", None)
        return records

    # ── Private helpers ────────────────────────────────────────────────────

    def _describe_object(self, model_name: str) -> dict:
        return getattr(self.authenticate(), model_name).describe()

    @staticmethod
    def _is_required(field) -> bool:
        return (
            not field.get("nillable", True)
            and not field.get("defaultedOnCreate", False)
            and not field.get("autoNumber", False)
            and not field.get("calculated", False)
        )

    @staticmethod
    def _relation(field):
        refs = field.get("referenceTo") or []
        return ",".join(refs) if refs else None

    @staticmethod
    def _picklist_values(field):
        values = field.get("picklistValues") or []
        return [
            {"value": v.get("value"), "label": v.get("label"), "active": v.get("active")}
            for v in values
        ] if values else None