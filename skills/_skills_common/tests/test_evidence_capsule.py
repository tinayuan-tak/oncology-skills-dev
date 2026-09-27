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
            (),  # declares no numeric_anchors → the hint scan still runs for this card
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


# ── L2a per-source CONCEPT (#1868, epic #1507 Arm B) ──────────────────────────────────────────────
def _presence_cards():
    """Two verdict-bearing presence source cards + one non-registered card."""
    return [
        {
            "card_id": "tumor-rna-distribution",
            "measurement_type": "tumor_expression_distribution",
            "summary": {
                "tumor_expression_class": "broadly_high",
                "distribution_pattern": "continuous",
                "allgene_percentile_class": "top_1pct",
                "allgene_percentile": 99.7415,
                "fraction_tumor_above_normal_p95": 0.7369,
                "detectable_fraction": 1.0,
            },
        },
        {
            "card_id": "tumor-scrna-celltype-expression",
            "measurement_type": "sc_tumor_celltype_expression",
            "summary": {
                "sc_expression_class": "malignant_broadly_detected",
                "within_tumor_coverage_class": "high",
                "tce_homogeneity_class": "homogeneous",
                "tce_antigen_escape_class": "escape_risk_low",
                "malignant_detection_fraction": 0.8948,
                "fraction_donors_broadly_detecting": 0.9529,
            },
        },
        {
            "card_id": "b-dist",  # not in _SOURCE_CONCEPTS → no concept key
            "summary": {"dependency_class": "strongly_selective", "median_chronos_panel": -0.457},
        },
    ]


def test_source_concept_composes_multiple_dimensions_distinct_from_class():
    caps = EC.emit_capsules(_presence_cards(), "COADREAD")["capsules"]
    tr = caps["tumor-rna-distribution"]
    # coarse class is a SINGLE *_class VALUE; the concept COMPOSES several orthogonal dimensions
    assert tr["class"] in ("broadly_high", "top_1pct"), "sanity: coarse class is a single *_class value"
    con = tr["concept"]
    assert con["source"] == "tumor_rna"
    assert con["token"] == "broadly_high_continuous_top_1pct"
    assert con["token"] != tr["class"], "concept must be DISTINCT from the coarse verdict class"
    assert [d["field"] for d in con["dimensions"]] == [
        "tumor_expression_class",
        "distribution_pattern",
        "allgene_percentile_class",
    ]
    # curated retained-attr selection carries a declared scale (no bare numbers)
    assert {a["metric"] for a in con["retained_attrs"]} == {
        "allgene_percentile",
        "fraction_tumor_above_normal_p95",
        "detectable_fraction",
    }
    assert all("scale" in a for a in con["retained_attrs"])
    sc = caps["tumor-scrna-celltype-expression"]["concept"]
    assert sc["token"] == "malignant_broadly_detected_high_homogeneous_escape_risk_low"


def test_source_concept_omitted_for_unregistered_and_thin_cards():
    # non-registered card → no concept key (byte-stable for every non-presence skill)
    caps = EC.emit_capsules(_presence_cards(), "COADREAD")["capsules"]
    assert "concept" not in caps["b-dist"]
    # thin (non-verdict-bearing) presence card → no concept (matches the full-only tail)
    thin = EC.emit_capsules(_presence_cards(), "COADREAD", verdict_card_ids={"b-dist"})["capsules"]
    assert "concept" not in thin["tumor-rna-distribution"]


def test_source_concept_drops_unmeasured_dimensions_and_attrs():
    # MUTATION: an unmeasured dimension must not fabricate a token segment; a missing attr is dropped.
    cards = [
        {
            "card_id": "tumor-rna-distribution",
            "measurement_type": "tumor_expression_distribution",
            "summary": {
                "tumor_expression_class": "broadly_high",
                "distribution_pattern": "data_unavailable",  # unmeasured → skipped
                "allgene_percentile": 99.7415,  # only this attr present
            },
        }
    ]
    con = EC.emit_capsules(cards, "COADREAD")["capsules"]["tumor-rna-distribution"]["concept"]
    assert con["token"] == "broadly_high", "unmeasured dimension leaked into the token"
    assert [a["metric"] for a in con["retained_attrs"]] == ["allgene_percentile"]
    # MUTATION: ALL dimensions unmeasured → no concept key at all (byte-stable)
    cards2 = [
        {
            "card_id": "tumor-rna-distribution",
            "summary": {"allgene_percentile": 99.7, "tumor_expression_class": None},
        }
    ]
    assert "concept" not in EC.emit_capsules(cards2, "COADREAD")["capsules"]["tumor-rna-distribution"]


def test_source_concept_is_verdict_inert_and_hash_stable():
    a = json.dumps(EC.emit_capsules(_presence_cards(), "COADREAD"), sort_keys=True, default=str)
    b = json.dumps(EC.emit_capsules(_presence_cards(), "COADREAD"), sort_keys=True, default=str)
    assert a == b
    # concept carries NO signal/tier/corroboration key — pure presentation-support
    con = EC.emit_capsules(_presence_cards(), "COADREAD")["capsules"]["tumor-rna-distribution"]["concept"]
    assert not ({"signal", "tier", "corroboration", "verdict"} & set(con))
