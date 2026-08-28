"""evidence_capsule — the complete-but-limited per-card data package (5 selector shapes + card floor).
Deterministic, no Bedrock. Verdict-INERT projection over resolved cards."""
from __future__ import annotations
import json, sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import evidence_capsule as EC  # noqa: E402


def _cards():
    return [
        {"card_id": "b-dist", "summary": {
            "dependency_class": "strongly_selective", "median_chronos_panel": -0.457,
            "selectivity_index": 0.85, "n_cell_lines_evaluated": 1538,
            "per_oncotree_code_stats": [
                {"oncotree_code": "COADREAD", "median_chronos": -1.28, "n": 19},
                {"oncotree_code": "PAAD", "median_chronos": -1.87, "n": 72},
                {"oncotree_code": "LXSC", "median_chronos": -0.20, "n": 7}]}},
        {"card_id": "a-paralog", "summary": {
            "paralog_buffering_class": "strong", "strongest_paralog_symbol": "NRAS", "n_paralogs_annotated": 12}},
        {"card_id": "c-missing", "summary": {}, "_missing": True},
    ]


def test_card_floor_every_card_represented():
    pkg = EC.emit_capsules(_cards(), "COADREAD")
    ids = {m["card_id"] for m in pkg["manifest"]}
    assert ids == {"a-paralog", "b-dist", "c-missing"}          # nothing vanishes
    assert all(c["_complete"] for c in pkg["capsules"].values())
    st = {m["card_id"]: m["status"] for m in pkg["manifest"]}
    assert st["c-missing"] == "absent" and pkg["capsules"]["c-missing"]["evidence_state"] == "data_unavailable"


def test_top_k_strata_indication_plus_extremes():
    caps = EC.emit_capsules(_cards(), "COADREAD")["capsules"]
    tk = caps["b-dist"]["top_k_strata"]
    roles = {r["role"]: r for r in tk}
    assert roles["INDICATION"]["stratum"] == "COADREAD" and roles["INDICATION"]["value"] == -1.28
    assert roles["extreme_strongest"]["stratum"] == "PAAD"       # lowest chronos = most dependent
    assert roles["extreme_weakest"]["stratum"] == "LXSC"


def test_numeric_anchors_and_provenance_and_caveats():
    caps = EC.emit_capsules(_cards(), "COADREAD")["capsules"]
    anch = {a["metric"] for a in caps["b-dist"]["numeric_anchors"]}
    assert "selectivity_index" in anch                          # anchor-hint field picked
    assert "n_cell_lines_evaluated" in caps["b-dist"]["n_basis"]
    assert "paralog_buffering_class" in caps["a-paralog"]["sibling_caveats"]   # caveat-hint field (real key)


def test_conflict_pair_across_same_measurement_type(monkeypatch):
    import _skills_common.evidence_capsule as M
    monkeypatch.setattr(M, "_card_meta", lambda cid: {"hi": ("mt_x", None), "lo": ("mt_x", None)}.get(cid, (None, None)))
    cards = [{"card_id": "hi", "summary": {"x_class": "strongly_selective"}},
             {"card_id": "lo", "summary": {"x_class": "no_dependency"}}]
    caps = EC.emit_capsules(cards, None)["capsules"]
    assert caps["hi"]["conflict_pairs"] and caps["hi"]["conflict_pairs"][0]["measurement_type"] == "mt_x"


def test_data_quality_flag_activating_vs_inactivation():
    cards = [{"card_id": "gm", "summary": {
        "functional_direction": "activating", "patient_functional_state_class": "sporadic_biallelic_inactivation"}}]
    caps = EC.emit_capsules(cards, "COADREAD")["capsules"]
    dq = caps["gm"]["data_quality_flags"]
    assert dq and "loss-of-function" in dq[0]["flag"].lower()


def test_thin_vs_full_via_verdict_card_ids():
    pkg = EC.emit_capsules(_cards(), "COADREAD", verdict_card_ids={"b-dist"})
    assert "top_k_strata" in pkg["capsules"]["b-dist"]           # full
    assert "top_k_strata" not in pkg["capsules"]["a-paralog"]     # thin (signal+anchor only)
    assert {m["card_id"]: m["status"] for m in pkg["manifest"]}["a-paralog"] == "thin"


def test_hash_stable():
    a = json.dumps(EC.emit_capsules(_cards(), "COADREAD"), sort_keys=True, default=str)
    b = json.dumps(EC.emit_capsules(_cards(), "COADREAD"), sort_keys=True, default=str)
    assert a == b
