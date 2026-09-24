"""Guard: `data_unavailable` availability detection must key on the card's PRIMARY class only.

Sweep-2 S1 regression. The M2 review-fix broadened `_data_unavailable_field` to scan EVERY
`*_class` field, so a card with a real PRIMARY verdict but a `data_unavailable` SECONDARY facet
(a normal partial-data state) was falsely marked `_missing`/`data_unavailable` — corrupting
`cards_available`, flipping `run_health` to degraded, and making the narrator report a live card
as DATA_UNAVAILABLE. This pins BOTH directions:
  - a real primary + data-less secondary stays AVAILABLE (the bug), and
  - a genuinely no-data PRIMARY is still DETECTED (the M2 case this must not re-open).
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import _data_unavailable_field, _primary_class_value  # noqa: E402

# --- real primary + data_unavailable SECONDARY facet must stay AVAILABLE (the bug) -----------


def test_immune_context_real_primary_data_unavailable_facet_is_available():
    s = {"immune_context_class": "immune_intermediate", "antigen_high_immune_context_class": "data_unavailable"}
    assert _data_unavailable_field(s) is None
    assert _primary_class_value(s) == "immune_intermediate"


def test_copy_number_real_primary_data_unavailable_patient_crosscheck_is_available():
    s = {
        "copy_number_class": "recurrently_amplified",
        "patient_copy_number_class": "data_unavailable",
        "patient_focal_cn_class": "data_unavailable",
    }
    assert _data_unavailable_field(s) is None
    assert _primary_class_value(s) == "recurrently_amplified"


def test_gnomad_real_constraint_data_unavailable_human_ko_facet_is_available():
    s = {"constraint_class": "highly_constrained", "human_ko_observed_class": "data_unavailable"}
    assert _data_unavailable_field(s) is None
    assert _primary_class_value(s) == "highly_constrained"


def test_dependency_real_primary_data_unavailable_control_facet_is_available():
    s = {"dependency_class": "broadly_dependent", "dep_control_position_class": "data_unavailable"}
    assert _data_unavailable_field(s) is None
    assert _primary_class_value(s) == "broadly_dependent"


# --- a genuinely no-data PRIMARY must still be DETECTED (do not re-open the M2 bug) ----------


def test_topic_specific_all_classes_data_unavailable_is_detected():
    s = {"copy_number_class": "data_unavailable", "patient_copy_number_class": "data_unavailable"}
    assert _data_unavailable_field(s) == "copy_number_class"


def test_legacy_primary_data_unavailable_is_detected():
    # A legacy primary present + data_unavailable decides on its own, even with a real secondary.
    s = {"selectivity_class": "data_unavailable", "some_secondary_class": "tumor_selective"}
    assert _data_unavailable_field(s) == "selectivity_class"


def test_legacy_primary_real_is_available_despite_data_unavailable_secondary():
    s = {"class": "strong_dependency", "other_class": "data_unavailable"}
    assert _data_unavailable_field(s) is None
    assert _primary_class_value(s) == "strong_dependency"


def test_no_class_fields_is_not_flagged():
    assert _data_unavailable_field({"cn_median_panel": 1.2, "n_samples": 40}) is None
    assert _data_unavailable_field({}) is None


# --- contracts-first: a declared non-`*_class` primary wins over the `*_class` heuristic --------


def test_declared_non_class_primary_wins_over_first_class_field():
    """`sc-normal-celltype-expression` declares `capsule.primary_class:
    sc_normal_essential_veto_grade` — a field that does NOT end in `_class`. Without the card_id
    the helper falls back to the blunt first-`*_class` heuristic; WITH the card_id it must return
    the declared graded veto, not `sc_normal_expression_class` (canon-17 F5 root cause, #1539)."""
    s = {
        "sc_normal_expression_class": "broadly_high",
        "sc_normal_essential_veto_grade": "epithelial_severe_veto",
    }
    # Heuristic (no card_id) mis-picks the first `*_class` field — the bug this fix leaves intact
    # only for un-declared cards.
    assert _primary_class_value(s) == "broadly_high"
    # Contracts-first (card_id given) honors the declared primary.
    assert _primary_class_value(s, "sc-normal-celltype-expression") == "epithelial_severe_veto"


def test_declared_primary_absent_falls_back_to_heuristic():
    """When the declared primary field is not present in the summary, the helper falls back to the
    legacy/`*_class` heuristic rather than returning None."""
    s = {"sc_normal_expression_class": "broadly_high"}
    assert _primary_class_value(s, "sc-normal-celltype-expression") == "broadly_high"
