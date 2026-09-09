"""literature-risk-assessment self-consistency (PR-4): N-sample majority vote on the per-dimension grade.

The framework model's temperature is unpinnable, so a single grade carries sampling noise; voting over N
grades of the SAME grounded corpus stabilizes the reported risk_level and records the vote dispersion.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

rc = load_run_py(Path(__file__).resolve().parent.parent, "lra_run_sc")


def _entry(level, **extra):
    return {"pillar": "P", "risk_level": level, "cited_pmids": ["111"], **extra}


def test_vote_dimension_majority_winner():
    samples = [_entry("LOW"), _entry("HIGH"), _entry("LOW")]
    out = rc._vote_dimension(samples)
    assert out["risk_level"] == "LOW"  # 2/3
    assert out["vote_distribution"] == {"LOW": 2, "HIGH": 1}
    assert out["n_samples"] == 3


def test_vote_dimension_tie_breaks_to_higher_risk():
    # 1 HIGH vs 1 LOW → tie resolves to the MORE CONSERVATIVE (higher-risk) level, never averaged down
    out = rc._vote_dimension([_entry("LOW"), _entry("HIGH")])
    assert out["risk_level"] == "HIGH"
    assert out["vote_distribution"] == {"LOW": 1, "HIGH": 1}


def test_vote_dimension_representative_is_first_at_winning_level():
    # representative entry carries the winner's own justification/citations (internally consistent)
    samples = [
        _entry("MEDIUM", justification="m1"),
        _entry("HIGH", justification="h"),
        _entry("MEDIUM", justification="m2"),
    ]
    out = rc._vote_dimension(samples)
    assert out["risk_level"] == "MEDIUM" and out["justification"] == "m1"


def test_run_with_samples_records_vote_distribution(monkeypatch):
    # only safety retrieves an abstract → only it is graded (others: not_assessed, no synth call)
    monkeypatch.setattr(
        rc.rl,
        "retrieve_axis",
        lambda target, indication, axis, **k: {"kept": ([_Ab("111")] if axis == "safety" else []), "dropped": []},
    )
    # cycle the grade across the 3 samples: HIGH, HIGH, LOW → majority HIGH (2/3)
    seq = iter(["HIGH", "HIGH", "LOW"])

    def fake_synth(system, prompt, name, schema):
        return {
            "risk_level": next(seq),
            "justification": "j",
            "interpretation": "i",
            "cited_pmids": ["111"],  # retrieved → survives containment (no downgrade)
            "contradicts_deterministic": False,
        }

    monkeypatch.setattr(rc, "synthesize_structured", fake_synth)
    res = rc.run("GENE", "safety-indication", None, "2015", "2026", per_cat=1, n_samples=3)
    safety = res["dimensions"]["safety"]
    assert safety["risk_level"] == "HIGH"
    assert safety["vote_distribution"] == {"HIGH": 2, "LOW": 1}
    assert safety["n_samples"] == 3
    assert res["provenance"]["n_samples"] == 3


def test_run_default_single_sample_has_no_vote_fields(monkeypatch):
    # n_samples=1 (default) is byte-identical to the prior single-call path — no vote_distribution key
    monkeypatch.setattr(
        rc.rl,
        "retrieve_axis",
        lambda target, indication, axis, **k: {"kept": ([_Ab("111")] if axis == "safety" else []), "dropped": []},
    )
    monkeypatch.setattr(
        rc,
        "synthesize_structured",
        lambda *a, **k: {
            "risk_level": "MEDIUM",
            "justification": "j",
            "interpretation": "i",
            "cited_pmids": ["111"],
            "contradicts_deterministic": False,
        },
    )
    res = rc.run("GENE", "safety-indication", None, "2015", "2026", per_cat=1)
    safety = res["dimensions"]["safety"]
    assert safety["risk_level"] == "MEDIUM"
    assert "vote_distribution" not in safety and "n_samples" not in safety
    assert res["provenance"]["n_samples"] == 1


class _Ab:
    def __init__(self, pmid):
        self.pmid, self.year, self.title, self.abstract = pmid, 2020, "t", "body"
