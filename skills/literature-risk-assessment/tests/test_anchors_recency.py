"""literature-risk-assessment PR-5: clinical/commercial card anchors (A5) + recency annotation.

Both are additive, verdict-inert context: the engine-blind clinical/commercial dims now reconcile against
the deterministic clinical-precedent / competitor-landscape cards, and every graded dim carries a
year-distribution annotation flagging stale evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

from _test_support import load_run_py

rc = load_run_py(Path(__file__).resolve().parent.parent, "lra_run_ar")


class _Ab:
    def __init__(self, pmid, year=2021):
        self.pmid, self.year, self.title, self.abstract = pmid, year, "t", "body"


def _pkg(tmp_path, cards):
    p = tmp_path / "evidence_package.json"
    p.write_text(json.dumps({"synthesis": {"sub_verdicts": {}}, "cards": cards}))
    return str(p)


def test_load_card_anchors_from_clinical_and_competitor_cards(tmp_path):
    pkg = _pkg(
        tmp_path,
        [
            {
                "card_id": "clinical-precedent",
                "summary": {
                    "highest_clinical_stage": "phase_2",
                    "notable_failures": ["drugX"],
                    "n_agents_engaging_target": 4,
                },
            },
            {
                "card_id": "competitor-landscape",
                "summary": {"competitor_class": "approved_competitor", "n_competitor_programs": 5, "n_approved": 2},
            },
        ],
    )
    a = rc._load_card_anchors(pkg)
    assert "phase_2" in a["clinical"] and "notable_failures=True" in a["clinical"]
    assert "approved_competitor" in a["commercial"] and "n_competitor_programs=5" in a["commercial"]


def test_load_card_anchors_absent_cards_and_no_file(tmp_path):
    assert rc._load_card_anchors(_pkg(tmp_path, [])) == {}
    assert rc._load_card_anchors(None) == {}
    assert rc._load_card_anchors(str(tmp_path / "missing.json")) == {}


def test_recency_year_distribution_and_cutoff():
    abs_ = [_Ab("1", 2016), _Ab("2", 2023), _Ab("3", 2025), _Ab("4", year=None)]
    r = rc._recency(abs_, "2026")
    assert r["n_with_year"] == 3
    assert r["earliest_year"] == 2016 and r["latest_year"] == 2025
    assert r["n_recent_5y"] == 2  # cutoff 2022 → 2023 + 2025
    assert r["median_year"] == 2023


def test_recency_none_when_no_years():
    assert rc._recency([_Ab("1", None)], "2026") is None
    assert rc._recency([], "2026") is None


def test_run_wires_card_anchor_and_recency(monkeypatch, tmp_path):
    pkg = _pkg(
        tmp_path,
        [
            {
                "card_id": "clinical-precedent",
                "summary": {"highest_clinical_stage": "approved", "n_agents_engaging_target": 3},
            }
        ],
    )
    monkeypatch.setattr(
        rc.rl,
        "retrieve_axis",
        lambda target, indication, axis, **k: {
            "kept": ([_Ab("111", 2024)] if axis == "clinical" else []),
            "dropped": [],
        },
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
    res = rc.run("GENE", "some-indication", pkg, "2015", "2026", per_cat=1)
    clin = res["dimensions"]["clinical"]
    assert "clinical-precedent" in clin["anchor_verdict"] and "approved" in clin["anchor_verdict"]
    assert clin["recency"]["latest_year"] == 2024 and clin["recency"]["n_recent_5y"] == 1
