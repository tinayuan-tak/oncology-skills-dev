"""aact_clinical_precedent — clinical-trial precedent for a (target, indication) from AACT.

Composes indication_crosswalk mesh_terms + dgidb-drug-target-directional-v1 (drug engages target) +
aact-oncology-trial-precedent-* (per condition x drug trial rollup) into the clinical-precedent
card's fields (highest_clinical_stage, approved_agents, n_active_trials, notable_failures).
Precedent semantics: a drug that ENGAGES the target counts (directional filter), not sole-target.

METHOD_VERSION 0.1.0.
"""

from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import read_clinical_precedent  # noqa: E402,F401
