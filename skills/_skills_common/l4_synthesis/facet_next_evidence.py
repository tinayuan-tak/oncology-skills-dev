"""C0f facet builder — next_evidence / value-of-information. STUB declared by C0a (#1995).

WILL BUILD (docs §"The six core L4 products" #6): what additional evidence would most change or resolve
the assessment — ``{evidence, resolves:[frames/unknowns]}`` — the step that makes L4 more than reporting.
Derived deterministically from the critical_unknowns facet + the NOT_ASSESSED domains; each item cites the
unknown / claim ref it would resolve.

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
