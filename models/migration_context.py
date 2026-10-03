from dataclasses import dataclass
from typing import Optional

from compatibility_analyzer.models.entity_schema import (
    EntitySchema,
)


@dataclass
class MigrationContext:

    source_system: str

    target_system: str

    source_entity: Optional[str] = None

    target_entity: Optional[str] = None

    source_schema: Optional[
        EntitySchema
    ] = None

    target_schema: Optional[
        EntitySchema
    ] = None

    prediction: Optional[dict] = None

    compatibility: Optional[dict] = None