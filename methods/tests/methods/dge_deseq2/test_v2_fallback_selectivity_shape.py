"""Regression: the v2 two-product fallback must populate the per-cell LFC keys the selectivity
classifier reads.

Bug: `_read_tvn_selectivity_v2_fallback` built its internal `row` WITHOUT log2fc_cell_a/c, then
called `_classify_selectivity_from_sensitivity(row)`. The classifier computes raw_max_lfc from
row["log2fc_cell_a"]/["log2fc_cell_c"] → always None → raw_max_lfc=0.0 → the >=1.5 / >=0.5 magnitude
gates never fired, and the discordant branch's c_lfc was None → EVERY fallback call collapsed to
not_informative / discordant_across_comparators. This drives verdicts for any indication still on the
v2 fallback (only the four-cell sensitivity product bypasses it).

S3-free: read_dge_gene_row (cell A) + read_tumor_vs_gtex_gene_row (cell C) are monkeypatched."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.dge_deseq2 import read as _r  # noqa: E402


def _patch(monkeypatch, cell_a: dict, cell_c: dict):
    # COADREAD has an adjacent manifest in _INDICATION_TO_ADJ_MANIFEST, so cell A is exercised.
    monkeypatch.setattr(_r, "read_dge_gene_row", lambda target, manifest: cell_a)
    monkeypatch.setattr(_r, "read_tumor_vs_gtex_gene_row", lambda target, indication: cell_c)


def test_fallback_strong_tumor_up_is_strong_selective(monkeypatch):
    # Both comparators strongly UP and significant → raw_max_lfc >= 1.5, supporting_frac == 1.0.
    _patch(monkeypatch, {"log2_fc": 2.0, "q_value": 0.001}, {"log2_fc": 2.2, "q_value": 0.001})
    out = _r._read_tvn_selectivity_v2_fallback("EPCAM", "COADREAD")
    assert out["_schema"] == "v2_two_product_fallback"
    # per-cell keys are now forwarded to the classifier
    assert out["log2fc_cell_a"] == 2.0 and out["log2fc_cell_c"] == 2.2
    assert out["selectivity_class"] == "strong_tumor_selective"


def test_fallback_field_effect_is_field_effect_selective(monkeypatch):
    # Adjacent SIG-DOWN but GTEx SIG strongly-UP → the field-cancerization signature.
    _patch(
        monkeypatch,
        {"log2_fc": -0.6, "q_value": 0.01},  # cell A (TCGA-adjacent) down
        {"log2_fc": 2.0, "q_value": 0.001},
    )  # cell C (GTEx population) strongly up
    out = _r._read_tvn_selectivity_v2_fallback("KRT20", "COADREAD")
    assert out["discordant"] is True
    assert out["log2fc_cell_c"] == 2.0  # the key the field-effect branch needs
    assert out["selectivity_class"] == "field_effect_tumor_selective"


def test_fallback_below_magnitude_gate_not_strong(monkeypatch):
    # Both up + significant but weak magnitude (< 1.5) → modest, NOT strong (guards the gate wiring).
    _patch(monkeypatch, {"log2_fc": 0.6, "q_value": 0.001}, {"log2_fc": 0.7, "q_value": 0.001})
    out = _r._read_tvn_selectivity_v2_fallback("MUC1", "COADREAD")
    assert out["selectivity_class"] == "modest_tumor_selective"
