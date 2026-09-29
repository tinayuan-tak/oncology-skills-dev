"""C0b facet builder — opportunity_drivers. STUB declared by the C0a (#1995) L4 skeleton.

WILL BUILD: the claims that make the target interesting, EACH citing its L2/L3 claim ref (docs §"The six
core L4 products" #2). One driver per resolved positive property, ranked deterministically.

Uniform facet-builder contract (see schema.py / assembler.FACET_BUILDERS):

    build(ctx: L4Context) -> Optional[dict]
        Return a facet-result dict — ``{"facet","layer","statements":[schema.statement(...)],...}`` — or
        None when the facet does not resolve (omitted -> byte-stable). Every emitted statement MUST cite
        resolvable claim refs (schema.statement); the assembler validates traceability and raises on an
        unresolvable ref.

Until built this returns None. A child implements ``build`` + flips ``BUILT`` in THIS module only — no
edit to assembler.FACET_BUILDERS or schema is needed, so the fan-out is collision-free.
"""

from __future__ import annotations

from typing import Optional

from _skills_common.l4_synthesis.context import L4Context

BUILT = False


def build(ctx: L4Context) -> Optional[dict]:  # noqa: ARG001
    return None
