# connectors/base_connector.py
from abc import ABC, abstractmethod


class ERPConnector(ABC):

    def __init__(self, config: dict):
        self.config = config

    # ------------------------------------------------------------------
    # Abstract interface — all connectors must implement these three
    # ------------------------------------------------------------------

    @abstractmethod
    def discover_models(self) -> list[dict]:
        """
        Return a list of available entities/objects/models.
        Each entry: {"model": "<technical_name>", "name": "<human_label>"}
        """

    @abstractmethod
    def fetch_schema(self, entity_name: str) -> dict:
        """
        Return the schema of a single entity as a dict.
        Must include: {"system": str, "model": str, "fields": dict}
        """

    @abstractmethod
    def sample_records(self, entity_name: str, limit: int = 20) -> list[dict]:
        """
        Return up to `limit` sample records from the entity.
        """

    # ------------------------------------------------------------------
    # Optional — override in subclasses
    # ------------------------------------------------------------------

    def test_connection(self) -> dict:
        """
        Validate connectivity. Override in subclasses.
        Returns {"status": "connected", ...} on success.
        Raises on failure.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement test_connection()"
        )

    def list_entities(self) -> list[dict]:
        """Alias for backwards compatibility. Prefer discover_models()."""
        return self.discover_models()

    @property
    def system_name(self) -> str:
        """Human-readable system name. Override in subclasses."""
        return self.__class__.__name__.replace("Connector", "")