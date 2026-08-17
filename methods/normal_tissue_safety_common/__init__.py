"""Shared normal-tissue safety helpers (single source of truth for the essential-organ set)."""
from .essential_organs import (  # noqa: F401
    CANONICAL_VITAL_ORGANS,
    S1_3_REQUIRED_ORGANS,
    GTEX_CROSSWALK,
    HPA_CROSSWALK,
    SC_NORMAL_CROSSWALK,
    GTEX_ESSENTIAL_TISSUES,
    HPA_ESSENTIAL_TISSUES,
    SC_NORMAL_ESSENTIAL_TISSUES,
    required_names,
)
