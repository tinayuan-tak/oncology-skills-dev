"""Test the RNA->protein proxy QUALIFIER on the tumor-presence RNA verdict (review Fix-1).

_bulk_rna_proxy_quality is a derived, VERDICT-INERT qualifier: when the bulk-RNA presence call is a
measured-positive, it reports whether RNA is a trustworthy protein proxy (spec D5). It must NEVER
change presence_verdict — these tests pin the mapping + the not_applicable guard (a non-positive RNA
verdict is never qualified) + that it reads the bucket dict shape _per_modality_verdicts emits.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run_proxy")


def _pm(rna_verdict, bucket="bulk_rna/tumor"):
    """A per_modality dict with one RNA bucket carrying a verdict (the shape _per_modality_verdicts emits)."""
    return {
        bucket: {
            "measurement": "bulk_rna",
            "sample_context": bucket.split("/")[1],
            "verdict": rna_verdict,
            "evidence_state": "measured",
        }
    }


def test_rna_positive_poor_proxy_flagged():
    # the case the fix exists for: RNA says present, but RNA is a POOR protein proxy → flag it
    assert tp._bulk_rna_proxy_quality(_pm("strongly_upregulated_in_tumor"), "poor_proxy") == "rna_positive_proxy_poor"
    assert tp._bulk_rna_proxy_quality(_pm("broadly_high_expression"), "poor_proxy") == "rna_positive_proxy_poor"


def test_rna_positive_adequate_proxy_confirmed():
    assert tp._bulk_rna_proxy_quality(_pm("broadly_high_expression"), "adequate_proxy") == "rna_confirmed_by_protein"


def test_rna_positive_partial_proxy():
    assert tp._bulk_rna_proxy_quality(_pm("lineage_restricted"), "partial_proxy") == "rna_positive_proxy_partial"


def test_proxy_untested_when_insufficient_or_missing():
    assert tp._bulk_rna_proxy_quality(_pm("broadly_high_expression"), "insufficient_paired_models") == "proxy_untested"
    assert tp._bulk_rna_proxy_quality(_pm("broadly_high_expression"), None) == "proxy_untested"
    assert tp._bulk_rna_proxy_quality(_pm("broadly_high_expression"), "data_unavailable") == "proxy_untested"


def test_not_applicable_when_rna_not_a_positive_presence_call():
    # a non-positive / absent / downregulated RNA verdict is NEVER qualified (guard)
    assert tp._bulk_rna_proxy_quality(_pm("broadly_low_expression"), "poor_proxy") == "not_applicable"
    assert tp._bulk_rna_proxy_quality(_pm("strongly_downregulated_in_tumor"), "adequate_proxy") == "not_applicable"
    assert tp._bulk_rna_proxy_quality(_pm("data_unavailable"), "poor_proxy") == "not_applicable"
    assert tp._bulk_rna_proxy_quality({}, "poor_proxy") == "not_applicable"


def test_falls_back_to_cell_line_bucket_when_no_tumor_bucket():
    # a target-only query has bulk_rna/cell_line but no bulk_rna/tumor — still qualifiable
    pm = _pm("broadly_high_expression", bucket="bulk_rna/cell_line")
    assert tp._bulk_rna_proxy_quality(pm, "poor_proxy") == "rna_positive_proxy_poor"


def test_verdict_inert_qualifier_is_pure():
    # the qualifier takes only (per_modality, rna_as_biomarker) — it cannot touch presence_verdict
    import inspect

    sig = inspect.signature(tp._bulk_rna_proxy_quality)
    assert list(sig.parameters) == ["per_modality", "rna_as_biomarker"]


def test_prefers_cell_line_when_tumor_bucket_data_unavailable_both_present():
    # The dead-fallback bug: BOTH buckets present — tumor bucket data_unavailable, cell-line bucket
    # positive. Must fall back to the cell-line arm (was wrongly "not_applicable" while the headline
    # reported bulk_rna_proxy_quality_source == "cell_line" — a self-contradiction).
    pm = {
        "bulk_rna/tumor": {
            "measurement": "bulk_rna",
            "sample_context": "tumor",
            "verdict": "data_unavailable",
            "evidence_state": "data_unavailable",
        },
        "bulk_rna/cell_line": {
            "measurement": "bulk_rna",
            "sample_context": "cell_line",
            "verdict": "broadly_high_expression",
            "evidence_state": "measured",
        },
    }
    assert tp._bulk_rna_proxy_quality(pm, "adequate_proxy") == "rna_confirmed_by_protein"


def test_prefers_tumor_arm_when_tumor_positive_even_if_cell_line_present():
    # Tumor arm positive wins over the cell-line arm (tumor-preferred).
    pm = {
        "bulk_rna/tumor": {"verdict": "strongly_upregulated_in_tumor", "evidence_state": "measured"},
        "bulk_rna/cell_line": {"verdict": "broadly_low_expression", "evidence_state": "measured"},
    }
    assert tp._bulk_rna_proxy_quality(pm, "poor_proxy") == "rna_positive_proxy_poor"
