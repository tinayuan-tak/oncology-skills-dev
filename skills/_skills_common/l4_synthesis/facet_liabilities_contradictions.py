"""C0c facet builder — liabilities AND contradictions (kept DISTINCT). STUB declared by C0a (#1995).

WILL BUILD two SEPARATE products (docs §"The six core L4 products" #3):
  * ``liabilities`` — adverse properties that count against the target (each cites its claim ref).
  * ``contradictions`` — evidence RELATIONSHIPS worth understanding (e.g. "TCGA broad-high / DepMap
    subset-high"), a ``{between:[claim_ref, claim_ref], note}`` — NOT a low score. Keeping these distinct
    is the load-bearing rule: a contradiction is a tension to surface, not a weakness to subtract.

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
