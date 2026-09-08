"""opentargets_literature_floor — the pinned, reproducible per-target literature FLOOR.

Reads the pinned Open Targets derived product (opentargets-literature-per-target-v1) for a target and
returns per-source (europepmc / entity_lut) top-N PubMed PMID pointers (+ the europepmc text-mined
sentence), optionally scoping the europepmc lane to the indication via the indication_crosswalk EFO
lane. The never-empty, entity-normalized offline floor under the skills grounded layer's live lanes;
carries ZERO finding inference (deferred to the consuming LLM layer). Reproducible against the OT
release pin (as_of).

METHOD_VERSION 0.1.0.
"""

from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import aggregate_literature, read_literature_floor  # noqa: E402,F401
