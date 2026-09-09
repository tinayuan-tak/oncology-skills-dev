"""Dashboard consolidation Ph3b-causal + Ph3c — the composed convergence layer, rendered from the
now-carried nomination fields (verdict-inert), extending EXISTING blocks (no new block kind):
  - lit×omics coherence table (LITERATURE_RISK): deep-research literature risk beside the deterministic
    omics 6-dim, per dimension, with an agreement read.
  - cross-evidence causal chain + independent-read trust strip (SYNTHESIS): from nomination['hypothesis'].
"""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render import render_report
from _skills_common.report_render._fixtures import make_nomination


def test_lit_omics_coherence_table():
    nom = make_nomination()  # target_report.risk_6dim provides the omics bins
    nom["risk_assessment"] = {
        "dimensions": {
            "biological": {
                "risk_level": "LOW",
                "interpretation": "oncodriver consensus",
                "cited_pmids": ["12345678", "23456789"],
                "contradicts_deterministic": False,
            },
            "safety": {
                "risk_level": "MEDIUM",
                "interpretation": "allele-specific spares WT",
                "cited_pmids": ["34567890"],
                "contradicts_deterministic": False,
            },
        }
    }
    h = render_report(nom, preset="full", backend="html")
    assert "Literature × omics coherence" in h
    assert "Omics — deterministic (risk_6dim)" in h and "Coherence" in h
    assert "cohtab" in h  # the v6 lit×omics coherence table
    assert "PMIDs" in h
    # a coherence verdict per row (omics bin vs literature grade)
    assert any(w in h for w in ("agree", "grade-divergence", "literature-only", "omics-only", "contradicts"))


def test_cross_evidence_causal_chain_in_synthesis():
    nom = make_nomination()
    nom["hypothesis"] = {
        "edges": [
            {"type": "conditions", "from_dimension": "genomic_alteration", "to_dimension": "dependency"},
            {"type": "confirmed_by", "from_dimension": "dependency", "to_dimension": "tractability_sm"},
        ],
        "verdict": {"computed": "advanceable_flagged"},
        "uncertainty": {"overall_certainty": "low", "limiting_dimension": "expression"},
        "defensibility": {"n_clauses": 27, "n_fully_traceable": 27, "n_coherence_violations": 0},
    }
    h = render_report(nom, preset="full", backend="html")
    assert "Cross-evidence integrator" in h
    assert "advanceable_flagged" in h and "certainty" in h
    assert "clauses traceable" in h
    assert "dependency" in h  # a causal-chain node
    assert "class='causal'" in h  # the v6 cross-evidence causal chain renders


def test_cross_evidence_absent_when_hypothesis_missing():
    """Fail-soft: no nomination['hypothesis'] → no cross-evidence strip (the composed report without
    the cross-evidence-hypothesis leg stays clean; the rest of synthesis is unaffected)."""
    nom = make_nomination()
    nom.pop("hypothesis", None)
    h = render_report(nom, preset="full", backend="html")
    assert "Cross-evidence integrator" not in h
