"""dgidb_drug_gene — per-target known-drug / druggable-category tractability (PHARMACOLOGY leg).

The tractability-small-molecule gate's structure leg (structure-features-static) says "is there a
druggable HANDLE"; this leg says "has a drug actually been catalogued against the target, and is it
in a recognized druggable-genome category". Reads dgidb-drug-gene-per-gene-v1 (gene-symbol keyed) and
emits known_drug_tractability_class {approved_drug_tractable / clinically_actionable /
druggable_genome / interaction_only / category_only / no_known_drug_evidence}. Absence = coverage
gap, never undruggable (measured-vs-null discipline).

METHOD_VERSION 0.1.0.
"""

from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import known_drug_tractability_for_gene  # noqa: E402,F401
