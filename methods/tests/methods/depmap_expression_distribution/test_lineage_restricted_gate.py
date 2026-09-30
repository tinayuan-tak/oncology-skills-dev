"""M1 regression: lineage_restricted must require ACTUAL lineage enrichment (no S3).

The classifier took n_lineage_restricted but never used it — ANY 10-70% pan-cancer detection was
labeled lineage_restricted, implying patient-selection specificity that was never tested. The fix
gates the class on n_lineage_restricted >= 1 (>=1 lineage expressed-fraction >=0.40 above the panel);
mid-band detection with no enriched lineage is broadly_moderate (diffuse presence, not specificity)."""

from __future__ import annotations

import importlib

cli = importlib.import_module("onc_methods.depmap_expression_distribution.cli")


def test_mid_band_with_enriched_lineage_is_lineage_restricted():
    assert (
        cli._classify_expression(frac_expressed=0.50, frac_highly=0.10, n_lineage_restricted=1) == "lineage_restricted"
    )


def test_mid_band_without_enriched_lineage_is_broadly_moderate():
    # SAME detection fraction, but no lineage is enriched → NOT lineage-restricted (the M1 bug).
    assert cli._classify_expression(frac_expressed=0.50, frac_highly=0.10, n_lineage_restricted=0) == "broadly_moderate"


def test_unaffected_classes_hold():
    assert cli._classify_expression(0.85, 0.40, 0) == "broadly_high"  # broad + high-fraction
    assert cli._classify_expression(0.85, 0.10, 0) == "broadly_moderate"  # broad, not high
    assert cli._classify_expression(0.05, 0.00, 3) == "broadly_low"  # below detection floor
