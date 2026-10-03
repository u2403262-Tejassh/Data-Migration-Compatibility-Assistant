SYSTEM_FIELD_EXACT = {
    "id",
    "display_name",
    "__last_update",
    "create_uid",
    "write_uid",
    "create_date",
    "write_date",
}

SYSTEM_FIELD_PREFIXES = (
    "message_",
    "activity_",
    "website_",
    "image_",
)


def is_system_field(field_name):
    if field_name in SYSTEM_FIELD_EXACT:
        return True

    return field_name.startswith(SYSTEM_FIELD_PREFIXES)


def analyze_target_fields(schema):
    """
    Returns a migration-safe target schema.
    """

    filtered_fields = {}

    for field_name, field_meta in schema["fields"].items():

        if is_system_field(field_name):
            continue

        if field_meta.get("readonly"):
            continue

        filtered_fields[field_name] = field_meta

    result = dict(schema)

    result["fields"] = filtered_fields
    result["field_count"] = len(filtered_fields)

    return result