"""Gap-A finish — the last two rule-read fields with no descriptor.

Gap A was the set of fields a rule READS but the framework cannot describe. PR 1 (sc_normal) + PR 5
(per_subgroup_metrics, via the shared vocab) closed four; these two are the remainder:
  - essential_tissue_flag  (normal_tissue_protein_breadth) — rule-read by the normal-tissue-essential killers
  - rna_as_biomarker       (rna_protein_concordance) — rule-read by the rna-*-proxy rules, on BOTH concordance cards
Both are categorical class tokens; adding them to their specs' `categorical` describes them. Verdict-inert.
"""

from __future__ import annotations

from _skills_common import field_descriptor as fd


def test_essential_tissue_flag_is_categorical():
    d = fd.descriptors_for("normal_tissue_protein_breadth")
    assert "essential_tissue_flag" in d
    assert d["essential_tissue_flag"]["role"] == "categorical"
    assert fd.classify_field("essential_tissue_flag", "normal_tissue_protein_breadth") == "categorical"


def test_rna_as_biomarker_is_categorical_on_the_shared_mt():
    # one spec entry (rna_protein_concordance) describes it for BOTH concordance cards (they share the mt).
    d = fd.descriptors_for("rna_protein_concordance")
    assert "rna_as_biomarker" in d
    assert d["rna_as_biomarker"]["role"] == "categorical"
    assert fd.classify_field("rna_as_biomarker", "rna_protein_concordance") == "categorical"


def test_neither_field_is_unclassified_anymore():
    assert fd.classify_field("essential_tissue_flag") != "unclassified"
    assert fd.classify_field("rna_as_biomarker") != "unclassified"


def test_the_original_gap_a_six_are_all_described_now():
    # the full Gap-A roster (rule-read, formerly undescribed) is closed across PR1 + PR5 + this PR.
    gap_a = [
        "sc_normal_safety_essential_class",  # PR 1
        "sc_normal_expression_class",  # PR 1
        "per_subgroup_metrics",  # PR 5 (shared vocab -> strata)
        "essential_tissue_flag",  # this PR
        "rna_as_biomarker",  # this PR
    ]
    for f in gap_a:
        assert fd.classify_field(f) != "unclassified", f
