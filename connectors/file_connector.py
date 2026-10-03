from compatibility_analyzer.connectors.base_connector import ERPConnector
from compatibility_analyzer.profiling.source_profiler import (
    load_source_file,
    profile_dataframe,
)
from compatibility_analyzer.models import (
    EntitySchema,
    FieldSchema,
)

class FileConnector(ERPConnector):
    ENTITY_NAME = "uploaded_dataset"

    def __init__(self, config: dict):
        super().__init__(config)

        self.file_path = config.get("file_path")
        self.dataframe = config.get("dataframe")

        if self.dataframe is None:
            if not self.file_path:
                raise ValueError(
                    "File connector requires a file_path or dataframe"
                )

            self.dataframe = load_source_file(self.file_path)

        self.profile = profile_dataframe(self.dataframe)

    def test_connection(self):
        return {
            "status": "connected",
            "rows": len(self.dataframe),
            "columns": len(self.dataframe.columns),
        }

    def discover_models(self):
        return [
            {
                "model": self.ENTITY_NAME,
                "name": "Uploaded Dataset",
            }
        ]

    def fetch_schema(self, model_name):

        if model_name != self.ENTITY_NAME:
            raise ValueError(
                f"Unknown file entity: {model_name}"
            )

        fields = {}

        for column_name, metadata in (
                self.profile["columns"].items()
        ):
            fields[column_name] = FieldSchema(
                name=column_name,
                label=column_name,
                field_type=self._normalize_dtype(
                    metadata.get("dtype")
                ),
                required=False,
                readonly=False,
                relation=None,
                source_dtype=metadata.get("dtype"),
                populated_pct=(
                        100 - metadata.get("null_pct", 0)
                ),
                null_pct=metadata.get("null_pct"),
                unique_pct=metadata.get("unique_pct"),
                sample_values=metadata.get(
                    "sample_values",
                    [],
                ),
            )

        return EntitySchema(
            system="file",
            entity=model_name,
            label="Uploaded Dataset",
            fields=fields,
            record_count=self.profile.get(
                "row_count"
            ),
            metadata={
                "column_count": self.profile.get(
                    "column_count"
                )
            },
        )
    def sample_records(self, model_name, limit=20):
        if model_name != self.ENTITY_NAME:
            raise ValueError(f"Unknown file entity: {model_name}")

        return self.dataframe.head(limit).to_dict("records")

    @staticmethod
    def _normalize_dtype(dtype):
        dtype_text = str(dtype or "").lower()

        if "bool" in dtype_text:
            return "boolean"

        if "datetime" in dtype_text or "datetimetz" in dtype_text:
            return "datetime"

        if "date" in dtype_text:
            return "date"

        if "int" in dtype_text:
            return "integer"

        if "float" in dtype_text or "decimal" in dtype_text:
            return "float"

        return "char"