"""pathway_node_leverage — COMPARATIVE facet: is the target the best NODE to hit, or is it dominated
by a more-dependent / more-tractable member of its neighbourhood (complex / pathway lens)?

SOFT, verdict-INERT context (DepMap-Chronos-derived → never a killer, never raises certainty). Feeds
the differentiation axis. Corrections: common-essential exclusion, tractability-yield (Pharos TDL),
noise-separation; LINEAGE-SCOPED. See docs/design/PATHWAY_NODE_LEVERAGE_SPEC.md (target-contracts).
tier: comparative.
"""

from .read import METHOD_VERSION, read_node_leverage  # noqa: F401
