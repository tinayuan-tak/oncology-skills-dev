"""gnomad_constraint — gnomAD gene LoF-constraint reader (gate-F germline safety axis).

Backs the `gnomad-lof-constraint` card (call: gnomad-constraint-lookup). Reads the
landed source manifest `gnomad-constraint-snapshot-2026-07-02` (v4.1 constraint_metrics.tsv,
gene-level, canonical/MANE transcript) and emits the constraint_class + pLI/LOEUF/z-scores
the card contract declares.

Before this module existed, the compose-dashboard dispatcher imported `methods.gnomad_constraint`
(which was absent), so the framework's ONE wired safety axis resolved `data_unavailable`. This
module makes gate F's germline arm actually fire.
"""

from .read import read_target_summary  # noqa: F401
