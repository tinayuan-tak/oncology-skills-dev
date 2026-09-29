"""C0d facet builder — critical_unknowns (a FIRST-CLASS product, not an appendix). STUB from C0a (#1995).

WILL BUILD (docs §"The six core L4 products" #5): each unknown as
``{question, status, affects:[frames], decision_importance, decision_critical, current_status,
claim_ids}`` where ``status ∈ schema.UNKNOWN_STATUS`` (KNOWN | UNKNOWN | CONTRADICTED | NOT_ASSESSED) and
``decision_critical`` flags the decision-critical unknowns apart from low-priority gaps. Honest
missingness — an unassessed domain is NOT_ASSESSED, never negative evidence.

Uniform facet-builder contract: ``build(ctx) -> Optional[dict]`` returning a facet-result dict (with
``statements`` each citing resolvable claim refs) or None. See schema.py / assembler.FACET_BUILDERS.
Until built this returns None; a child flips ``BUILT`` + implements ``build`` in THIS module only.
"""

from __future__ import annotations

from typing import Optional

from _skills_common.l4_synthesis.context import L4Context

BUILT = False


def build(ctx: L4Context) -> Optional[dict]:  # noqa: ARG001
    return None
