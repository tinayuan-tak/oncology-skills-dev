"""sanger_drug_synergy — classification + ranking + coverage-gap discipline (hermetic, rows injected)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.sanger_drug_synergy.read import synergy_partners_for_gene, _classify  # noqa: E402


def _row(cls, drug, delta, n_syn=5, n=10, role="anchor", pt="AKT1"):
    return {"synergy_class": cls, "partner_drug": drug, "partner_target": pt, "partner_pathway": "PI3K",
            "target_role": role, "n_lines_tested": n, "n_lines_synergistic": n_syn,
            "frac_lines_synergistic": n_syn / n, "mean_delta_emax": delta, "tissues": "Breast"}


def test_classify_strongest_wins():
    assert _classify([_row("context_synergy", "d1", 0.02), _row("robust_synergy", "d2", 0.2)]) == "strong_synergy_opportunity"
    assert _classify([_row("context_synergy", "d1", 0.02), _row("supported_synergy", "d2", 0.07)]) == "synergy_opportunity"
    assert _classify([_row("context_synergy", "d1", 0.02)]) == "context_synergy_opportunity"


def test_coverage_gap_is_not_evidence_against():
    """A target absent from the 86-gene screen → no_synergy_screen (coverage gap), NOT a negative."""
    assert _classify(None) == "no_synergy_screen"
    assert _classify([]) == "no_synergy_screen"
    s = synergy_partners_for_gene("NOTSCREENED", rows=[])
    assert s["synergy_opportunity_class"] == "no_synergy_screen"
    assert s["n_synergy_partners"] == 0


def test_summary_ranks_and_surfaces_strongest():
    rows = [_row("supported_synergy", "Navitoclax", 0.075, pt="BCL2"),
            _row("robust_synergy", "MK-2206", 0.2, pt="AKT1")]
    s = synergy_partners_for_gene("EGFR", rows=rows)
    assert s["synergy_opportunity_class"] == "strong_synergy_opportunity"
    assert s["strongest_synergy_partner_drug"] == "MK-2206"       # robust ranks first
    assert s["strongest_synergy_delta_emax"] == 0.2
    assert s["n_synergy_partners"] == 2
    assert "chemical synergy" in s["synergy_context"]
    assert s["top_synergy_partners"][0]["partner_drug"] == "MK-2206"
