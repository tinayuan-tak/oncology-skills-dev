"""COAD/READ/COADREAD breadth double-count guard (audit 2026-08-08 / T10).

The pan-cancer stacked DGE product keeps COAD, READ, AND their merged OncoTree parent
COADREAD as three separate per-indication slices (a per-indication LOOKUP legitimately wants
any one). But the tumor_elevation_breadth roll-up counts K-of-N indications, and COADREAD =
COAD ∪ READ over the SAME tumor samples — so counting all three double-counts colorectal.
`_dedupe_overlapping_indications` drops the composite parent whenever a child is present.

These are pure-function tests on the row list (no S3), mirroring the module's unit-test style.
"""

from onc_methods.dge_deseq2.derive_pancan_stack import (
    _COMPOSITE_INDICATIONS,
    _dedupe_overlapping_indications,
)


def _row(ind):
    return {"indication": ind, "gene_symbol": "KRAS", "max_abs_log2fc": 1.0}


def test_coadread_dropped_when_both_children_present():
    rows = [_row("COAD"), _row("READ"), _row("COADREAD"), _row("LUAD")]
    kept = {r["indication"] for r in _dedupe_overlapping_indications(rows)}
    assert kept == {"COAD", "READ", "LUAD"}  # composite parent removed
    assert "COADREAD" not in kept


def test_coadread_dropped_when_only_one_child_present():
    # A single child is enough to prefer the finer granularity over the merged parent.
    rows = [_row("COAD"), _row("COADREAD"), _row("BRCA")]
    kept = {r["indication"] for r in _dedupe_overlapping_indications(rows)}
    assert kept == {"COAD", "BRCA"}


def test_coadread_kept_when_no_child_present():
    # No COAD/READ slice → COADREAD is the ONLY colorectal signal, so it must be kept.
    rows = [_row("COADREAD"), _row("LUAD")]
    kept = {r["indication"] for r in _dedupe_overlapping_indications(rows)}
    assert kept == {"COADREAD", "LUAD"}


def test_non_composite_rows_pass_through_untouched():
    rows = [_row("COAD"), _row("READ"), _row("LUAD"), _row("STAD")]
    assert len(_dedupe_overlapping_indications(rows)) == 4


def test_idempotent():
    rows = [_row("COAD"), _row("READ"), _row("COADREAD")]
    once = _dedupe_overlapping_indications(rows)
    twice = _dedupe_overlapping_indications(once)
    assert [r["indication"] for r in once] == [r["indication"] for r in twice]


def test_case_insensitive_indication_labels():
    rows = [_row("coad"), _row("read"), _row("coadread")]
    kept = {r["indication"] for r in _dedupe_overlapping_indications(rows)}
    assert kept == {"coad", "read"}  # lowercase composite still dropped


def test_composite_map_documents_coadread():
    # Guard: if the map is edited, COADREAD -> {COAD, READ} must remain the documented union.
    assert _COMPOSITE_INDICATIONS["COADREAD"] == {"COAD", "READ"}
