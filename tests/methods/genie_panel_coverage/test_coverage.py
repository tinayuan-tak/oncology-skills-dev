"""genie_panel_coverage — the panel-coverage-denominator primitive.

GENIE is panel-sequenced, so "no mutation row for gene G" is ambiguous: G-wild-type vs
G-not-on-the-sample's-panel. These tests pin the honest denominator — a sample counts
toward gene G's denominator ONLY if its panel covers G — using injected sample→panel +
panel→gene maps (no S3).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.genie_panel_coverage import read as cov  # noqa: E402


# Two panels: BIG covers KRAS+TP53+EGFR; SMALL covers only TP53.
_PANEL_GENES = {
    "BIG": frozenset({"KRAS", "TP53", "EGFR"}),
    "SMALL": frozenset({"TP53"}),
}
# s1,s2 on BIG; s3,s4 on SMALL; s5 has no mutation panel (not SNV-profiled).
_SAMPLE_PANEL = {"s1": "BIG", "s2": "BIG", "s3": "SMALL", "s4": "SMALL"}


def test_covered_respects_panel_membership():
    assert cov.covered("s1", "KRAS", _SAMPLE_PANEL, _PANEL_GENES) is True
    assert cov.covered("s3", "KRAS", _SAMPLE_PANEL, _PANEL_GENES) is False  # SMALL lacks KRAS
    assert cov.covered("s3", "TP53", _SAMPLE_PANEL, _PANEL_GENES) is True
    assert cov.covered("s5", "TP53", _SAMPLE_PANEL, _PANEL_GENES) is False  # not in map → no coverage


def test_denominator_excludes_uncovered_samples():
    """KRAS is on BIG only → denominator over all 4 samples is 2 (s1,s2), NOT 4.
    This is the whole point: the 2 SMALL samples are not-sequenced-for-KRAS, not KRAS-WT."""
    n = cov.n_covered_samples("KRAS", ["s1", "s2", "s3", "s4"], _SAMPLE_PANEL, _PANEL_GENES)
    assert n == 2


def test_denominator_full_for_universally_covered_gene():
    # TP53 is on BOTH panels → all 4 covered (this is why KRAS-like universal drivers
    # happen to be safe even with a naive denominator, but rarer genes are not).
    assert cov.n_covered_samples("TP53", ["s1", "s2", "s3", "s4"], _SAMPLE_PANEL, _PANEL_GENES) == 4


def test_coverage_denominator_breakdown():
    d = cov.panel_coverage_denominator("KRAS", ["s1", "s2", "s3", "s4"], _SAMPLE_PANEL, _PANEL_GENES)
    assert d == {"n_total": 4, "n_covered": 2, "n_uncovered": 2, "coverage_fraction": 0.5}


def test_gene_on_no_panel_is_coverage_gap_not_zero():
    """A gene on NONE of the cohort's panels → n_covered==0 → caller must emit
    data_unavailable/coverage-gap, NOT frequency 0%."""
    d = cov.panel_coverage_denominator("MYC", ["s1", "s2", "s3", "s4"], _SAMPLE_PANEL, _PANEL_GENES)
    assert d["n_covered"] == 0 and d["coverage_fraction"] == 0.0


def test_empty_sample_set():
    d = cov.panel_coverage_denominator("KRAS", [], _SAMPLE_PANEL, _PANEL_GENES)
    assert d["n_total"] == 0 and d["coverage_fraction"] is None
