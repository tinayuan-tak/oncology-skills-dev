#!/usr/bin/env python3
"""translational-readiness — Phase-J PARTIAL skill (graduated 2026-08-14, scientific-gap #1).

Was a pure placeholder (emit_placeholder). Now PARTIALLY wired: it composes the
target-model-availability card (HCMI patient-derived model coverage per indication) — the
"can I preclinically validate a nomination in this indication?" leg of translational readiness.

DESCRIPTIVE (verdict_fn=None): like target-intrinsic, this skill emits no nomination verdict — model
availability is translational CONTEXT that informs confidence, not a gate. Uses the shared
run_wired_skill dispatcher; skill-specific logic reduces to CARDS + a headline callback.

STILL PARTIAL: the PD-assay, imaging-tracer, and INTERNAL Takeda models (PDX/organoid/GEMM) legs
remain un-wired (those catalogs are not in data-catalog) — surfaced in partial_status_note. The
public HCMI model-availability card is the first real translational signal wired here; the
genotype-MATCHED refinement (does an available model carry THIS target's alteration?) is a v2.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field


SKILL_NAME = "translational-readiness"
SKILL_VERSION = "1.1.0"

CARDS = [
    "target-model-availability",   # scientific-gap #1 (2026-08-14): per-indication HCMI patient-derived
                                   # model coverage (organoid/next-gen cancer models). INDICATION-level,
                                   # target-independent translational cohort context. VERDICT-INERT.
]

QUESTION = ("How translationally ready is {target} in {indication} — are there patient-derived "
            "(HCMI organoid / next-generation cancer) models available to preclinically validate a "
            "nomination? (PD-assay, imaging-tracer, and internal-model legs remain un-wired.)")

# Honest partial-coverage note: the internal Takeda models registry (PDX/organoid/GEMM), PD-assay, and
# imaging-tracer catalogs are NOT in data-catalog, so those legs are still un-wired. Only the public
# HCMI model-availability leg is reflected in this decision.
PARTIAL_STATUS_NOTE = (
    "translational-readiness is status: partial — only the public HCMI model-availability leg is wired "
    "(target-model-availability card). The PD-assay, imaging-tracer, and INTERNAL Takeda models "
    "(PDX/organoid/GEMM) catalogs are not yet in data-catalog. Model availability is INDICATION-level "
    "(target-independent) translational context; genotype-matched model coverage is a v2."
)


def _headline(cards, fired, verdict_pair):
    """Descriptive translational-readiness context — model-availability fields from the composed card.
    No verdict spine (verdict_fn=None): translational readiness informs confidence/context, not a
    nomination. A composed consumer reads these as indication-grain translational context."""
    return {
        "model_availability_class":  get_card_field(cards, "target-model-availability",
                                          "model_availability_class"),
        "n_patient_derived_models":  get_card_field(cards, "target-model-availability",
                                          "n_patient_derived_models"),
        "primary_site_breakdown":    get_card_field(cards, "target-model-availability",
                                          "primary_site_breakdown"),
        "model_source":              get_card_field(cards, "target-model-availability", "source"),
    }


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",   # rules axis for loading; translational-readiness emits no verdict
        question=QUESTION,
        verdict_fn=None,                   # DESCRIPTIVE — model availability is translational context, not a gate
        headline_fn=_headline,
        partial_status_note=PARTIAL_STATUS_NOTE,
    ))
