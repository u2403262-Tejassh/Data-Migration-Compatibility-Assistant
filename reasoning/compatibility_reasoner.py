"""
reasoning/compatibility_reasoner.py

Two-pass ERP compatibility analysis:
  Pass 1 — Deterministic: exact field-name matches.
  Pass 2 — LLM:           fuzzy / semantic matches for remaining fields.

Phase 2 changes:
  - EntitySchema accepted natively by schema_fields() and compact_target_schema()
  - normalized_type() handles Python/pandas dtypes (str, int64, float64, …)
  - summarize_unmapped_target_fields() bug fixed (missing detail_entries.append)
  - Duplicate issues between deterministic and LLM passes are deduplicated
  - compatibility_score (0–100 float) added to analyze_compatibility() output
  - many2many required unmapped fields downgraded HIGH → MEDIUM
  - Low-confidence LLM mappings generate LOW warnings
  - Degenerate source field names (_, Unnamed: X) are filtered out
  - LLM prompt updated: do NOT re-report unmapped required fields
"""

import json
import re
import warnings

from compatibility_analyzer.utils.schema_utils import json_safe, is_system_field
from compatibility_analyzer.migration_catalog.catalog_manager import get_catalog


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_LLM_SOURCE_FIELDS = 30
MAX_LLM_TARGET_FIELDS = 30
MAX_UNMAPPED_OUTPUT = 30

# LLM mapping suggestions below this confidence get a LOW warning
LOW_CONFIDENCE_THRESHOLD = 0.55

SYSTEM_FIELD_PREFIXES = (
    "message_",
    "activity_",
    "image_",
    "website_",
)

NON_MIGRATION_TARGET_FIELDS = frozenset({
    "id",
    "display_name",
    "__last_update",
    "create_uid",
    "write_uid",
    "create_date",
    "write_date",
})

# Source column names that are CSV export artifacts, not real business fields
DEGENERATE_SOURCE_FIELDS = frozenset({"_", ""})
def same_model_migration(
    source_schema,
    target_schema,
):

    return (
        _schema_system_name(
            source_schema
        )
        ==
        _schema_system_name(
            target_schema
        )
        and
        _schema_model_name(
            source_schema
        )
        ==
        _schema_model_name(
            target_schema
        )
    )

def _is_degenerate_field(name: str) -> bool:
    """Return True for unnamed or placeholder column names from CSV exports."""
    return (
        not name
        or name in DEGENERATE_SOURCE_FIELDS
        or name.lower().startswith("unnamed:")
        or name.lower().startswith("unnamed_")
    )


# ---------------------------------------------------------------------------
# EntitySchema duck-typing
# ---------------------------------------------------------------------------

def _is_entity_schema(obj) -> bool:
    """
    Return True if obj is an EntitySchema dataclass instance.
    Checked structurally (duck typing) to avoid circular imports.
    """
    return (
        hasattr(obj, "fields")
        and hasattr(obj, "entity")
        and hasattr(obj, "system")
        and not isinstance(obj, dict)
    )


def _schema_model_name(schema) -> str:
    if _is_entity_schema(schema):
        return schema.entity
    return schema.get("model") or schema.get("entity", "")


def _schema_system_name(schema) -> str:
    if _is_entity_schema(schema):
        return schema.system
    return schema.get("system", "")


# ---------------------------------------------------------------------------
# Schema normalization
# ---------------------------------------------------------------------------

def schema_fields(schema) -> dict:
    """
    Return a normalized {field_name: metadata_dict} from either an EntitySchema
    instance or a raw dict (ERP dict with "fields" key, or CSV dict with "columns").

    This is the single point of truth for field extraction in the reasoner.
    All other functions call this rather than accessing schema keys directly.
    """
    # Phase 2: EntitySchema dataclass
    if _is_entity_schema(schema):
        return {
            name: {
                "label": f.label,
                "type": f.field_type,
                "required": f.required,
                "readonly": f.readonly,
                "relation": f.relation,
                "help": getattr(f, "help_text", None),
                # native_type carries the pre-normalization source type
                "source_dtype": (
                    getattr(f, "native_type", None)
                    or getattr(f, "source_dtype", None)
                ),
                "populated_pct": f.populated_pct,
                "null_pct": getattr(f, "null_pct", None),
                "unique_pct": getattr(f, "unique_pct", None),
                "sample_values": f.sample_values,
                "pattern_hint": getattr(f, "pattern_hint", None),
            }
            for name, f in schema.fields.items()
        }

    # Raw ERP dict: {"fields": {...}}
    if "fields" in schema:
        return schema["fields"]

    # Legacy CSV dict: {"columns": {...}}
    return {
        field_name: {
            "label": field_name,
            "type": metadata.get("dtype"),
            "required": metadata.get("null_pct", 0) == 0,
            "relation": metadata.get("relation"),
            "sample_values": metadata.get("sample_values", []),
            "pattern_hint": metadata.get("pattern_hint"),
        }
        for field_name, metadata in schema.get("columns", {}).items()
    }


def source_schema_to_profile(source_schema):
    """
    Deprecated: convert ERP dict schema → legacy CSV profile format.
    Kept only for backwards compatibility with old call sites.
    Use schema_fields() directly instead.
    """
    warnings.warn(
        "source_schema_to_profile() is deprecated; use schema_fields() directly.",
        DeprecationWarning,
        stacklevel=2,
    )
    if "columns" in source_schema:
        return source_schema

    columns = {}
    for field_name, metadata in source_schema.get("fields", {}).items():
        columns[field_name] = {
            "dtype": metadata.get("source_dtype") or metadata.get("type"),
            "null_pct": metadata.get("null_pct"),
            "unique_pct": metadata.get("unique_pct"),
            "sample_values": metadata.get("sample_values", []),
            "pattern_hint": metadata.get("pattern_hint"),
            "label": metadata.get("label"),
            "required": metadata.get("required"),
            "relation": metadata.get("relation"),
        }

    return {
        "row_count": source_schema.get("row_count"),
        "column_count": len(columns),
        "columns": columns,
    }


# ---------------------------------------------------------------------------
# Type normalization
# ---------------------------------------------------------------------------

def normalized_type(field_metadata: dict) -> str:
    """
    Map a native field type (Odoo, Salesforce, Python/pandas, Oracle, …) to a
    canonical group used for cross-system type-mismatch detection.

    Canonical groups:
        text       — any string / char / text type  (str, object, varchar, …)
        number     — integer, float, monetary, currency
        date       — date, datetime, timestamp
        boolean    — bool
        relation   — many2one / FK
        multi      — many2many, one2many
        selection  — picklist / enum
        binary     — file, attachment, image
    """
    raw = (
        field_metadata.get("source_dtype")
        or field_metadata.get("type")
        or ""
    )
    field_type = str(raw).lower().strip()

    # Strip pandas integer/float width suffixes: "int64" → "int", "float32" → "float"
    pandas_match = re.match(r"^(int|uint|float|bool)\d+$", field_type)
    if pandas_match:
        field_type = pandas_match.group(1)

    # "datetime64[ns]", "datetime64[ns, UTC]" → "datetime"
    if field_type.startswith("datetime64"):
        field_type = "datetime"

    # Text / string family
    # Includes Python's "str" and "object" (pandas default string dtype)
    if field_type in {
        "char", "string", "str", "text", "textarea", "object",
        "varchar", "nvarchar", "clob", "nclob", "longtext",
    }:
        return "text"

    # Numeric family
    if field_type in {
        "integer", "int", "uint",
        "float", "double", "decimal",
        "monetary", "currency", "number", "numeric",
    }:
        return "number"

    # Date / time family
    if field_type in {"date", "datetime", "timestamp", "datetimetz", "time"}:
        return "date"

    # Boolean
    if field_type in {"boolean", "bool", "checkbox"}:
        return "boolean"

    # Many-to-one / FK
    if field_type in {"many2one", "reference", "lookup", "masterdetail"}:
        return "relation"

    # Many-to-many / one-to-many
    if field_type in {"many2many", "one2many", "multipicklist"}:
        return "multi"

    # Selection / enum / picklist
    if field_type in {"selection", "picklist", "combobox", "enum"}:
        return "selection"

    # Binary / attachment
    if field_type in {"binary", "base64", "blob", "image", "file"} or "binary" in field_type:
        return "binary"

    # Unknown — return as-is so no false-positive mismatch is raised
    return field_type


# ---------------------------------------------------------------------------
# Schema compact helpers  (token-budget summaries for LLM prompts)
# ---------------------------------------------------------------------------

def compact_fields(fields: dict, max_fields: int = None) -> dict:
    """Legacy shim kept for any callers outside the reasoner."""
    return _compact_source_fields(fields, max_fields)


def _compact_source_fields(fields: dict, max_fields: int = None) -> dict:
    """
    Compact representation for SOURCE fields sent to the LLM.
    Includes type and up to 2 sample values. No label/pattern (saves tokens).
    """
    compact = {}
    for field_name, metadata in fields.items():
        t = json_safe(metadata.get("source_dtype") or metadata.get("type"))
        s = json_safe(metadata.get("sample_values", [])[:2])
        # Only include samples key if there are actual values
        entry = {"t": t}
        if s:
            entry["s"] = s
        compact[field_name] = entry
        if max_fields and len(compact) >= max_fields:
            break
    return compact


def _compact_target_fields(fields: dict, max_fields: int = None) -> dict:
    """
    Compact representation for TARGET fields sent to the LLM.
    Target fields have no sample values — omitting saves ~40% tokens vs compact_fields.
    """
    compact = {}
    for field_name, metadata in fields.items():
        entry = {"t": json_safe(metadata.get("type"))}
        if metadata.get("required"):
            entry["req"] = True
        if metadata.get("relation"):
            entry["rel"] = json_safe(metadata.get("relation"))
        compact[field_name] = entry
        if max_fields and len(compact) >= max_fields:
            break
    return compact


def compact_source_profile(source_schema) -> dict:
    """Legacy shim — use compact_fields(schema_fields(schema)) instead."""
    return compact_fields(schema_fields(source_schema))


def compact_target_schema(target_schema, max_fields: int = 25) -> dict:
    """
    Token-budget-friendly target field dict for LLM prompting.
    Accepts EntitySchema or raw dict.
    Excludes system/framework fields and readonly non-required fields.
    """
    allowed_types = {
        "char", "text", "boolean", "date", "datetime",
        "many2one", "many2many", "one2many", "selection",
        "integer", "float", "monetary",
    }
    excluded_exact = NON_MIGRATION_TARGET_FIELDS | {
        "color", "active", "employee",
        "partner_latitude", "partner_longitude",
    }
    excluded_prefixes = ("message_", "activity_", "calendar_", "signup_", "image_")

    fields = schema_fields(target_schema)
    compact = {}

    for field_name, metadata in fields.items():
        if field_name in excluded_exact:
            continue
        if any(field_name.startswith(p) for p in excluded_prefixes):
            continue
        if metadata.get("type") not in allowed_types:
            continue
        if metadata.get("readonly") and not metadata.get("required"):
            continue

        compact[field_name] = {
            "label": json_safe(metadata.get("label")),
            "type": json_safe(metadata.get("type")),
            "required": json_safe(metadata.get("required")),
            "relation": json_safe(metadata.get("relation")),
        }

        if len(compact) >= max_fields:
            break

    return compact


def field_subset(schema, field_names: list) -> dict:
    fields = schema_fields(schema)
    return {name: fields[name] for name in field_names if name in fields}


# ---------------------------------------------------------------------------
# Deterministic exact matching  (Pass 1)
# ---------------------------------------------------------------------------

def deterministic_exact_matches(source_schema, target_schema) -> dict:
    """
    Find source ↔ target field pairs with matching (case-insensitive) names.
    Degenerate source field names (_, Unnamed: X) are excluded.
    """
    source_fields = schema_fields(source_schema)
    target_fields = schema_fields(target_schema)

    # Build lowercased target name → original name map (skip system fields)
    normalized_target = {
        name.lower().strip(): name
        for name in target_fields
        if name not in NON_MIGRATION_TARGET_FIELDS
    }

    mappings = []
    mapped_source = set()
    mapped_target = set()

    for source_field in source_fields:
        if _is_degenerate_field(source_field):
            continue

        normalized = source_field.lower().strip()
        if normalized not in normalized_target:
            continue

        target_field = normalized_target[normalized]
        mappings.append({
            "source_field": source_field,
            "target_field": target_field,
            "confidence": 1.0,
            "reason": "exact field name match",
        })
        mapped_source.add(source_field)
        mapped_target.add(target_field)

    unmapped_source = [f for f in source_fields if f not in mapped_source]
    unmapped_target = [f for f in target_fields if f not in mapped_target]

    return {
        "mapping_suggestions": mappings,
        "mapped_source_fields": mapped_source,
        "mapped_target_fields": mapped_target,
        "unmapped_source_fields": unmapped_source,
        "unmapped_target_fields": unmapped_target,
    }


# ---------------------------------------------------------------------------
# LLM prompt builder  (Pass 2)
# ---------------------------------------------------------------------------

def build_reasoning_prompt(
    source_schema,
    target_schema,
    source_field_names=None,
    target_field_names=None,
) -> str:
    source_subset = field_subset(
        source_schema,
        source_field_names or list(schema_fields(source_schema)),
    )
    target_subset = field_subset(
        target_schema,
        target_field_names or list(schema_fields(target_schema)),
    )

    # Remove degenerate source fields from the LLM input
    source_subset = {k: v for k, v in source_subset.items() if not _is_degenerate_field(k)}

    compact_source = _compact_source_fields(source_subset, max_fields=MAX_LLM_SOURCE_FIELDS)
    compact_target = _compact_target_fields(target_subset, max_fields=MAX_LLM_TARGET_FIELDS)

    required_fields = [name for name, meta in compact_target.items() if meta.get("required")]

    target_system = _schema_system_name(target_schema) or "target ERP"
    source_system = _schema_system_name(source_schema) or "source system"
    source_entity = _schema_model_name(source_schema) or "source"
    target_entity = _schema_model_name(target_schema) or "target"

    return f"""
You are an ERP migration analyst.

Analyze compatibility between SOURCE ({source_system}: {source_entity}) and TARGET ({target_system}: {target_entity}).

Tasks:
- Suggest fuzzy or semantic field mappings for the AMBIGUOUS SOURCE FIELDS provided below
- Identify datatype or format mismatches in suggested mappings
- Identify relational compatibility issues (e.g. many2one without matching records)
- Suggest export / import improvements

Rules:
- DO NOT return exact name matches — those have already been handled
- ONLY use field names listed below — DO NOT invent fields
- DO NOT report issues about unmapped required target fields — those are reported separately
- Confidence scale: 1.0 = certain, 0.7 = likely, 0.5 = plausible, 0.3 = speculative
- Be specific and practical; keep recommendations concise

Return STRICT JSON ONLY — no markdown, no code fences, no preamble:

{{
  "mapping_suggestions": [
    {{
      "source_field": "source column",
      "target_field": "target field",
      "confidence": 0.0,
      "reason": "why these fields correspond"
    }}
  ],
  "unmapped_source_fields": [
    {{
      "source_field": "source column",
      "reason": "why not mappable",
      "recommendation": "what to do"
    }}
  ],
  "compatibility_issues": [
    {{
      "severity": "high|medium|low",
      "issue": "description",
      "recommendation": "fix"
    }}
  ],
  "export_recommendations": [
    "recommendation"
  ],
  "overall_assessment": "2–3 sentence summary"
}}

AMBIGUOUS SOURCE FIELDS:
{json.dumps(compact_source, separators=(',', ':'))}

AVAILABLE TARGET FIELDS:
{json.dumps(compact_target, separators=(',', ':'))}

REQUIRED TARGET FIELDS (for reference only — do NOT report missing ones as issues):
{json.dumps(required_fields)}
"""


# ---------------------------------------------------------------------------
# LLM result helpers
# ---------------------------------------------------------------------------

def empty_llm_result() -> dict:
    return {
        "mapping_suggestions": [],
        "unmapped_source_fields": [],
        "compatibility_issues": [],
        "export_recommendations": [],
        "overall_assessment": "",
    }


def validate_llm_result(result: dict) -> dict:
    required_keys = [
        "mapping_suggestions",
        "unmapped_source_fields",
        "compatibility_issues",
        "export_recommendations",
        "overall_assessment",
    ]
    for key in required_keys:
        if key not in result:
            result[key] = [] if key != "overall_assessment" else ""
    return result


def bounded_ambiguous_fields(exact_match_result: dict) -> list:
    """Unmapped source fields up to the LLM token budget, degenerate names excluded."""
    return [
        f for f in exact_match_result["unmapped_source_fields"]
        if not _is_degenerate_field(f)
    ][:MAX_LLM_SOURCE_FIELDS]


def bounded_target_fields(exact_match_result: dict, target_schema) -> list:
    """Unmapped target fields prioritized by required status, up to token budget."""
    target_fields = schema_fields(target_schema)
    required_unmapped = [
        f for f in exact_match_result["unmapped_target_fields"]
        if target_fields.get(f, {}).get("required")
    ]
    ordered = []
    for f in required_unmapped + exact_match_result["unmapped_target_fields"]:
        if f not in ordered:
            ordered.append(f)
    return ordered[:MAX_LLM_TARGET_FIELDS]


def normalize_llm_mappings(
    llm_mappings,
    source_candidates,
    target_candidates,
    source_schema,
    target_schema,
) -> tuple:
    """
    Validate and deduplicate LLM mapping suggestions against allowed field sets.
    Returns (normalized_mappings, mapped_source_set, mapped_target_set).
    """
    source_fields = schema_fields(
        source_schema
    )

    target_fields = schema_fields(
        target_schema
    )
    source_allowed = set(source_candidates)
    target_allowed = set(target_candidates)
    normalized = []
    mapped_source = set()
    mapped_target = set()

    for mapping in llm_mappings:
        source_field = mapping.get("source_field")
        target_field = mapping.get("target_field")

        if source_field not in source_allowed:
            continue

        if target_field not in target_allowed:
            continue

        if source_field in mapped_source:
            continue

        if target_field in mapped_target:
            continue

        source_meta = source_fields.get(
            source_field,
            {},
        )

        target_meta = target_fields.get(
            target_field,
            {},
        )

        source_type = normalized_type(
            source_meta
        )

        target_type = normalized_type(
            target_meta
        )

        # Hard reject incompatible mappings

        if (
                source_type == "number"
                and target_type in {
            "relation",
            "multi",
        }
        ):
            continue

        if (
                source_type == "boolean"
                and target_type in {
            "relation",
            "multi",
        }
        ):
            continue

        if (
                source_type in {
            "relation",
            "multi",
        }
                and target_type not in {
            "relation",
            "multi",
        }
        ):
            continue

        # count fields should never map
        # to relation collections

        if source_field.endswith("_count"):
            continue

        normalized.append({
            "source_field": source_field,
            "target_field": target_field,
            "confidence": float(mapping.get("confidence") or 0.0),
            "reason": mapping.get("reason", "semantic match"),
        })
        mapped_source.add(source_field)
        mapped_target.add(target_field)

    return normalized, mapped_source, mapped_target


# ---------------------------------------------------------------------------
# Issue builders
# ---------------------------------------------------------------------------

def build_missing_required_issues(target_schema, unmapped_target_fields: list) -> list:
    """
    Deterministic issues for required target fields that have no mapping.

    many2many / one2many fields are MEDIUM (often auto-populated by the ERP).
    many2one and scalar required fields are HIGH.
    """
    target_fields = schema_fields(target_schema)
    issues = []

    for field_name in unmapped_target_fields:
        metadata = target_fields.get(field_name, {})
        if not metadata.get("required"):
            continue

        field_type = metadata.get("type", "")
        type_hint = f" ({field_type})" if field_type else ""

        if field_type in {"many2many", "one2many"}:
            severity = "medium"
            recommendation = (
                f"'{field_name}' is a multi-value relational field and may be "
                "auto-populated by the target ERP. "
                "Review the system's default configuration before migration."
            )
        elif field_type == "many2one":
            severity = "high"
            recommendation = (
                f"Provide a valid '{field_name}' record reference from the target "
                "system, or add a lookup / default transformation."
            )
        else:
            severity = "high"
            recommendation = (
                "Provide a source value, transformation rule, default value, or "
                "pre-migration enrichment for this target field."
            )

        issues.append({
            "severity": severity,
            "issue": f"Required target field '{field_name}'{type_hint} is not mapped.",
            "recommendation": recommendation,
        })

    return issues


def build_mapped_field_issues(source_schema, target_schema, mappings: list) -> list:
    """
    Issues for type mismatches and readonly-field violations in confirmed mappings.
    """
    source_fields = schema_fields(source_schema)
    target_fields = schema_fields(target_schema)
    issues = []

    for mapping in mappings:
        source_field = mapping.get("source_field")
        target_field = mapping.get("target_field")
        source_meta = source_fields.get(source_field, {})
        target_meta = target_fields.get(target_field, {})

        source_type = normalized_type(source_meta)
        target_type = normalized_type(target_meta)

        # Only flag a mismatch when both sides resolve to a known, different group
        if source_type and target_type and source_type != target_type:
            issues.append({
                "severity": "medium",
                "issue": (
                    f"Mapped field '{source_field}' has type '{source_type}' but "
                    f"target field '{target_field}' expects '{target_type}'."
                ),
                "recommendation": "Add a transformation or validate values before import.",
            })

        if target_meta.get("readonly"):
            issues.append({
                "severity": "high",
                "issue": (
                    f"Target field '{target_field}' is readonly and cannot be imported."
                ),
                "recommendation": (
                    "Remove this mapping or use an alternative import path / API endpoint."
                ),
            })

    return issues


def build_low_confidence_issues(llm_mappings: list) -> list:
    """
    LOW warnings for LLM mapping suggestions whose confidence falls below the threshold.
    Exact matches (confidence == 1.0) are skipped.
    """
    issues = []
    for mapping in llm_mappings:
        confidence = float(mapping.get("confidence") or 0.0)
        if confidence >= 1.0:
            continue  # exact match — not an LLM suggestion
        if confidence < LOW_CONFIDENCE_THRESHOLD:
            issues.append({
                "severity": "low",
                "issue": (
                    f"Mapping '{mapping['source_field']}' → '{mapping['target_field']}' "
                    f"has low confidence ({confidence:.0%}): {mapping.get('reason', '')}."
                ),
                "recommendation": "Manually verify this mapping before import.",
            })
    return issues


def _extract_field_name(text: str):
    """Extract the first single-quoted identifier from an issue description."""
    match = re.search(r"'([^']+)'", text)
    return match.group(1) if match else None


def deduplicate_issues(deterministic_issues: list, llm_issues: list) -> list:
    """
    Merge deterministic + LLM issues, dropping LLM entries that repeat a field
    already covered by a deterministic issue.

    Deterministic issues are always preferred: their wording is precise and
    machine-generated. LLM issues about the same named field are dropped.
    """
    covered_fields = set()
    for issue in deterministic_issues:
        field = _extract_field_name(issue.get("issue", ""))
        if field:
            covered_fields.add(field)

    unique_llm = []
    for issue in llm_issues:
        field = _extract_field_name(issue.get("issue", ""))
        if field and field in covered_fields:
            continue  # already reported deterministically
        unique_llm.append(issue)

    return deterministic_issues + unique_llm


# ---------------------------------------------------------------------------
# Compatibility score
# ---------------------------------------------------------------------------

def compute_compatibility_score(
    mapping_suggestions: list,
    source_schema,
    target_schema,
    compatibility_issues: list,
) -> float:

    source_fields = schema_fields(source_schema)
    target_fields = schema_fields(target_schema)

    meaningful_source = [
        f for f in source_fields
        if not is_system_field(f)
        and not _is_degenerate_field(f)
    ]

    mapped_target_set = {
        m["target_field"]
        for m in mapping_suggestions
    }

    IGNORE_REQUIRED = {
        "journal_id",
        "move_type",
        "auto_post",
        "state",
    }

    required_target = [
        f
        for f, meta in target_fields.items()
        if meta.get("required")
        and f not in NON_MIGRATION_TARGET_FIELDS
        and f not in IGNORE_REQUIRED
    ]

    unmapped_required = [
        f
        for f in required_target
        if f not in mapped_target_set
    ]

    total_source = max(1, len(meaningful_source))

    source_coverage = min(
        1.0,
        len(mapping_suggestions) / total_source,
    )

    required_coverage = (
        (
            len(required_target)
            - len(unmapped_required)
        )
        / max(1, len(required_target))
        if required_target
        else 1.0
    )

    base = (
        source_coverage * 0.7
        + required_coverage * 0.3
    ) * 100

    extra_high = [
        i
        for i in compatibility_issues
        if i.get("severity") == "high"
        and "Required target field" not in i.get("issue", "")
    ]

    medium_issues = [
        i
        for i in compatibility_issues
        if i.get("severity") == "medium"
    ]

    penalty = min(
        15.0,
        len(extra_high) * 5.0
        + len(medium_issues) * 2.0,
    )

    return round(
        max(0.0, base - penalty),
        1,
    )


# ---------------------------------------------------------------------------
# Unmapped field summaries
# ---------------------------------------------------------------------------

def system_field_group(field_name: str):
    for prefix in SYSTEM_FIELD_PREFIXES:
        if field_name.startswith(prefix):
            return f"{prefix}*"
    return None


def summarize_unmapped_source_fields(source_schema, unmapped_source_fields: list) -> list:
    fields = schema_fields(source_schema)
    detail_entries = []
    group_counts = {}

    for field_name in unmapped_source_fields:
        if _is_degenerate_field(field_name):
            continue

        group = system_field_group(field_name)
        if group:
            group_counts[group] = group_counts.get(group, 0) + 1
            continue

        if len(detail_entries) >= MAX_UNMAPPED_OUTPUT:
            continue

        metadata = fields.get(field_name, {})
        detail_entries.append({
            "source_field": field_name,
            "reason": "No exact or high-confidence semantic target field was identified.",
            "recommendation": "Create a custom target field or exclude from migration.",
            "type": metadata.get("source_dtype") or metadata.get("type"),
        })

    group_entries = [
        {
            "source_field_group": group,
            "count": count,
            "reason": "system / framework fields",
            "recommendation": "typically ignore during migration",
        }
        for group, count in group_counts.items()
    ]

    detail_limit = max(0, MAX_UNMAPPED_OUTPUT - len(group_entries))
    return detail_entries[:detail_limit] + group_entries[:MAX_UNMAPPED_OUTPUT]


def summarize_unmapped_target_fields(target_schema, unmapped_target_fields: list) -> list:
    """
    Return summary entries for required unmapped target fields.

    Bug fixed: the original implementation was missing the detail_entries.append()
    call, so this function always returned an empty list.
    """
    target_fields = schema_fields(target_schema)
    detail_entries = []
    group_counts = {}

    for field_name in unmapped_target_fields:
        group = system_field_group(field_name)
        if group:
            group_counts[group] = group_counts.get(group, 0) + 1
            continue

        if len(detail_entries) >= MAX_UNMAPPED_OUTPUT:
            continue

        metadata = target_fields.get(field_name, {})
        if not metadata.get("required"):
            continue

        # Previously this append was missing — required target fields were silently dropped
        detail_entries.append({
            "target_field": field_name,
            "type": metadata.get("type"),
            "reason": "Required target field has no corresponding source mapping.",
            "recommendation": (
                "Assign a default value, constant, or transformation rule before import."
            ),
        })

    group_entries = [
        {
            "target_field_group": group,
            "count": count,
            "reason": "system / framework fields",
            "recommendation": "typically auto-managed — no action required",
        }
        for group, count in group_counts.items()
    ]

    detail_limit = max(0, MAX_UNMAPPED_OUTPUT - len(group_entries))
    return detail_entries[:detail_limit] + group_entries[:MAX_UNMAPPED_OUTPUT]


# ---------------------------------------------------------------------------
# Overall assessment
# ---------------------------------------------------------------------------

def build_overall_assessment(
    mapping_count: int,
    unmapped_source_count: int,
    issue_count: int,
) -> str:
    if issue_count:
        return (
            f"Compatibility analysis completed with {mapping_count} mapped fields, "
            f"{unmapped_source_count} unmapped source fields, and {issue_count} issues "
            "requiring review before migration."
        )
    if unmapped_source_count:
        return (
            f"Compatibility analysis completed with {mapping_count} mapped fields. "
            f"{unmapped_source_count} source fields remain unmapped and should be reviewed."
        )
    return (
        f"Compatibility analysis completed successfully with {mapping_count} mapped fields "
        "and no unmapped source fields."
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_compatibility(llm_client, source_schema, target_schema) -> dict:
    """
    Run the two-pass compatibility analysis.

    Accepts EntitySchema instances or raw dicts for both schemas.

    Returns:
        mapping_suggestions       list[dict]
        unmapped_source_fields    list[dict]
        unmapped_target_fields    list[dict]
        unmapped_source_count     int
        unmapped_target_count     int
        compatibility_issues      list[dict]   — deduplicated, no duplicates between passes
        compatibility_score       float        — 0–100
        export_recommendations    list[str]
        overall_assessment        str
    """
    # --- Pass 1: deterministic exact-name matches ---
    exact_result = deterministic_exact_matches(
        source_schema,
        target_schema,
    )

    # --- Pass 1.5: catalog-known semantic mappings ---
    _src_system = _schema_system_name(source_schema)
    _tgt_system = _schema_system_name(target_schema)

    print("\n=== CATALOG DEBUG ===")
    print("SOURCE SYSTEM:", _src_system)
    print("TARGET SYSTEM:", _tgt_system)

    _catalog = (
        get_catalog(_src_system, _tgt_system)
        if (_src_system and _tgt_system)
        else None
    )

    print("CATALOG FOUND:", _catalog is not None)
    _src_model  = _schema_model_name(source_schema)
    _tgt_model  = _schema_model_name(target_schema)

    _catalog = get_catalog(_src_system, _tgt_system) if (_src_system and _tgt_system) else None
    if _catalog:
        print("\n=== INJECTING CATALOG MAPPINGS ===")
        print("SOURCE MODEL:", _src_model)
        print("TARGET MODEL:", _tgt_model)

        before_count = len(exact_result["mapping_suggestions"])

        exact_result = _catalog.inject_catalog_mappings(
            exact_result,
            _src_model,
            _tgt_model,
        )

        after_count = len(exact_result["mapping_suggestions"])

        print("MAPPINGS BEFORE:", before_count)
        print("MAPPINGS AFTER :", after_count)

    ambiguous_source = bounded_ambiguous_fields(
        exact_result
    )

    ambiguous_target = bounded_target_fields(
        exact_result,
        target_schema,
    )

    if same_model_migration(
            source_schema,
            target_schema,
    ):
        compatibility_score = compute_compatibility_score(
            exact_result["mapping_suggestions"],
            source_schema,
            target_schema,
            [],
        )

        return {
            "mapping_suggestions":
                exact_result["mapping_suggestions"],

            "unmapped_source_fields":
                summarize_unmapped_source_fields(
                    source_schema,
                    exact_result["unmapped_source_fields"],
                ),

            "unmapped_target_fields":
                summarize_unmapped_target_fields(
                    target_schema,
                    exact_result["unmapped_target_fields"],
                ),

            "unmapped_source_count":
                len(
                    exact_result["unmapped_source_fields"]
                ),

            "unmapped_target_count":
                len(
                    exact_result["unmapped_target_fields"]
                ),

            "compatibility_issues": [],

            "export_recommendations": [],

            "overall_assessment":
                "Source and target entities are identical.",

            "compatibility_score":
                compatibility_score,
        }


    # --- Pass 2: LLM ---
    llm_result = empty_llm_result()
    if llm_client and ambiguous_source and ambiguous_target:
        prompt = build_reasoning_prompt(
            source_schema,
            target_schema,
            source_field_names=ambiguous_source,
            target_field_names=ambiguous_target,
        )
        llm_result = validate_llm_result(llm_client.generate_json(prompt))

    llm_mappings, llm_mapped_source, llm_mapped_target = normalize_llm_mappings(
        llm_result["mapping_suggestions"],
        ambiguous_source,
        ambiguous_target,
        source_schema,
        target_schema,
    )

    # --- Merge mapped sets ---
    all_mapped_source = exact_result["mapped_source_fields"] | llm_mapped_source
    all_mapped_target = exact_result["mapped_target_fields"] | llm_mapped_target

    final_unmapped_source = [
        f for f in schema_fields(source_schema)
        if f not in all_mapped_source
    ]
    final_unmapped_target = [
        f for f in schema_fields(target_schema)
        if f not in all_mapped_target
    ]

    mapping_suggestions = exact_result["mapping_suggestions"] + llm_mappings

    # --- Build and deduplicate issues ---
    deterministic_issues = (
        build_missing_required_issues(target_schema, final_unmapped_target)
        + build_mapped_field_issues(source_schema, target_schema, mapping_suggestions)
        + build_low_confidence_issues(llm_mappings)
    )
    compatibility_issues = deduplicate_issues(
        deterministic_issues,
        llm_result["compatibility_issues"],
    )

    # --- Summaries ---
    unmapped_source_entries = summarize_unmapped_source_fields(
        source_schema, final_unmapped_source,
    )
    unmapped_target_entries = summarize_unmapped_target_fields(
        target_schema, final_unmapped_target,
    )

    # --- Score ---
    compatibility_score = compute_compatibility_score(
        mapping_suggestions,
        source_schema,
        target_schema,
        compatibility_issues,
    )

    export_recommendations = llm_result["export_recommendations"] or [
        "Review unmapped source and required target fields before migration export.",
    ]
    overall_assessment = llm_result["overall_assessment"] or build_overall_assessment(
        len(mapping_suggestions),
        len(unmapped_source_entries),
        len(compatibility_issues),
    )

    return {
        "mapping_suggestions": mapping_suggestions,
        "unmapped_source_fields": unmapped_source_entries,
        "unmapped_target_fields": unmapped_target_entries,
        "unmapped_source_count": len(final_unmapped_source),
        "unmapped_target_count": len(final_unmapped_target),
        "compatibility_issues": compatibility_issues,
        "compatibility_score": compatibility_score,
        "export_recommendations": export_recommendations,
        "overall_assessment": overall_assessment,
    }