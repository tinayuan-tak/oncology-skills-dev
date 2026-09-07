"""H3 regression: broadly_high must be REACHABLE and panel-relative (no S3).

The prior high_cutoff was the HIGH_ABUNDANCE_PERCENTILE quantile of the target's OWN abundance vector,
so broadly_high required median (p50) >= p70 of the same vector — impossible. broadly_high was dead.
The fix keys it on the PANEL-WIDE all-protein median null (passed in as all_protein_medians)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

cli = importlib.import_module("methods.depmap_protein_abundance.cli")


def test_classify_broadly_high_fires_with_panel_cutoff():
    # median (5.0) above the panel high cutoff → broadly_high is reachable.
    assert (
        cli.classify_protein_abundance(fraction_detected=1.0, median_abundance=5.0, per_lineage=[], high_cutoff=3.8)
        == "broadly_high"
    )
    # same detection, median below cutoff → broadly_moderate.
    assert (
        cli.classify_protein_abundance(fraction_detected=1.0, median_abundance=2.0, per_lineage=[], high_cutoff=3.8)
        == "broadly_moderate"
    )
    # no panel null (high_cutoff None) → cannot assess panel-relative high → broadly_moderate, never crash.
    assert (
        cli.classify_protein_abundance(fraction_detected=1.0, median_abundance=5.0, per_lineage=[], high_cutoff=None)
        == "broadly_moderate"
    )


def test_compute_summary_broadly_high_uses_panel_null():
    # 10/10 detected (fraction 1.0 > BROADLY_DETECTED_FRACTION), target median = 5.0.
    abund = {f"ACH-{i:04d}": 5.0 for i in range(10)}
    # panel null where 5.0 sits well above the 70th percentile of all-protein medians.
    panel = tuple(float(x) for x in range(0, 5))  # p70 ~= 3.8
    out = cli.compute_summary("EGFR", abund, {}, n_panel=10, all_protein_medians=panel)
    assert out["protein_expression_class"] == "broadly_high", (
        f"panel-relative high not reached; got {out['protein_expression_class']!r} — H3 regression"
    )
    # WITHOUT the panel null, broadly_high cannot fire (honest — no panel to be 'high' relative to).
    out_no_null = cli.compute_summary("EGFR", abund, {}, n_panel=10)
    assert out_no_null["protein_expression_class"] == "broadly_moderate"
