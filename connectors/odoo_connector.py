import xmlrpc.client
from compatibility_analyzer.models import (
    EntitySchema,
    FieldSchema,
)
from compatibility_analyzer.connectors.base_connector import ERPConnector
DEFAULT_MODEL_ALLOWLIST = None
TECHNICAL_PREFIXES = (
    "ir.",
    "mail.",
    "base.",
    "web.",
    "bus.",
    "digest.",
    "utm.",
    "iap.",
    "portal.",
)

class OdooConnector(ERPConnector):
    def __init__(self, config: dict):
        super().__init__(config)

        if not all([
            config.get("url"),
            config.get("db"),
            config.get("username"),
            config.get("password"),
        ]):
            raise ValueError("Missing Odoo connection parameters")

        self.url = config["url"].rstrip("/")
        self.db = config["db"]
        self.username = config["username"]
        self.password = config["password"]
        self.model_allowlist = config.get("model_allowlist", DEFAULT_MODEL_ALLOWLIST)

        self.uid = None

    def _common_proxy(self):
        return xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/common",
            allow_none=True,
        )

    def _models_proxy(self):
        return xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/object",
            allow_none=True,
        )

    def authenticate(self):

        if self.uid:
            return self.uid

        self.uid = self._common_proxy().authenticate(
            self.db,
            self.username,
            self.password,
            {},
        )

        if not self.uid:
            raise ValueError(
                "Odoo authentication failed"
            )

        return self.uid

    def execute(
            self,
            model,
            method,
            args=None,
            kwargs=None,
    ):

        self.authenticate()

        try:

            return (
                self._models_proxy()
                .execute_kw(
                    self.db,
                    self.uid,
                    self.password,
                    model,
                    method,
                    args or [],
                    kwargs or {},
                )
            )

        except Exception:

            self.uid = None

            self.authenticate()

            return (
                self._models_proxy()
                .execute_kw(
                    self.db,
                    self.uid,
                    self.password,
                    model,
                    method,
                    args or [],
                    kwargs or {},
                )
            )
    def search_read(self, model, domain=None, fields=None, limit=None):
        kwargs = {}

        if fields:
            kwargs["fields"] = fields

        if limit:
            kwargs["limit"] = limit

        return self.execute(
            model,
            "search_read",
            [domain or []],
            kwargs,
        )

    def test_connection(self):

        version = (
            self._common_proxy()
            .version()
        )

        self.authenticate()

        return {
            "status": "connected",
            "server_version": version[
                "server_version"
            ],
        }

    def discover_models(self):

        models = self.search_read(
            "ir.model",
            fields=[
                "model",
                "name",
                "state",
            ],
        )

        filtered = []

        for model in models:

            model_name = model["model"]

            if model_name.startswith(
                    TECHNICAL_PREFIXES
            ):
                continue

            filtered.append({
                "model": model_name,
                "name": model["name"],
            })

        return sorted(
            filtered,
            key=lambda x: x["name"].lower(),
        )
    
    def _fetch_runtime_fields(self, model_name):
        return self.execute(
            model_name,
            "fields_get",
            [],
            {
                "attributes": [
                    "string",
                    "type",
                    "required",
                    "readonly",
                    "relation",
                    "help",
                    "selection",
                ]
            },
        )

    def _fetch_metadata_fields(self, model_name):
        return self.search_read(
            "ir.model.fields",
            domain=[("model", "=", model_name)],
            fields=[
                "name",
                "field_description",
                "ttype",
                "required",
                "readonly",
                "relation",
                "selection",
                "size",
                "translate",
                "state",
            ],
        )

    @staticmethod
    def _normalize_schema(runtime_fields, metadata_fields):
        metadata_lookup = {
            field["name"]: field
            for field in metadata_fields
        }

        normalized_fields = {}

        for name, runtime in runtime_fields.items():
            metadata = metadata_lookup.get(name, {})
            normalized_fields[name] = {
                "label": runtime.get("string"),
                "type": runtime.get("type"),
                "required": runtime.get("required"),
                "readonly": runtime.get("readonly"),
                "relation": runtime.get("relation"),
                "help": runtime.get("help"),
                "state": metadata.get("state"),
                "size": metadata.get("size"),
                "translate": metadata.get("translate"),
                "selection": runtime.get("selection") or metadata.get("selection"),
            }

        return normalized_fields

    def fetch_schema(self, model_name):

        runtime_fields = self._fetch_runtime_fields(
            model_name
        )

        metadata_fields = self._fetch_metadata_fields(
            model_name
        )

        normalized_fields = self._normalize_schema(
            runtime_fields,
            metadata_fields,
        )

        fields = {}

        for field_name, metadata in (
                normalized_fields.items()
        ):
            fields[field_name] = FieldSchema(
                name=field_name,
                label=metadata.get(
                    "label",
                    field_name,
                ),
                field_type=metadata.get(
                    "type",
                    "unknown",
                ),
                required=metadata.get(
                    "required",
                    False,
                ),
                readonly=metadata.get(
                    "readonly",
                    False,
                ),
                relation=metadata.get(
                    "relation",
                ),
                help_text=metadata.get(
                    "help",
                ),
            )

        return EntitySchema(
            system="odoo",
            entity=model_name,
            label=model_name,
            fields=fields,
        )
    
    def sample_records(self, model_name, limit=20):
        return self.search_read(
            model_name,
            limit=limit,
        )

    @property
    def system_name(self):
        return "Odoo"


class OdooClient(OdooConnector):
    def __init__(self, url, db, username, password):
        super().__init__({
            "url": url,
            "db": db,
            "username": username,
            "password": password,
        })
        self.authenticate()
