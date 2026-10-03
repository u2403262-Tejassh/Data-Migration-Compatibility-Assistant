"""
matching/entity_matcher.py

Entity / model prediction for migration target selection.

Token budget fix:
  - prefilter_entity_catalog() reduces Salesforce's ~600 objects (13,000 tokens)
    to the top 50 keyword-matched candidates (~1,100 tokens) before the LLM call.
  - Source profile sent for entity matching uses field names + type only
    (no samples/patterns — not needed for entity identification).
"""

import json
import re

from compatibility_analyzer.utils.schema_utils import json_safe
from compatibility_analyzer.migration_catalog.catalog_manager import get_catalog

# Maximum entities sent to the LLM. Pre-filtering picks the most relevant ones.
MAX_CATALOG_CANDIDATES = 50

# Maximum source fields sent for entity matching.
# Entity identification needs field names + types only; samples are not required.
MAX_MATCH_SOURCE_FIELDS = 15

# Common English stop-words excluded from keyword scoring.
_STOP = frozenset({
    "the", "and", "for", "with", "not", "are", "has", "all", "can",
    "its", "that", "this", "will", "have", "from", "into", "more",
})


# ── Schema helpers ─────────────────────────────────────────────────────────

def source_schema_to_profile(source_schema):
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
        }

    return {
        "row_count": source_schema.get("row_count"),
        "column_count": len(columns),
        "columns": columns,
    }


def _compact_source_for_matching(source_schema) -> dict:
    """
    Ultra-compact source profile for entity matching.
    Only field name → type string. No samples, no pattern, no label.
    Keeps the LLM call well under the token budget.
    """
    profile = source_schema_to_profile(source_schema)
    columns = profile.get("columns", {})

    result = {}
    for field_name, meta in list(columns.items())[:MAX_MATCH_SOURCE_FIELDS]:
        result[field_name] = meta.get("dtype") or "unknown"

    return result


def compact_source_profile(source_profile):
    """Legacy shim — still used by older callers."""
    profile = source_schema_to_profile(source_profile)
    compact = {}
    for field_name, metadata in profile["columns"].items():
        compact[field_name] = {
            "type": json_safe(metadata.get("dtype")),
            "samples": json_safe(metadata.get("sample_values", [])[:2]),
        }
    return compact


# ── Entity catalog pre-filter ──────────────────────────────────────────────

def prefilter_entity_catalog(source_schema, entities, top_n=MAX_CATALOG_CANDIDATES):
    """
    Reduce a large entity catalog to the top `top_n` keyword-relevant candidates.

    Salesforce has ~600 queryable objects (≈ 13,000 tokens if sent in full).
    Keyword pre-filtering narrows this to ≤ 50 entries (≈ 1,100 tokens)
    without losing the most likely match.

    Algorithm:
      1. Extract keywords from source field names and entity name.
      2. Score each target entity by keyword overlap with name/model strings.
      3. Return the top_n highest-scoring entities.
         If all scores are 0 (no overlap), return the first top_n alphabetically.
    """
    if len(entities) <= top_n:
        return entities

    # ── Build source keyword set ───────────────────────────────────────────
    source_kw = set()

    entity_name = (
        source_schema.get("model")
        or source_schema.get("name")
        or source_schema.get("entity")
        or ""
    ).lower()
    source_kw.update(re.split(r"[_.\s:]+", entity_name))

    fields = (
        source_schema.get("fields")
        or source_schema.get("columns")
        or {}
    )
    for field_name in list(fields.keys())[:30]:
        # split_on_underscores
        source_kw.update(re.split(r"[_\s]+", field_name.lower()))
        # split camelCase: "AccountName" → ["Account", "Name"]
        source_kw.update(w.lower() for w in re.findall(r"[A-Z][a-z]+|[a-z]+", field_name))

    source_kw = {k for k in source_kw if len(k) > 2 and k not in _STOP}

    if not source_kw:
        return entities[:top_n]

    # ── Score entities ─────────────────────────────────────────────────────
    scored = []
    for entity in entities:
        label = (entity.get("name") or "").lower()
        model = (entity.get("model") or "").lower()

        entity_words = set(re.split(r"[_.\s:]+", label) + re.split(r"[_.\s:]+", model))
        entity_words.update(w.lower() for w in re.findall(r"[A-Z][a-z]+|[a-z]+", label))
        entity_words = {w for w in entity_words if len(w) > 2}

        score = len(source_kw & entity_words)
        scored.append((score, entity))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:top_n]]


def compact_entity_catalog(entities):
    return [
        {"model": json_safe(e["model"]), "name": json_safe(e["name"])}
        for e in entities
    ]


# ── Prompt builders ────────────────────────────────────────────────────────

def build_matching_prompt(source_profile, entities, target_system="target ERP"):
    compact_source = _compact_source_for_matching(source_profile)
    compact_entities = compact_entity_catalog(entities)

    return f"""ERP migration analyst task.

Identify the best target entity in {target_system} for this source dataset.

Return STRICT JSON ONLY:
{{"dataset_type":"string","predicted_model":"technical name","predicted_model_name":"human name","confidence":0.0,"reasoning":["reason"],"alternatives":[{{"model":"name","name":"label"}}]}}

SOURCE FIELDS (name:type):
{json.dumps(compact_source, separators=(',', ':'))}

TARGET ENTITIES:
{json.dumps(compact_entities, separators=(',', ':'))}
"""


def build_entity_matching_prompt(
    source_schema,
    entities,
    source_system="source ERP",
    target_system="target ERP",
):
    compact_source = _compact_source_for_matching(source_schema)
    compact_entities = compact_entity_catalog(entities)

    return f"""ERP migration analyst task.

Match source entity ({source_system}: {source_schema.get('model', 'unknown')}) to best target entity in {target_system}.

Return STRICT JSON ONLY:
{{"dataset_type":"string","predicted_model":"technical name","predicted_model_name":"human name","confidence":0.0,"reasoning":["reason"],"alternatives":[{{"model":"name","name":"label"}}]}}

SOURCE FIELDS (name:type):
{json.dumps(compact_source, separators=(',', ':'))}

TARGET ENTITIES:
{json.dumps(compact_entities, separators=(',', ':'))}
"""


# ── Main entry point ───────────────────────────────────────────────────────

def _normalize_system_name(name: str) -> str:
    """Minimal normalizer — mirrors workflow_controller.normalize_system."""
    n = name.strip().lower()
    if n in {"csv/xlsx", "csv", "xlsx", "file"}:
        return "file"
    if n == "oracle fusion":
        return "oracle"
    return n


def predict_target_entity(
    llm_client,
    source_schema,
    entities,
    source_system="source system",
    target_system="target ERP",
):
    # --- Catalog short-circuit: if we know this entity pair, skip the LLM ---
    source_model = (
        source_schema.get("model")
        or source_schema.get("entity")
        or ""
    )
    catalog = get_catalog(
        _normalize_system_name(source_system),
        _normalize_system_name(target_system),
    )
    if catalog and source_model:
        entry = catalog.find_entity(source_model)
        if entry:
            return {
                "dataset_type":          entry.get("source_name", source_model),
                "predicted_model":       entry["target_model"],
                "predicted_model_name":  entry.get("target_name", entry["target_model"]),
                "confidence":            0.95,
                "reasoning":             [
                    f"Known migration mapping from catalog: "
                    f"{source_model} → {entry['target_model']}",
                    entry.get("notes", ""),
                ],
                "alternatives":          [],
                "catalog_matched":       True,
            }
    # -----------------------------------------------------------------------

    # Pre-filter the catalog BEFORE building the prompt
    filtered_entities = prefilter_entity_catalog(source_schema, entities)

    is_file = (
        source_schema.get("system") == "file"
        or "columns" in source_schema
    )

    if is_file:
        prompt = build_matching_prompt(
            source_schema,
            filtered_entities,
            target_system=target_system,
        )
    else:
        prompt = build_entity_matching_prompt(
            source_schema,
            filtered_entities,
            source_system=source_system,
            target_system=target_system,
        )

    result = llm_client.generate_json(prompt)

    for key in ["dataset_type", "predicted_model", "predicted_model_name",
                "confidence", "reasoning", "alternatives"]:
        if key not in result:
            raise ValueError(f"LLM response missing required key: {key}")

    return result


def predict_target_model(llm_client, source_profile, models, target_system="target ERP"):
    """Legacy alias."""
    return predict_target_entity(
        llm_client, source_profile, models, target_system=target_system,
    )