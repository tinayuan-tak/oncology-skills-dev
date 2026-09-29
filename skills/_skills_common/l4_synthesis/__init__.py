"""l4_synthesis — the L4 decision-facing target-synthesis layer (epic #1986).

L4 integrates the domain interpretations (L3d) and decision frames (L3f) into a coherent, claim-ID-
traceable target/program story. It is a DETERMINISTIC, verdict-INERT, facet-based VIEW over the already-
emitted L2/L3 evidence — NO new measurement, NO LLM authorship of this layer, and it moves NO existing
emitted field.

C0a (#1995) lands: the facet-object schema (``schema``), the read-over context + claim-ID resolver
(``context``), the assembler skeleton (``assembler``) with ONE module per facet builder, and the
thesis+archetype facet built end-to-end (``facet_thesis_archetype``). The remaining facet modules are
declared stubs that C0b–C0f flip on collision-free.

Public entry point::

    from _skills_common.l4_synthesis import assemble_target_synthesis
    synthesis = assemble_target_synthesis(decision_json)   # None when nothing resolves
"""

from __future__ import annotations

from _skills_common.l4_synthesis.assembler import (
    FACET_BUILDERS,
    L4TraceabilityError,
    assemble_target_synthesis,
    unresolved_refs,
)
from _skills_common.l4_synthesis.context import L4Context, read_context, resolve_ref

__all__ = [
    "assemble_target_synthesis",
    "unresolved_refs",
    "FACET_BUILDERS",
    "L4TraceabilityError",
    "L4Context",
    "read_context",
    "resolve_ref",
]
