"""Facet builder — decision_dimensions (5R as FACETS of the one synthesis). STUB declared by C0a (#1995).

WILL BUILD (docs §"L4 object" ``decision_dimensions`` + §"Frame on the way in, view on the way out"): the
5R read — right_target / right_tissue / right_safety / right_patient / right_drug — as VIEWS that
reorganize the already-synthesized story, NOT a separate scoring system and NOT a scalar N/5. Each
dimension cites the claim refs its read rests on.

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
