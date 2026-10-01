#!/usr/bin/env python
"""genomic-alteration-profile component-scorecard adapter (PR-1c of epic SK#2210 / #1507).

Writes EXACTLY ``scorecard/genomic-alteration-profile.json`` (the one-file-per-skill contract of
``_skills_common.component_scorecard``); never touches ``SCORECARD.md`` (that is the aggregate
entrypoint ``scripts/regenerate_scorecard.py``) and never a sibling skill's shard.

## Scope of THIS adapter

PR-1c built the SK#1941-style EXPORTED evidence-package sections for the GENOMIC domain
(``source_properties`` L2a + the ``recurrence_concordance`` ``integrated_properties`` island L2b, both
under ``--emit-envelope`` via ``run.py::_evidence_sections``), replicating the safety (PR-1a) and
dependency (PR-1b) seeds. So the L2a and L2b cells move from NOT-ASSESSED to BUILT-but-UNMEASURED. They
do NOT move to GREEN: being built is not being measured, and a criterion promoted on the strength of the
layer merely existing is the fail-open shape this scorecard exists to refuse (``cell_rollup``:
built=True + any NULL still rolls up NULL).

L1, L3 and L4 are deliberately LEFT at the all-NULL baseline (``built=None``): PR-1c is the L2a/L2b
substrate item and does not build an L1 disposition/panel assessment, an L3d story object, or an L4
synthesis layer for this skill. Claiming any of them here would be a measurement this issue did not
make.

This is a pure L2-seed adapter — the whole BUILT-but-UNMEASURED shape (L2a/L2b built + all-NULL,
L1/L3/L4 at baseline) is the shared ``component_scorecard.build_l2_seed_shard`` factory; this file is
just the per-skill data literal (the two cell descriptions + the layers' structural pins) + the call.
The committed shard is reconciled byte-for-byte against ``build_shard()`` by
``tests/test_scorecard_shard.py``, so a hand-edit that drifts from this adapter reds — the shard is a
live function of this code, not a fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
REPO_ROOT = SKILLS_ROOT.parent
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common import component_scorecard as cs  # noqa: E402

SKILL = "genomic-alteration-profile"

# ── Per-skill data literal: the two L2 cell descriptions + each layer's structural pins ─────────────
# L2a/L2b are BUILT by PR-1c (epic SK#2210 / #1507) but UNMEASURED — the exemplar's L2a/L2b measurement
# machinery (tumor-presence's envelope_rows / envelope_checks) has no genomic counterpart yet, so every
# criterion stays NULL with the shared null_reason (see cs.l2_seed_null_reason). The structural pins
# that DO exist are correctness guards on the export, not a measurement.
_L2A_DESC = (
    "L2a = source_properties (SK#1941-shape EXPORTED section, --emit-envelope), built by PR-1c "
    "of epic SK#2210 / #1507: 7 per-source observational properties "
    "(genomic_claims.py::_SOURCE_PROPERTY_RECIPES_GENOMIC), governed by "
    "contracts/vocabularies/property_catalog/genomic.yaml. BUILT, NOT MEASURED — every criterion "
    "NULL with its reason (see cs.l2_seed_null_reason)."
)
_L2B_DESC = (
    "L2b = integrated_properties (SK#1941-shape EXPORTED section), built by PR-1c of epic "
    "SK#2210 / #1507: the recurrence_concordance island (SK#1629, MC3 exome x GENIE panel). "
    "BUILT, NOT MEASURED — every criterion NULL with its reason."
)
_STRUCTURAL_PINS = {
    "L2a": [
        "skills/genomic-alteration-profile/tests/test_evidence_package_sections.py",
        "contracts/tests/validators/test_property_catalog.py (sweeps genomic.yaml)",
        "contracts/tests/validators/test_claim_axis_enum.py (genomic.* resolves reconciliation)",
    ],
    "L2b": [
        "skills/genomic-alteration-profile/tests/test_evidence_package_sections.py",
    ],
}


def build_shard() -> cs.SkillShard:
    """Build the genomic-alteration-profile scorecard shard in memory. DETERMINISTIC — no live reads:
    only L2a/L2b move off the baseline, and they move to a fixed BUILT-but-UNMEASURED state."""
    return cs.build_l2_seed_shard(SKILL, _L2A_DESC, _L2B_DESC, _STRUCTURAL_PINS)


def main() -> int:
    scorecard_dir = REPO_ROOT / cs.SCORECARD_DIRNAME
    shard = build_shard()
    path = cs.write_skill_shard(scorecard_dir, shard)
    print(f"[genomic-alteration-profile scorecard adapter] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
