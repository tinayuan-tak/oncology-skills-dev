"""risk_projection — the re-homed DETERMINISTIC 6-dim risk core (moved 2026-09-03 from
literature-risk-assessment/scripts/risk_rollup.py to _skills_common so target-profile can compute
target_report.risk_6dim from in-memory sub_results). Pins the CONTRACT (modality-conditioned
conjunction, reproducibility, engine-blind dims, card-fed clinical/commercial) — not the thresholds —
and the in-memory package assembler's byte-parity with the on-disk evidence-package cards.
"""

from __future__ import annotations

import sys
from pathlib import Path

COMMON = Path(__file__).resolve().parent.parent
if str(COMMON.parent) not in sys.path:
    sys.path.insert(0, str(COMMON.parent))  # skills/

from _skills_common.risk_projection import (  # noqa: E402
    deterministic_bins,
    assemble_risk_package,
    _mod,
)


def _pkg(sub_verdicts: dict, cards: list | None = None) -> dict:
    return {"synthesis": {"sub_verdicts": {k: {"verdict": v} for k, v in sub_verdicts.items()}}, "cards": cards or []}


# --------------------------------------------------------------- deterministic_bins (the pure core)


def test_safety_conjunction_fixes_false_low():
    """The validated FOLR1 fix: on-target-safety may read tolerant, but a critical-organ normal-tissue
    liability under a SURFACE modality escalates safety to HIGH (esc=2) — a 1:1 on-target-only map misses
    it. Conjunction, not a single lookup."""
    pkg = _pkg(
        {"safety": "tolerant_reduced_safety_risk"},
        [{"card_id": "normal-tissue-liability-gtex", "interpretation_call": "critical_organ_liability"}],
    )
    assert deterministic_bins(pkg, "adc")["safety"]["bin"] == "HIGH"
    # same signal, non-surface modality → esc=1 → MED (still raised above the tolerant base LOW)
    assert deterministic_bins(pkg, "small_molecule")["safety"]["bin"] == "MED"


def test_deterministic_bin_is_reproducible():
    pkg = _pkg({"safety": "highly_constrained_safety_concern", "dependency": "concordant_dependent"})
    assert deterministic_bins(pkg, "small_molecule") == deterministic_bins(pkg, "small_molecule")


def test_pan_essential_is_med_biological_not_high():
    """pan_essential_killer is a dependency but not tumor-selective — its tox routes to SAFETY, so
    biological is MED, not HIGH (only non_dependent is HIGH biological risk)."""
    pkg = _pkg({"dependency": "pan_essential_killer", "mechanism": "well_characterized"})
    assert deterministic_bins(pkg, "small_molecule")["biological"]["bin"] == "MED"
    pkg_nd = _pkg({"dependency": "non_dependent", "mechanism": "well_characterized"})
    assert deterministic_bins(pkg_nd, "small_molecule")["biological"]["bin"] == "HIGH"


def test_druggability_strong_tractability_is_low():
    for v in ("well_covered", "chemically_confirmed_genetic", "measured_potent_ligand", "chemically_active"):
        pkg = _pkg({"tractability_sm": v})
        assert deterministic_bins(pkg, "small_molecule")["druggability"]["bin"] == "LOW", v


def test_clinical_bin_from_precedent_card():
    hi = _pkg({}, [{"card_id": "clinical-precedent", "summary": {"notable_failures": True}}])
    assert deterministic_bins(hi, "small_molecule")["clinical"]["bin"] == "HIGH"
    lo = _pkg({}, [{"card_id": "clinical-precedent", "summary": {"highest_clinical_stage": "approved"}}])
    assert deterministic_bins(lo, "small_molecule")["clinical"]["bin"] == "LOW"


def test_commercial_bin_from_competitor_card():
    hi = _pkg({}, [{"card_id": "competitor-landscape", "summary": {"competitor_class": "approved_competitor"}}])
    assert deterministic_bins(hi, "small_molecule")["commercial"]["bin"] == "HIGH"
    lo = _pkg({}, [{"card_id": "competitor-landscape", "summary": {"competitor_class": "no_known_competitor"}}])
    assert deterministic_bins(lo, "small_molecule")["commercial"]["bin"] == "LOW"


def test_engine_blind_dims_present_when_unfed():
    dims = deterministic_bins(_pkg({}), "small_molecule")
    assert set(dims) == {"safety", "biological", "druggability", "clinical", "commercial", "translational"}
    # translational is ALWAYS engine-blind; clinical/commercial engine-blind when their card is absent
    for d in ("translational", "clinical", "commercial"):
        assert dims[d]["bin"] == "ENGINE-BLIND"


def test_raw_loeuf_surfaced_in_safety_chain():
    pkg = _pkg(
        {"safety": "highly_constrained_safety_concern"},
        [{"card_id": "gnomad-lof-constraint", "summary": {"loeuf_score": 0.12}}],
    )
    chain = deterministic_bins(pkg, "small_molecule")["safety"]["chain"]
    assert any("0.12" in str(detail) for _src, detail, _lvl in chain)


# --------------------------------------------------------------- assemble_risk_package (in-memory pkg)


def _sr(short, verdict, cards=None):
    return {short: {"verdict": (verdict, "r"), "cards": cards or []}}


def test_assemble_from_sub_results_feeds_cards_and_verdicts():
    """The in-memory assembler unions present cards (normalized like the on-disk package) + extracts the
    verdict string — so a clinical-precedent card carried on a sub-result reaches the clinical bin."""
    sub_results = {
        **_sr("safety", "highly_constrained_safety_concern"),
        **_sr(
            "differentiation",
            "landscape",
            [
                {
                    "card_id": "clinical-precedent",
                    "summary": {"highest_clinical_stage": "approved"},
                    "interpretation_call": "x",
                }
            ],
        ),
    }
    pkg = assemble_risk_package(sub_results)
    dims = deterministic_bins(pkg, _mod("small_molecule"))
    assert dims["safety"]["bin"] == "HIGH"  # verdict string threaded
    assert dims["clinical"]["bin"] == "LOW"  # present card threaded through _envelope_card_present


def test_assemble_skips_missing_cards():
    """A _missing card must be excluded from the package (matching _write_evidence_package's present-only
    union) — so a would-be competitor card that didn't resolve leaves commercial ENGINE-BLIND."""
    sub_results = _sr(
        "differentiation",
        "landscape",
        [{"card_id": "competitor-landscape", "summary": {"competitor_class": "approved_competitor"}, "_missing": True}],
    )
    pkg = assemble_risk_package(sub_results)
    assert pkg["cards"] == []  # skipped
    assert deterministic_bins(pkg, "small_molecule")["commercial"]["bin"] == "ENGINE-BLIND"


def test_assemble_bad_input_raises_for_caller_to_catch():
    """assemble_risk_package is pure; a non-dict caller error surfaces (build_risk_6dim wraps it)."""
    import pytest

    with pytest.raises(AttributeError):
        assemble_risk_package("not-a-dict")
