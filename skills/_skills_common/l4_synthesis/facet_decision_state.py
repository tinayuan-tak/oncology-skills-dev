"""Facet builder — decision_state (L4b — the TIP of the iceberg only). STUB declared by C0a (#1995).

WILL BUILD (docs §"L4a / L4b"): given the current decision STAGE (ctx.stage), the state of the program —
``{stage, status, rationale}``. Deliberately small: the same science supports different calls by stage
(early discovery "proceed to characterize" vs candidate nomination "insufficient evidence"), so the stage
is explicit and this is the tip, never the main output. Its rationale cites the claim refs it rests on.

Uniform facet-builder contract: ``build(ctx) -> Optional[dict]`` returning a facet-result dict (with a
``decision_state`` sub-object + ``statements`` each citing resolvable claim refs) or None. See schema.py /
assembler.FACET_BUILDERS. Until built this returns None; a child flips ``BUILT`` + implements ``build`` in
THIS module only.
"""

from __future__ import annotations

from typing import Optional

from _skills_common.l4_synthesis.context import L4Context

BUILT = False


def build(ctx: L4Context) -> Optional[dict]:  # noqa: ARG001
    return None
