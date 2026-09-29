"""C0e facet builder — modality_implications. STUB declared by the C0a (#1995) L4 skeleton.

WILL BUILD (docs §"The six core L4 products" #4): PER MODALITY (adc / tce / small_molecule / ...) a
``{opportunity, liability, critical_unknown}`` — capturing WHY different modalities see the same biology
differently, NOT a scalar ``adc_fit = moderate``. Frame on the way in, VIEW on the way out: this reorganizes
the one synthesis object, it does not re-derive it. Each cell cites its claim ref.

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
