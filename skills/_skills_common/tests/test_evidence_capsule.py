"""evidence_capsule — the complete-but-limited per-card data package (5 selector shapes + card floor).
Deterministic, no Bedrock. Verdict-INERT projection over resolved cards."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import evidence_capsule as EC  # noqa: E402


def _cards():
    return [
        {
            "card_id": "b-dist",
            "summary": {
                "dependency_class": "strongly_selective",
                "median_chronos_panel": -0.457,
                "selectivity_index": 0.85,
                "n_cell_lines_evaluated": 1538,
                "per_oncotree_code_stats": [
                    {"oncotree_code": "COADREAD", "median_chronos": -1.28, "n": 19},
                    {"oncotree_code": "PAAD", "median_chronos": -1.87, "n": 72},
                    {"oncotree_code": "LXSC", "median_chronos": -0.20, "n": 7},
                ],
            },
        },
        {
            "card_id": "a-paralog",
            "summary": {
                "paralog_buffering_class": "strong",
                "strongest_paralog_symbol": "NRAS",
                "n_paralogs_annotated": 12,
            },
        },
        {"card_id": "c-missing", "summary": {}, "_missing": True},
    ]


def test_card_floor_every_card_represented():
    pkg = EC.emit_capsules(_cards(), "COADREAD")
    ids = {m["card_id"] for m in pkg["manifest"]}
    assert ids == {"a-paralog", "b-dist", "c-missing"}  # nothing vanishes
    assert all(c["_complete"] for c in pkg["capsules"].values())
    st = {m["card_id"]: m["status"] for m in pkg["manifest"]}
    assert st["c-missing"] == "absent" and pkg["capsules"]["c-missing"]["evidence_state"] == "data_unavailable"


def test_top_k_strata_indication_plus_extremes():
    caps = EC.emit_capsules(_cards(), "COADREAD")["capsules"]
    tk = caps["b-dist"]["top_k_strata"]
    roles = {r["role"]: r for r in tk}
    assert roles["INDICATION"]["stratum"] == "COADREAD" and roles["INDICATION"]["value"] == -1.28
    assert roles["extreme_strongest"]["stratum"] == "PAAD"  # lowest chronos = most dependent
    assert roles["extreme_weakest"]["stratum"] == "LXSC"


def test_numeric_anchors_and_provenance_and_caveats():
    caps = EC.emit_capsules(_cards(), "COADREAD")["capsules"]
    anch = {a["metric"] for a in caps["b-dist"]["numeric_anchors"]}
    assert "selectivity_index" in anch  # anchor-hint field picked
    assert "n_cell_lines_evaluated" in caps["b-dist"]["n_basis"]
    assert "paralog_buffering_class" in caps["a-paralog"]["sibling_caveats"]  # caveat-hint field (real key)


def test_categorical_anchors_opt_in_only():
    # A clinical card whose decision-relevant datum is a STRING stage + a LIST of agents: invisible to
    # numeric_anchors, surfaced only when the card opts in via config['categorical_fields'].
    cards = [
        {
            "card_id": "clinical-precedent",
            "summary": {
                "clinical_precedent_class": "trial_precedent_present",
                "highest_clinical_stage": "approved",
                "approved_agents": ["adagrasib", "sotorasib"],
                "n_trials": 170,
            },
        }
    ]
    # no config → categorical_anchors is None (byte-stable for every non-opted card)
    plain = EC.emit_capsules(cards, "COADREAD")["capsules"]["clinical-precedent"]
    assert plain["categorical_anchors"] is None
    # opted in → the stage label + agent list ride through verbatim
    cfg = {"clinical-precedent": {"categorical_fields": ["highest_clinical_stage", "approved_agents"]}}
    ca = EC.emit_capsules(cards, "COADREAD", config=cfg)["capsules"]["clinical-precedent"]["categorical_anchors"]
    got = {a["field"]: a["value"] for a in ca}
    assert got["highest_clinical_stage"] == "approved"
    assert got["approved_agents"] == ["adagrasib", "sotorasib"]


def test_categorical_anchors_list_capped():
    cards = [{"card_id": "x", "summary": {"agents": [f"d{i}" for i in range(20)]}}]
    cfg = {"x": {"categorical_fields": ["agents"]}}
    ca = EC.emit_capsules(cards, None, config=cfg)["capsules"]["x"]["categorical_anchors"]
    assert len(ca[0]["value"]) == 6  # top-k capped for token budget


def test_capsule_contract_primary_class_beats_alphabetical(monkeypatch):
    # Multi-class card: alphabetical-first picks 'alphafold_confidence_class'; the declared primary is the
    # verdict-driving 'structural_ligandability_class'. Contract must win.
    monkeypatch.setattr(
        EC,
        "_card_capsule_contract",
        lambda cid: (
            "structural_ligandability_class",
            ("structural_ligandability_class", "has_experimental_cocrystal"),
        ),
    )
    cards = [
        {
            "card_id": "structure-features-static",
            "summary": {
                "alphafold_confidence_class": "high",
                "structural_ligandability_class": "experimental_ligandable",
                "has_experimental_cocrystal": True,
                "method_version": "0.1.0",
            },
        }
    ]
    cap = EC.emit_capsules(cards, "COADREAD")["capsules"]["structure-features-static"]
    assert cap["class"] == "experimental_ligandable"  # declared primary, NOT 'high'
    got = {a["field"]: a["value"] for a in cap["categorical_anchors"]}
    assert got == {"structural_ligandability_class": "experimental_ligandable", "has_experimental_cocrystal": True}


def test_echo_denylist_excludes_provenance_from_heuristics():
    # method_version / target / indication are request-echo — must not leak into caveat/anchor heuristics.
    cards = [
        {
            "card_id": "z",
            "summary": {"coverage": "partial", "method_version": "1.2.3", "target": "KRAS", "indication": "COADREAD"},
        }
    ]
    caps = EC.emit_capsules(cards, "COADREAD")["capsules"]["z"]
    sib = caps.get("sibling_caveats") or {}
    assert "coverage" in sib  # real caveat-hint field kept
    assert "method_version" not in sib and "target" not in sib  # echo fields denied


def test_conflict_pair_across_same_measurement_type(monkeypatch):
    import _skills_common.evidence_capsule as M

    monkeypatch.setattr(
        M, "_card_meta", lambda cid: {"hi": ("mt_x", None), "lo": ("mt_x", None)}.get(cid, (None, None))
    )
    cards = [
        {"card_id": "hi", "summary": {"x_class": "strongly_selective"}},
        {"card_id": "lo", "summary": {"x_class": "no_dependency"}},
    ]
    caps = EC.emit_capsules(cards, None)["capsules"]
    assert caps["hi"]["conflict_pairs"] and caps["hi"]["conflict_pairs"][0]["measurement_type"] == "mt_x"


def test_a_card_that_did_not_measure_cannot_conflict_with_one_that_did(monkeypatch):
    """The conflict test is a tier DISTANCE (`max - min >= 2`), so it reads the presence ordinal as a
    number. That is exactly why `unmeasured` is off the ordinal: give the abstention any value and a card
    outside its source's coverage manufactures a contradiction against every card reading strong/moderate.
    Here `strongly_selective` (3) vs an unread card would be a 3-or-more spread on any numbering."""
    import _skills_common.evidence_capsule as M

    monkeypatch.setattr(
        M, "_card_meta", lambda cid: {"hi": ("mt_x", None), "gap": ("mt_x", None)}.get(cid, (None, None))
    )
    cards = [
        {"card_id": "hi", "summary": {"x_class": "strongly_selective"}},
        {"card_id": "gap", "summary": {"x_class": "data_unavailable"}},
    ]
    caps = EC.emit_capsules(cards, None)["capsules"]
    assert not caps["hi"].get("conflict_pairs"), "a coverage gap is not a disagreement"
    assert not caps["gap"].get("conflict_pairs")


def test_two_real_disagreements_still_conflict_when_a_third_card_abstains(monkeypatch):
    """The non-vacuity partner: dropping abstentions must not disable the detector for the cards that DID
    measure — otherwise this fix would silence real contradictions whenever coverage was incomplete."""
    import _skills_common.evidence_capsule as M

    monkeypatch.setattr(
        M,
        "_card_meta",
        lambda cid: {"hi": ("mt_x", None), "lo": ("mt_x", None), "gap": ("mt_x", None)}.get(cid, (None, None)),
    )
    cards = [
        {"card_id": "hi", "summary": {"x_class": "strongly_selective"}},
        {"card_id": "lo", "summary": {"x_class": "no_dependency"}},
        {"card_id": "gap", "summary": {"x_class": "data_unavailable"}},
    ]
    caps = EC.emit_capsules(cards, None)["capsules"]
    assert caps["hi"]["conflict_pairs"], "the real hi/lo disagreement must survive"
    others = {o["card"] for o in caps["hi"]["conflict_pairs"][0]["other_sources"]}
    assert others == {"lo"}, f"the abstaining card must not be listed as a disagreeing source: {others}"


def test_data_quality_flag_activating_vs_inactivation():
    cards = [
        {
            "card_id": "gm",
            "summary": {
                "functional_direction": "activating",
                "patient_functional_state_class": "sporadic_biallelic_inactivation",
            },
        }
    ]
    caps = EC.emit_capsules(cards, "COADREAD")["capsules"]
    dq = caps["gm"]["data_quality_flags"]
    assert dq and "loss-of-function" in dq[0]["flag"].lower()


def test_thin_vs_full_via_verdict_card_ids():
    pkg = EC.emit_capsules(_cards(), "COADREAD", verdict_card_ids={"b-dist"})
    assert "top_k_strata" in pkg["capsules"]["b-dist"]  # full
    assert "top_k_strata" not in pkg["capsules"]["a-paralog"]  # thin (signal+anchor only)
    assert {m["card_id"]: m["status"] for m in pkg["manifest"]}["a-paralog"] == "thin"


def test_hash_stable():
    a = json.dumps(EC.emit_capsules(_cards(), "COADREAD"), sort_keys=True, default=str)
    b = json.dumps(EC.emit_capsules(_cards(), "COADREAD"), sort_keys=True, default=str)
    assert a == b
