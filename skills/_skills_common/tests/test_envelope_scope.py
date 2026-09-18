"""context.scope must reflect the actual request, not a hardcoded constant.

assemble_evidence_package() previously stamped context.scope = "cancer_type" unconditionally, so a
subtype-scoped run (which sets subgroup_spec to a strata list) emitted the SAME scope as an
indication-level run — context.scope was a constant, not information. It now derives from
subgroup_spec (the one input carrying the indication-vs-subtype distinction). These tests pin the
derivation from BOTH sides so it cannot silently regress to a constant.

Hermetic: uses a single excluded-by-applies_when card so no card spec / measurement-type loader is
touched; only the context block is under test.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.envelope import assemble_evidence_package  # noqa: E402

_VS = {
    "n_cards_attempted": 1,
    "n_cards_passed": 0,
    "n_cards_passed_with_warnings": 0,
    "n_cards_failed": 0,
    "n_cards_excluded_by_applies_when": 1,
}
_SYN = {"headline": "test headline"}


def _excluded_card():
    return [
        {
            "card_id": "tumor-vs-normal-selectivity",
            "card_version": "1.0.0",
            "excluded_by_applies_when": True,
            "exclusion_reason": "hermetic scope test — no card evidence needed",
        }
    ]


def _emit(subgroup_spec):
    ctx = {"target_symbol": "KRAS", "indication": "COADREAD", "data_mode": "exploratory"}
    if subgroup_spec is not None:
        ctx["subgroup_spec"] = subgroup_spec
    return assemble_evidence_package(
        input_context=ctx,
        card_outputs=_excluded_card(),
        validation_summary=_VS,
        synthesis_block=_SYN,
        deterministic_timestamps=True,
        framework_version="2.0.0",
        generated_by="skills/test@abc123",
        dashboard_spec_ref="skill:test",
    )


def test_indication_level_run_is_cancer_type():
    """No subgroup_spec (or null) => indication-level => cancer_type (the byte-stable default)."""
    assert _emit(None)["context"]["scope"] == "cancer_type"
    assert _emit(None)["context"]["subgroup_spec"] is None


def test_empty_strata_list_is_cancer_type():
    """An empty list is not a subtype scope — falsy, so it stays cancer_type."""
    assert _emit([])["context"]["scope"] == "cancer_type"


def test_subtype_scoped_run_is_cancer_subtype():
    """A strata list => subtype-scoped => cancer_subtype (previously mislabeled cancer_type)."""
    ep = _emit(["MSI_H", "MSS"])
    assert ep["context"]["scope"] == "cancer_subtype"
    assert ep["context"]["subgroup_spec"] == ["MSI_H", "MSS"]


def test_all_subgroups_is_cancer_subtype():
    """The 'all' sentinel is also a subtype scope (all subgroups), not indication-level."""
    assert _emit("all")["context"]["scope"] == "cancer_subtype"
