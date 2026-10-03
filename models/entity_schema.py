from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FieldSchema:
    name: str
    label: str
    field_type: str

    required: bool = False
    readonly: bool = False

    relation: Optional[str] = None
    help_text: Optional[str] = None

    source_dtype: Optional[str] = None

    populated_pct: Optional[float] = None
    null_pct: Optional[float] = None
    unique_pct: Optional[float] = None

    sample_values: list = field(default_factory=list)


@dataclass
class EntitySchema:
    system: str

    entity: str

    label: str

    fields: dict[str, FieldSchema]

    record_count: Optional[int] = None

    metadata: dict = field(default_factory=dict)

    @property
    def field_count(self) -> int:
        return len(self.fields)

    def to_dict(self) -> dict:
        return {
            "system": self.system,
            "model": self.entity,
            "entity": self.entity,
            "name": self.label,
            "label": self.label,
            "field_count": self.field_count,
            "record_count": self.record_count,
            "fields": {
                name: {
                    "label": f.label,
                    "type": f.field_type,
                    "required": f.required,
                    "readonly": f.readonly,
                    "relation": f.relation,
                    "help": f.help_text,
                    "source_dtype": f.source_dtype,
                    "populated_pct": f.populated_pct,
                    "null_pct": f.null_pct,
                    "unique_pct": f.unique_pct,
                    "sample_values": f.sample_values,
                }
                for name, f in self.fields.items()
            },
            "metadata": self.metadata,
        }