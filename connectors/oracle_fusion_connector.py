import logging
import requests

from compatibility_analyzer.connectors.base_connector import ERPConnector
from compatibility_analyzer.models import EntitySchema, FieldSchema

logger = logging.getLogger(__name__)

ORACLE_API_VERSION = "11.13.18.05"

ORACLE_TYPE_MAP = {
    "string": "char",
    "varchar": "char",
    "clob": "text",
    "integer": "integer",
    "number": "float",
    "decimal": "float",
    "boolean": "boolean",
    "date": "date",
    "datetime": "datetime",
    "timestamp": "datetime",
    "object": "many2one",
    "reference": "many2one",
    "array": "one2many",
}


class OracleFusionConnector(ERPConnector):

    def __init__(self, config):
        super().__init__(config)

        self.base_url = (
            config.get("url")
            or config.get("base_url")
            or ""
        ).rstrip("/")

        self.username = config.get("username")
        self.password = config.get("password")

        self.session = requests.Session()

    # ----------------------------------------------------------
    # Authentication
    # ----------------------------------------------------------

    def authenticate(self):

        if not self.base_url:
            raise ValueError(
                "Oracle Fusion URL is required"
            )

        self.session.auth = (
            self.username,
            self.password,
        )

        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "REST-Framework-Version": "8",
        })

        return self.session

    # ----------------------------------------------------------
    # Connection Test
    # ----------------------------------------------------------

    def test_connection(self):

        self.authenticate()

        response = self.session.get(
            self.base_url +
            f"/fscmRestApi/resources/"
            f"{ORACLE_API_VERSION}/"
            f"invoices/describe",
            timeout=30,
        )

        if response.status_code != 200:
            raise ValueError(
                f"Oracle connection failed "
                f"({response.status_code})"
            )

        try:
            payload = response.json()
        except Exception:
            raise ValueError(
                "Oracle endpoint returned "
                "non-JSON content"
            )

        if "Resources" not in payload:
            raise ValueError(
                "Unexpected Oracle response"
            )

        return {
            "status": "connected"
        }

    # ----------------------------------------------------------
    # Entity Discovery (temporary static catalog)
    # ----------------------------------------------------------

    def discover_models(self):

        self.test_connection()

        return [

            {
                "model": "invoices",
                "name": "Invoices",
                "module": "fscm",
            },

            {
                "model": "suppliers",
                "name": "Suppliers",
                "module": "fscm",
            },

            {
                "model": "customers",
                "name": "Customers",
                "module": "fscm",
            },

            {
                "model": "accounts",
                "name": "Accounts",
                "module": "crm",
            },

            {
                "model": "contacts",
                "name": "Contacts",
                "module": "crm",
            },

            {
                "model": "workers",
                "name": "Workers",
                "module": "hcm",
            },

            {
                "model": "departments",
                "name": "Departments",
                "module": "hcm",
            },
        ]

    # ----------------------------------------------------------
    # Schema Discovery
    # ----------------------------------------------------------

    def fetch_schema(self, model_name):

        self.authenticate()

        module_map = {
            "invoices": "fscm",
            "suppliers": "fscm",
            "customers": "fscm",
            "accounts": "crm",
            "contacts": "crm",
            "workers": "hcm",
            "departments": "hcm",
        }

        module = module_map.get(
            model_name.lower()
        )

        if not module:
            raise ValueError(
                f"Unknown Oracle entity: "
                f"{model_name}"
            )

        endpoint_map = {
            "fscm": "fscmRestApi",
            "crm": "crmRestApi",
            "hcm": "hcmRestApi",
        }

        response = self.session.get(
            self.base_url
            + f"/{endpoint_map[module]}"
              f"/resources/"
              f"{ORACLE_API_VERSION}/"
              f"{model_name}/describe",
            timeout=30,
        )

        if not response.ok:
            raise ValueError(
                f"Unable to fetch schema for "
                f"{model_name}"
            )

        payload = response.json()

        resource = (
            payload.get("Resources", {})
            .get(model_name.lower())
        )

        if not resource:

            resource = next(
                iter(
                    payload.get(
                        "Resources",
                        {},
                    ).values()
                ),
                {},
            )

        fields = {}

        for attr in resource.get(
            "attributes",
            [],
        ):

            field_name = attr.get("name")

            if not field_name:
                continue

            native_type = (
                attr.get("type")
                or "string"
            )

            normalized_type = ORACLE_TYPE_MAP.get(
                native_type.lower(),
                "char",
            )

            fields[field_name] = FieldSchema(
                name=field_name,
                label=attr.get(
                    "title",
                    field_name,
                ),
                field_type=normalized_type,
                required=attr.get(
                    "mandatory",
                    False,
                ),
                readonly=not attr.get(
                    "updatable",
                    True,
                ),
                source_dtype=native_type,
            )
        schema = EntitySchema(
            system="oracle_fusion",
            entity=model_name,
            label=model_name,
            fields=fields,
            metadata={
                "module": module,
            },
        )

        print("\n=== ORACLE SCHEMA INFO ===")
        print("ENTITY:", schema.entity)
        print("SYSTEM:", schema.system)

        return schema

    # ----------------------------------------------------------
    # Sample Records
    # ----------------------------------------------------------

    def sample_records(
        self,
        model_name,
        limit=20,
    ):

        self.authenticate()

        module_map = {
            "invoices": "fscm",
            "suppliers": "fscm",
            "customers": "fscm",
            "accounts": "crm",
            "contacts": "crm",
            "workers": "hcm",
            "departments": "hcm",
        }

        module = module_map.get(
            model_name.lower()
        )

        if not module:
            return []

        endpoint_map = {
            "fscm": "fscmRestApi",
            "crm": "crmRestApi",
            "hcm": "hcmRestApi",
        }

        response = self.session.get(
            self.base_url
            + f"/{endpoint_map[module]}"
              f"/resources/"
              f"{ORACLE_API_VERSION}/"
              f"{model_name}",
            params={
                "limit": limit,
                "onlyData": "true",
            },
            timeout=30,
        )

        if not response.ok:
            return []

        payload = response.json()

        return payload.get(
            "items",
            [],
        )