"""
planning/field_classifier.py  —  Phase 2.5

Merged replacement for source_field_analyzer.py and target_schema_analyzer.py.

Accepts both plain dicts (legacy) and EntitySchema instances (Phase 2+).

Exports:
    analyze_source_fields(schema, samples)    → field analysis dict
    analyze_target_fields(schema)             → migration-safe target schema dict
    filter_schema_fields(schema, field_names) → filtered schema dict
    selected_field_names(field_analysis)      → list of selectable field names
"""

from compatibility_analyzer.utils.schema_utils import (
    SYSTEM_FIELD_EXACT,
    SYSTEM_FIELD_PREFIXES,
    is_system_field,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

BINARY_TYPES = frozenset({"binary", "base64", "blob", "image", "file"})


def _is_entity_schema(obj) -> bool:
    """Duck-type check for EntitySchema instances."""
    return (
        hasattr(obj, "fields")
        and hasattr(obj, "entity")
        and hasattr(obj, "system")
        and not isinstance(obj, dict)
    )


def _get_fields_dict(schema) -> dict:
    """
    Return a normalized {field_name: metadata_dict} from either an
    EntitySchema instance or a raw dict schema.
    """
    if _is_entity_schema(schema):
        return {
            name: {
                "label": f.label,
                "type": f.field_type,
                "required": f.required,
                "readonly": f.readonly,
                "relation": f.relation,
                "source_dtype": getattr(f, "native_type", None),
                "populated_pct": f.populated_pct,
                "null_pct": getattr(f, "null_pct", None),
                "unique_pct": getattr(f, "unique_pct", None),
                "sample_values": f.sample_values,
                "pattern_hint": getattr(f, "pattern_hint", None),
            }
            for name, f in schema.fields.items()
        }

    return schema.get("fields", {})


def _is_empty_value(value) -> bool:
    if value is None or value is False:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, tuple, dict, set)) and len(value) == 0:
        return True
    return False


def _is_binary_field(metadata: dict) -> bool:
    raw = str(
        metadata.get("type")
        or metadata.get("source_dtype")
        or ""
    ).lower()
    return raw in BINARY_TYPES or "binary" in raw or "blob" in raw


def _population_stats(field_name: str, samples: list) -> tuple:
    """Return (populated_pct, null_pct) from sample records."""
    if not samples:
        return 0.0, 100.0

    total = len(samples)
    populated = sum(
        1 for row in samples if not _is_empty_value(row.get(field_name))
    )
    populated_pct = round((populated / total) * 100, 2)
    return populated_pct, round(100 - populated_pct, 2)


def _field_selection_reason(system_field, binary_field, empty_field) -> str:
    if system_field:
        return "system field"
    if binary_field:
        return "binary/blob field"
    if empty_field:
        return "0% populated"
    return "business field"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_source_fields(schema, samples: list) -> dict:
    """
    Classify each source field as selectable or excluded with a reason.

    Args:
        schema:  EntitySchema instance or raw dict with a "fields" key.
        samples: List of record dicts returned by connector.sample_records().

    Returns:
        {field_name: {"selectable": bool, "reason": str, "populated_pct": float, ...}}
    """
    fields = _get_fields_dict(schema)
    analyzed = {}

    for field_name, metadata in fields.items():
        populated_pct, null_pct = _population_stats(field_name, samples)
        system_field = is_system_field(field_name)
        binary_field = _is_binary_field(metadata)
        empty_field = populated_pct == 0
        readonly = bool(metadata.get("readonly"))

        analyzed[field_name] = {
            "label": metadata.get("label") or field_name,
            "type": metadata.get("source_dtype") or metadata.get("type"),
            "populated_pct": populated_pct,
            "null_pct": null_pct,
            "system_field": system_field,
            "binary_field": binary_field,
            "readonly": readonly,
            "selectable": not system_field and not binary_field and not empty_field,
            "reason": _field_selection_reason(system_field, binary_field, empty_field),
        }

    return analyzed


def analyze_target_fields(schema) -> dict:
    """
    Return a migration-safe target schema dict: system and readonly fields removed.

    Accepts EntitySchema or raw dict.
    Always returns a raw dict (backwards-compatible with compatibility_reasoner).
    """
    if _is_entity_schema(schema):
        base = schema.to_dict()
    else:
        base = dict(schema)

    fields = _get_fields_dict(schema)
    filtered = {}

    for field_name, metadata in fields.items():
        if is_system_field(field_name):
            continue
        # Keep readonly fields that are required (the reasoner needs to flag them)
        if metadata.get("readonly") and not metadata.get("required"):
            continue
        filtered[field_name] = metadata

    result = dict(base)
    result["fields"] = filtered
    result["field_count"] = len(filtered)
    return result


def filter_schema_fields(schema, field_names: list) -> dict:
    """
    Return a copy of schema containing only the specified fields.

    Accepts EntitySchema or raw dict.
    Always returns a raw dict.
    """
    if _is_entity_schema(schema):
        base = schema.to_dict()
    else:
        base = dict(schema)

    selected = set(field_names)

    filtered_fields = {
        k: v for k, v in base.get("fields", {}).items()
        if k in selected
    }
    result = dict(base)
    result["fields"] = filtered_fields
    result["field_count"] = len(filtered_fields)
    result["selected_field_count"] = len(selected)

    # Legacy CSV path
    if "columns" in base:
        result["columns"] = {
            k: v for k, v in base["columns"].items()
            if k in selected
        }
        result["column_count"] = len(result["columns"])

    return result


def selected_field_names(field_analysis: dict) -> list:
    """Return a list of field names marked as selectable."""
    return [
        name for name, meta in field_analysis.items()
        if meta.get("selectable")
    ]