"""validate_gold — held-out gold validation harness for risk_rollup [3A] bins (offline, synthetic pkgs).

Pins the SCORER logic against packages with known sub-verdicts, so the harness itself is trustworthy
before it is run live on real evidence packages:
  - biological maps 1:1 (dependency-driven bin);
  - a `selectivity` gold entry is scored against the SAFETY bin (selectivity folds into the safety
    conjunction — there is no standalone selectivity dim);
  - hit / miss / no_package / unknown_dim outcomes;
  - score_gold aggregates per-dimension accuracy + lists misses + counts no_package;
  - load_gold scores only gold_upheld (review_queue is carried, never silently scored).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import validate_gold as vg  # noqa: E402


def _pkg(dep=None, mech="well_characterized", safety="tolerant_reduced_safety_risk",
         sel=None, tract="well_covered", cards=None):
    sv = {"mechanism": {"verdict": mech}, "safety": {"verdict": safety},
          "tractability_sm": {"verdict": tract}}
    if dep:
        sv["dependency"] = {"verdict": dep}
    if sel:
        sv["selectivity"] = {"verdict": sel}
    return {"synthesis": {"sub_verdicts": sv}, "cards": cards or []}


def _entry(dim, target, modality, expected, label="positive", indication="X"):
    return {"_dimension": dim, "target": target, "modality": modality,
            "expected_bin": expected, "label": label, "indication": indication, "confidence": "high"}


# ---- score_entry: biological (1:1) ----
def test_biological_nondependent_scores_high():
    e = _entry("biological", "FOO", "small_molecule", "HIGH", label="negative")
    r = vg.score_entry(e, _pkg(dep="non_dependent"))
    assert r["rollup_dim"] == "biological" and r["got_bin"] == "HIGH" and r["outcome"] == "hit"


def test_biological_lineage_selective_scores_low():
    e = _entry("biological", "KRAS", "small_molecule", "LOW", label="positive")
    r = vg.score_entry(e, _pkg(dep="lineage_selective"))
    assert r["got_bin"] == "LOW" and r["outcome"] == "hit"


# ---- score_entry: selectivity folds into the SAFETY bin ----
def test_selectivity_entry_scored_against_safety_bin():
    # a broadly-normal (not_selective) surface antigen → HIGH safety (surface escalator) → expected HIGH
    e = _entry("selectivity", "EGFR", "antibody", "HIGH", label="negative")
    r = vg.score_entry(e, _pkg(sel="not_selective"))
    assert r["rollup_dim"] == "safety" and r["got_bin"] == "HIGH" and r["outcome"] == "hit"
    # a tumor-selective surface antigen (no selectivity escalator) → LOW safety → expected LOW
    e2 = _entry("selectivity", "FOLR1", "adc", "LOW", label="positive")
    r2 = vg.score_entry(e2, _pkg(sel="strong_tumor_selective"))
    assert r2["rollup_dim"] == "safety" and r2["got_bin"] == "LOW" and r2["outcome"] == "hit"


# ---- outcomes: no_package + miss ----
def test_no_package_outcome():
    r = vg.score_entry(_entry("biological", "FOO", "small_molecule", "LOW"), None)
    assert r["outcome"] == "no_package" and r["got_bin"] is None


def test_miss_is_flagged():
    # expected LOW but a non_dependent pkg yields HIGH → miss (not a silent pass)
    e = _entry("biological", "FOO", "small_molecule", "LOW", label="positive")
    r = vg.score_entry(e, _pkg(dep="non_dependent"))
    assert r["got_bin"] == "HIGH" and r["outcome"] == "miss"


# ---- score_gold aggregation ----
def test_score_gold_aggregates_and_lists_misses():
    entries = [
        _entry("biological", "A", "small_molecule", "LOW", indication="i1"),   # hit (lineage_selective)
        _entry("biological", "B", "small_molecule", "LOW", indication="i2"),   # miss (non_dependent->HIGH)
        _entry("biological", "C", "small_molecule", "LOW", indication="i3"),   # no_package
    ]
    pkgs = {("A", "i1"): _pkg(dep="lineage_selective"), ("B", "i2"): _pkg(dep="non_dependent")}
    rep = vg.score_gold(entries, lambda t, i: pkgs.get((t, i)))
    bio = rep["by_dimension"]["biological"]
    assert bio["hit"] == 1 and bio["miss"] == 1 and bio["no_package"] == 1
    assert bio["accuracy"] == 0.5 and bio["scored"] == 2
    assert any("B/i2" in m for m in bio["misses"])
    assert rep["overall"]["scored"] == 2 and rep["overall"]["no_package"] == 1


# ---- load_gold: only gold_upheld is scored ----
def test_load_gold_flattens_upheld_only(tmp_path):
    doc = {"assembled": [
        {"dimension": "safety",
         "gold_upheld": [{"target": "T1", "indication": "i", "modality": "small_molecule",
                          "expected_bin": "LOW", "label": "positive"}],
         "review_queue": [{"target": "T2", "indication": "i", "modality": "adc",
                           "expected_bin": "HIGH", "label": "negative"}]},
    ]}
    p = tmp_path / "gold.json"
    p.write_text(json.dumps(doc))
    entries, review = vg.load_gold(p)
    assert len(entries) == 1 and entries[0]["target"] == "T1" and entries[0]["_dimension"] == "safety"
    assert len(review) == 1 and review[0]["target"] == "T2"
