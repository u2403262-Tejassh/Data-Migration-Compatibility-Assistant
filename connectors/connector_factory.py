from compatibility_analyzer.connectors.file_connector import FileConnector
from compatibility_analyzer.connectors.odoo_connector import OdooConnector
from compatibility_analyzer.connectors.oracle_fusion_connector import (
    OracleFusionConnector,
)
from compatibility_analyzer.connectors.salesforce_connector import (
    SalesforceConnector,
)


class ConnectorFactory:
    @staticmethod
    def create(system_name, config):
        system_name = system_name.lower()

        if system_name in {"file", "csv", "xlsx"}:
            return FileConnector(config)

        if system_name == "odoo":
            return OdooConnector(config)

        if system_name in {"salesforce", "sf"}:
            return SalesforceConnector(config)

        if system_name == "oracle":
            return OracleFusionConnector(config)

        raise ValueError(
            f"Unsupported ERP system: {system_name}"
        )