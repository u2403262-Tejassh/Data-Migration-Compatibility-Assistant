from compatibility_analyzer.utils.schema_utils import is_system_field

BINARY_TYPES = {
    "binary",
    "base64",
}


def is_empty_value(value):
    if value is None:
        return True

    if value is False:
        return True

    if isinstance(value, str) and value.strip() == "":
        return True

    if isinstance(value, (list, tuple, dict, set)) and len(value) == 0:
        return True

    return False


def is_binary_field(metadata):
    field_type = str(
        metadata.get("type")
        or metadata.get("source_dtype")
        or metadata.get("salesforce_type")
        or ""
    ).lower()

    return field_type in BINARY_TYPES or "binary" in field_type or "blob" in field_type


def population_stats(field_name, samples):
    if not samples:
        return 0.0, 100.0

    total = len(samples)
    populated = sum(
        1
        for row in samples
        if not is_empty_value(row.get(field_name))
    )

    populated_pct = round((populated / total) * 100, 2)
    return populated_pct, round(100 - populated_pct, 2)


def analyze_source_fields(source_schema, samples):
    fields = source_schema.get("fields", {})
    analyzed = {}

    for field_name, metadata in fields.items():
        populated_pct, null_pct = population_stats(field_name, samples)
        system_field = is_system_field(field_name)
        binary_field = is_binary_field(metadata)
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
            "reason": field_selection_reason(system_field, binary_field, empty_field),
        }

    return analyzed


def field_selection_reason(system_field, binary_field, empty_field):
    if system_field:
        return "system field"

    if binary_field:
        return "binary/blob field"

    if empty_field:
        return "0% populated"

    return "business field"


def selected_field_names(field_analysis):
    return [
        field_name
        for field_name, metadata in field_analysis.items()
        if metadata.get("selectable")
    ]


def filter_schema_fields(schema, field_names):
    selected = set(field_names)
    filtered = dict(schema)
    filtered["fields"] = {
        field_name: metadata
        for field_name, metadata in schema.get("fields", {}).items()
        if field_name in selected
    }
    filtered["field_count"] = len(filtered["fields"])

    if "columns" in schema:
        filtered["columns"] = {
            field_name: metadata
            for field_name, metadata in schema.get("columns", {}).items()
            if field_name in selected
        }
        filtered["column_count"] = len(filtered["columns"])

    filtered["selected_field_count"] = len(selected)
    return filtered
