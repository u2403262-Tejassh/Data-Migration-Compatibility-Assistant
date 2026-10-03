"""
migration_catalog/catalog_manager.py

Two-layer migration catalog system.

Layer 1 (this module): Static curated catalog of migration-relevant entities
and their known field mappings for well-understood system pairs.

Layer 2: The existing LLM reasoning, invoked only for fields NOT covered by
the catalog (custom fields, unusual configurations).

Usage:
    catalog = get_catalog("odoo", "salesforce")
    if catalog:
        entities = catalog.get_migration_entities()
        fields   = catalog.get_migration_fields("res.partner")
        mappings = catalog.get_known_mappings("res.partner", "Contact")
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CATALOG_DIR = Path(__file__).parent / "data"

# Aliases so connectors can pass their raw system names
_SYSTEM_ALIASES = {
    "odoo": "odoo",

    "salesforce": "salesforce",
    "sf": "salesforce",

    "oracle": "oracle",
    "oracle fusion": "oracle",
    "oracle_fusion": "oracle",     # <-- IMPORTANT

    "file": "file",
    "csv": "file",
    "csv/xlsx": "file",
}

# Map (source_system, target_system) → JSON filename
_CATALOG_FILES = {

    ("odoo", "salesforce"): "odoo_salesforce.json",
    ("salesforce", "odoo"): "salesforce_odoo.json",

    ("oracle", "odoo"): "oracle_odoo.json",
    ("odoo", "oracle"): "odoo_oracle.json",

    ("oracle", "salesforce"): "oracle_salesforce.json",
    ("salesforce", "oracle"): "salesforce_oracle.json",
    
}


def _normalize_system(name: str) -> str:
    return _SYSTEM_ALIASES.get(name.lower().strip(), name.lower().strip())


def _load_catalog_data(source_system: str, target_system: str) -> Optional[dict]:
    key = (_normalize_system(source_system), _normalize_system(target_system))
    filename = _CATALOG_FILES.get(key)
    if not filename:
        return None

    path = _CATALOG_DIR / filename
    if not path.exists():
        logger.warning("Catalog file not found: %s", path)
        return None

    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Failed to load catalog %s: %s", path, exc)
        return None


class MigrationCatalog:
    """
    Catalog for a specific (source_system, target_system) pair.

    Provides:
      - get_migration_entities()  → list of {source_model, target_model, ...}
      - get_migration_fields(source_model)  → list of migration-relevant field names
      - get_known_mappings(source_model, target_model)
            → list of {source_field, target_field, confidence, reason}
      - filter_source_schema(schema)  → schema with only catalog fields
      - filter_target_schema(schema, target_model)  → schema with only catalog fields
      - inject_catalog_mappings(exact_result, source_model, target_model)
            → adds catalog mappings to the deterministic pass result
    """

    def __init__(self, data: dict):
        self._data = data
        # Index entities by source_model for fast lookup
        self._by_source: dict[str, list[dict]] = {}
        for entity in data.get("entities", []):
            src = entity["source_model"]
            self._by_source.setdefault(src, []).append(entity)

    # ------------------------------------------------------------------
    # Entity helpers
    # ------------------------------------------------------------------

    def get_migration_entities(self) -> list[dict]:
        """Return all catalogued entities as list of dicts."""
        return self._data.get("entities", [])

    def get_catalogued_source_models(self) -> list[str]:
        """Return distinct source model names present in the catalog."""
        return list(self._by_source.keys())

    def find_entity(self, source_model: str, target_model: str = None) -> Optional[dict]:
        """
        Find the best catalog entry for (source_model, target_model).
        If target_model is None, returns the first entry for source_model.
        """
        candidates = self._by_source.get(source_model, [])
        if not candidates:
            return None
        if target_model is None:
            return candidates[0]
        for c in candidates:
            if c["target_model"].lower() == target_model.lower():
                return c
        return candidates[0]  # fall back to first match

    # ------------------------------------------------------------------
    # Field helpers
    # ------------------------------------------------------------------

    def get_migration_fields(self, source_model: str, target_model: str = None) -> list[str]:
        """
        Return the list of migration-relevant source field names for an entity.
        Returns empty list if entity is not in the catalog.
        """
        entry = self.find_entity(source_model, target_model)
        if not entry:
            return []
        return list(entry.get("fields", {}).keys())

    def get_known_mappings(
        self,
        source_model: str,
        target_model: str = None,
    ) -> list[dict]:
        """
        Return deterministic field mappings from the catalog for this entity pair.

        Returns list of:
          {source_field, target_field, confidence, reason}
        """
        entry = self.find_entity(source_model, target_model)
        if not entry:
            return []

        mappings = []
        for source_field, info in entry.get("fields", {}).items():
            if not isinstance(info, dict):
                continue
            target_field = info.get("target")
            if not target_field:
                continue
            reason = "catalog: known migration mapping"
            if info.get("notes"):
                reason = f"catalog: {info['notes']}"
            mappings.append({
                "source_field": source_field,
                "target_field": target_field,
                "confidence": info.get("confidence", 0.8),
                "reason": reason,
            })
        return mappings

    # ------------------------------------------------------------------
    # Schema filtering
    # ------------------------------------------------------------------

    def filter_source_schema(
        self,
        schema: dict,
        source_model: str,
        target_model: str = None,
    ) -> dict:
        """
        Return a copy of schema containing only catalog-listed source fields
        (plus any fields that were already marked as selectable business fields).

        Falls back to the full schema if the entity is not in the catalog.
        """
        catalog_fields = self.get_migration_fields(source_model, target_model)
        if not catalog_fields:
            return schema  # Not in catalog — don't filter

        catalog_set = set(catalog_fields)
        all_fields = schema.get("fields", {})

        # Keep catalog fields that exist in the actual schema
        filtered = {
            k: v for k, v in all_fields.items()
            if k in catalog_set
        }

        # Also keep custom fields (x_ prefix in Odoo; __c suffix in Salesforce)
        for k, v in all_fields.items():
            if k.startswith("x_") or k.endswith("__c"):
                filtered[k] = v

        result = dict(schema)
        result["fields"] = filtered
        result["field_count"] = len(filtered)
        result["catalog_filtered"] = True
        result["catalog_field_count"] = len(catalog_fields)
        return result

    def filter_target_schema(
        self,
        schema: dict,
        target_model: str,
        source_model: str = None,
    ) -> dict:
        """
        Return a copy of the target schema containing only the fields that
        appear as targets in the catalog mappings, plus required fields.

        Falls back to the full schema if the entity is not in the catalog.
        """
        entry = self.find_entity(source_model or "", target_model) if source_model else None

        # Build target field set from all catalog entries for this target_model
        target_fields_in_catalog: set[str] = set()
        for entity in self._data.get("entities", []):
            if entity.get("target_model", "").lower() == target_model.lower():
                for field_info in entity.get("fields", {}).values():
                    if isinstance(field_info, dict) and field_info.get("target"):
                        target_fields_in_catalog.add(field_info["target"])

        if not target_fields_in_catalog:
            return schema  # Not in catalog — don't filter

        all_fields = schema.get("fields", {})

        # Keep catalog target fields + required fields + custom fields
        filtered = {}
        for k, v in all_fields.items():
            if k in target_fields_in_catalog:
                filtered[k] = v
            elif v.get("required"):
                filtered[k] = v
            elif k.endswith("__c"):
                filtered[k] = v

        result = dict(schema)
        result["fields"] = filtered
        result["field_count"] = len(filtered)
        result["catalog_filtered"] = True
        return result

    # ------------------------------------------------------------------
    # Reasoner integration
    # ------------------------------------------------------------------

    def inject_catalog_mappings(
        self,
        exact_result: dict,
        source_model: str,
        target_model: str = None,
    ) -> dict:
        """
        Inject catalog-known mappings into the deterministic pass result,
        skipping any fields already mapped by exact-name matching.

        Mutates and returns the exact_result dict.
        """
        catalog_mappings = self.get_known_mappings(source_model, target_model)
        if not catalog_mappings:
            return exact_result

        already_mapped_source = set(exact_result.get("mapped_source_fields", set()))
        already_mapped_target = set(exact_result.get("mapped_target_fields", set()))

        # Available target fields to validate against
        available_target = set(exact_result.get("unmapped_target_fields", []))
        # Also include currently mapped targets (for validation only)
        all_known_targets = already_mapped_target | available_target

        added_source: set[str] = set()
        added_target: set[str] = set()

        for mapping in catalog_mappings:
            src = mapping["source_field"]
            tgt = mapping["target_field"]

            # Skip if source already mapped
            if src in already_mapped_source or src in added_source:
                continue
            # Skip if target already mapped
            if tgt in already_mapped_target or tgt in added_target:
                continue
            # Skip if target field doesn't exist in the actual target schema
            if all_known_targets and tgt not in all_known_targets:
                continue
            # Skip if source field not in unmapped source fields
            if src not in exact_result.get("unmapped_source_fields", []):
                continue

            exact_result["mapping_suggestions"].append(mapping)
            added_source.add(src)
            added_target.add(tgt)

        # Update unmapped lists
        exact_result["unmapped_source_fields"] = [
            f for f in exact_result.get("unmapped_source_fields", [])
            if f not in added_source
        ]
        exact_result["unmapped_target_fields"] = [
            f for f in exact_result.get("unmapped_target_fields", [])
            if f not in added_target
        ]
        exact_result.setdefault("mapped_source_fields", set()).update(added_source)
        exact_result.setdefault("mapped_target_fields", set()).update(added_target)

        return exact_result

    # ------------------------------------------------------------------
    # Residual field helpers (for LLM pass 2)
    # ------------------------------------------------------------------

    def get_residual_source_fields(
        self,
        schema: dict,
        source_model: str,
        target_model: str = None,
    ) -> list[str]:
        """
        Return source fields that are NOT in the catalog — these are the ones
        the LLM should attempt to map (custom fields, unusual configs).
        """
        catalog_fields = set(self.get_migration_fields(source_model, target_model))
        all_fields = list(schema.get("fields", {}).keys())
        return [f for f in all_fields if f not in catalog_fields]


# ------------------------------------------------------------------
# Module-level factory
# ------------------------------------------------------------------

_catalog_cache: dict[tuple, Optional["MigrationCatalog"]] = {}


def get_catalog(source_system: str, target_system: str) -> Optional[MigrationCatalog]:
    """
    Return a MigrationCatalog for the given system pair, or None if
    no catalog exists for that pair.

    Results are cached in-process.
    """
    key = (_normalize_system(source_system), _normalize_system(target_system))
    if key in _catalog_cache:
        return _catalog_cache[key]

    data = _load_catalog_data(source_system, target_system)
    catalog = MigrationCatalog(data) if data else None
    _catalog_cache[key] = catalog

    if catalog:
        entity_count = len(catalog.get_migration_entities())
        logger.info(
            "Loaded migration catalog: %s→%s  (%d entities)",
            source_system, target_system, entity_count,
        )
    else:
        logger.debug(
            "No migration catalog available for %s→%s",
            source_system, target_system,
        )

    return catalog
