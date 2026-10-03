# matching/dataset_matcher.py  (NEW file — shim only)
"""Backwards-compatibility shim. Import from entity_matcher instead."""
import warnings
warnings.warn(
    "dataset_matcher is deprecated; use entity_matcher",
    DeprecationWarning,
    stacklevel=2,
)
from compatibility_analyzer.matching.entity_matcher import *  # noqa: F401,F403
from compatibility_analyzer.matching.entity_matcher import (
    predict_target_entity,
    predict_target_model,
)