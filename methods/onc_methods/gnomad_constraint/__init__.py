"""gnomad_constraint — gnomAD gene LoF-constraint reader (germline safety axis).

Backs the `gnomad-lof-constraint` card (call: gnomad-constraint-lookup). Reads the
landed derived product `gnomad-constraint-per-gene-v1` (gene-keyed, per-gene-
representative distillation of the gnomAD v4.1.1 constraint source) and emits the
constraint_class + pLI/LOEUF/z-scores the card contract declares.

Before this module existed, the compose-dashboard dispatcher imported `methods.gnomad_constraint`
(which was absent), so the framework's ONE wired safety axis resolved `data_unavailable`. This
module makes the germline safety arm actually fire.
"""

from .read import read_target_summary  # noqa: F401
