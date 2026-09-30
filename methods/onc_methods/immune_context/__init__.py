"""immune_context — per-indication tumor immune-context (T-cell infiltration) for the biologics
EFFECTOR arm. classify = pure CIBERSORT-fraction → immune-hot/cold classifier; read = S3 boundary.
Consumed by the immune-context skill (the effector companion to surface-modality-fit).
"""

from .antigen_conditioned import read_antigen_conditioned  # noqa: E402,F401 — v2 facet entry
from .read import read_immune_context  # noqa: E402,F401 — live-dispatcher entry
