"""Smoke test: read_per_sample_expression_all_three_groups reads GTEx from the
long derived product (gtex-tpm-recount3-long-v1) and returns the same values
the wide product's emit-time correctness check produced.

Marked slow because it hits S3. Skipped unless RUN_S3_SMOKE=1 is set — CI's
default job should skip; run locally when validating the refactor:

    RUN_S3_SMOKE=1 AWS_PROFILE=cbg pytest tests/methods/dge_deseq2/test_gtex_long_consumer.py -v
"""

from __future__ import annotations

import os

import numpy as np
import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_S3_SMOKE") != "1",
    reason="requires S3 access; set RUN_S3_SMOKE=1 to enable",
)


def _median_log2tpm(records):
    vals = [r["log2_tpm"] for r in records if r["log2_tpm"] is not None]
    return float(np.median(vals)) if vals else float("nan")


# (target, indication, expected_gtex_tissue, expected_median_log2tpm,
#  expected_n_samples). Values come from the gtex-tpm-recount3-long-v1
# manifest's emit-time correctness check + the wide product's sample-count
# sidecar (COLON=822, LUNG=655, BRAIN=2931 per the manifest cohort block).
CASES = [
    # (target, indication, gtex_tissue, expected_median, expected_n)
    ("EPCAM", "COADREAD", "COLON",  3.1817,  822),
    ("ACTB",  "COADREAD", "COLON", 12.3797,  822),
    ("GFAP",  "GBM",      "BRAIN",  8.9259, 2931),
]


@pytest.mark.parametrize("target,indication,expected_tissue,expected_median,expected_n",
                         CASES)
def test_gtex_branch_reads_from_long_product(
    target, indication, expected_tissue, expected_median, expected_n,
):
    from methods.dge_deseq2.read import read_per_sample_expression_all_three_groups

    res = read_per_sample_expression_all_three_groups(target, indication)
    assert res is not None, f"reader returned None for {target}/{indication}"
    assert res["gtex_tissue"] == expected_tissue

    gtex = res["gtex_samples"]
    assert len(gtex) == expected_n, (
        f"n_gtex mismatch for {target}/{expected_tissue}: "
        f"got {len(gtex)}, expected {expected_n}"
    )

    # Record shape: preserve the fields the caller (emit_pan_tissue) expects.
    for k in ("sample_id", "tissue_subregion", "log2_cpm", "log2_tpm", "tpm"):
        assert k in gtex[0], f"missing key {k!r} in GTEx record"

    # Bit-identical to the long-product's emit-time correctness check.
    observed_median = _median_log2tpm(gtex)
    assert abs(observed_median - expected_median) < 1e-3, (
        f"median mismatch for {target}/{expected_tissue}: "
        f"expected {expected_median}, got {observed_median}"
    )


def test_gtex_branch_returns_empty_for_indication_without_gtex_mapping():
    """HNSC has no canonical GTEx tissue (INDICATION_TO_GTEX_TISSUE[HNSC] is None
    per the mapping in dge_tcga_gtex_precompute). The reader must return
    gtex_samples=[] + gtex_tissue=None, NOT raise."""
    from methods.dge_deseq2.read import (
        INDICATION_TO_GTEX_TISSUE,
        read_per_sample_expression_all_three_groups,
    )

    # Only run this branch if the mapping actually returns None here — otherwise
    # the assertion is moot on this checkout.
    if INDICATION_TO_GTEX_TISSUE.get("HNSC") is not None:
        pytest.skip("INDICATION_TO_GTEX_TISSUE[HNSC] has been wired; test needs "
                    "a different unmapped indication")

    res = read_per_sample_expression_all_three_groups("EPCAM", "HNSC")
    assert res is not None
    assert res["gtex_tissue"] is None
    assert res["gtex_samples"] == []
    assert res["n_gtex"] == 0
