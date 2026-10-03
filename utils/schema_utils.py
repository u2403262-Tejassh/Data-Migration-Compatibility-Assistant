# ---------------------------------------------------------------------------
# System / framework field exclusion
# ---------------------------------------------------------------------------

SYSTEM_FIELD_EXACT = frozenset({
    # Odoo ORM fields
    "id",
    "display_name",
    "__last_update",
    "create_uid",
    "write_uid",
    "create_date",
    "write_date",
    # Salesforce audit fields
    "CreatedDate",
    "LastModifiedDate",
    "SystemModstamp",
    "IsDeleted",
    "OwnerId",
    "CreatedById",
    "LastModifiedById",
})

SYSTEM_FIELD_PREFIXES = (
    "message_",
    "activity_",
    "image_",
    "website_",
    "calendar_",
    "signup_",
)


def is_system_field(field_name: str) -> bool:
    """Return True if the field is an ERP framework/internal field."""
    return (
            field_name in SYSTEM_FIELD_EXACT
            or field_name.startswith(SYSTEM_FIELD_PREFIXES)
    )


# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------

def json_safe(value):
    """
    Recursively convert numpy/pandas scalars and other non-JSON-serializable
    objects to their Python equivalents.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}

    # numpy / pandas scalars expose .item()
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except (TypeError, ValueError):
            pass

    return str(value)