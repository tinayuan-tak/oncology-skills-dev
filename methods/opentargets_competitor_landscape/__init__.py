"""opentargets_competitor_landscape — the competitor field for a (target, indication).

Reads the pinned Open Targets derived rollup (opentargets-target-competitor-drugs-per-gene-v1) for a
target, maps the framework's OncoTree indication -> EFO/MONDO ids via the indication_crosswalk EFO
lane, classifies each competitor drug's MODALITY (ADC / TCE / mAb / small-molecule / degrader / ...),
and aggregates to the competitor-landscape card's fields (competitor_class, highest_clinical_stage,
approved_agents, per-modality landscape). Reproducible against the OT release pin (as_of).

METHOD_VERSION 0.1.0.
"""
from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import read_competitor_landscape  # noqa: E402,F401
