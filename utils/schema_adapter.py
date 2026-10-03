def schema_to_dict(schema):

    if hasattr(schema, "to_dict"):
        return schema.to_dict()

    return schema