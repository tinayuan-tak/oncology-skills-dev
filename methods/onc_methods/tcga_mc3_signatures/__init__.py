"""tcga_mc3_signatures — per-indication mutational-signature (mutagenic-process) cohort context.

Verdict-inert companion facet (tier: indication, entity_grain: cohort). See cli.py for the pipeline
and read.py for the card reader entry (read_mutational_signature_context).
"""

from .read import METHOD_VERSION, read_mutational_signature_context

__all__ = ["read_mutational_signature_context", "METHOD_VERSION"]
