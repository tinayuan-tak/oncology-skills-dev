"""_skills_common.scope — retained only for the DEFAULT_CONTRACTS_REPO back-compat alias.

The IDAS multi-indication machinery that once lived here (the Scope dataclass, ScopeError,
parse_cli_scope, resolve_bucket, ScopeMode, and the idas-indication / strategic-bucket loaders) was
never consumed by production code — a full cross-repo search found its only references in this module's
own unit test — so it was removed 2026-09-05. The sole live export, DEFAULT_CONTRACTS_REPO, now lives in
_skills_common.paths (the single-source-of-truth for sibling-repo roots) and is re-exported here so the
existing `from _skills_common.scope import DEFAULT_CONTRACTS_REPO` importers (evidence_graph,
evidence_salience, certainty_corroboration, functional-requirement/run.py, several tests) are unaffected.

The IDAS multi-indication design still lives in target-contracts docs/design/IDAS_SUBTYPE_PIPELINE.md;
re-introduce a typed Scope here if/when that pipeline is actually wired.
"""
from __future__ import annotations

from _skills_common.paths import DEFAULT_CONTRACTS_REPO  # noqa: F401  (back-compat re-export)
