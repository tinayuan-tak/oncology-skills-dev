"""Offline guards for the intra-package COHERENCE step + the adversarial-survival post-check.
No Bedrock: the LLM is a stub. Verifies the four coherence detectors (measured-negative sub-verdict
or card cited as support; agent contradicts/tensions_with edge unsurfaced; intrinsic cross-card
SL-vs-no_partner contradiction), that surfacing clears them, that therapeutic_window is exempt, that
promotion is blocked with teeth; and the survival metric's containment discard + majority + gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from _test_support import load_run_py

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import adversarial_survival as AS  # noqa: E402
import hypothesis_core as hc  # noqa: E402

R = load_run_py(SCRIPTS.parent, "ce_run_coherence")

FIX = Path(__file__).resolve().parent / "fixtures"
PKG = FIX / "evidence_package_new_blocks.json"
RISK = FIX / "risk.json"
DOSSIER = FIX / "dossier.json"


# =============================== is_negative_verdict ===============================
def test_is_negative_verdict_polarity():
    assert hc.is_negative_verdict("non_dependent_paralog_buffered") is True
    assert hc.is_negative_verdict("no_partner_mapped") is True
    assert hc.is_negative_verdict("neither_viable") is True
    assert hc.is_negative_verdict("passenger_pattern") is True
    for v in (
        "strongly_selective_dependency",
        "strong_tumor_selective",
        "lineage_selective",
        "discordant_across_comparators",
        "constitutive_combinatorial_dependency",
    ):
        assert hc.is_negative_verdict(v) is False
    # gap verdicts are absence, NOT measured-negative (handled by absence-discipline)
    for v in ("insufficient", "data_unavailable", None, "not_informative"):
        assert hc.is_negative_verdict(v) is False


# =============================== (a) measured-negative sub-verdict cited as support ================
def test_negative_signal_cited_as_support_is_flagged():
    conv = {"dependency": "non_dependent_paralog_buffered", "mechanism": "well_characterized"}
    clauses = {"causal_rationale": {"support": ["dependency", "mechanism"], "surfaced": []}}
    v = hc.coherence_violations(clauses, conv, [], [], {"dependency", "mechanism"}, out_of_scope=set())
    assert v["causal_rationale"][0]["type"] == "negative_signal_asserted"
    assert v["causal_rationale"][0]["dimension"] == "dependency"


def test_surfacing_in_contradicting_citations_clears_it():
    conv = {"dependency": "non_dependent_paralog_buffered"}
    # the LLM cites dependency AND flags it in contradicting_citations → surfaced → cleared
    clauses = {"causal_rationale": {"support": ["dependency"], "surfaced": ["dependency"]}}
    assert hc.coherence_violations(clauses, conv, [], [], {"dependency"}, out_of_scope=set()) == {}


def test_surfacing_via_principal_tension_clears_it():
    conv = {"dependency": "non_dependent_paralog_buffered"}
    clauses = {"population": {"support": ["dependency"], "surfaced": []}}
    tensions = [{"statement": "dep absent", "citations": ["dependency", "paralog-buffering"]}]
    assert hc.coherence_violations(clauses, conv, [], tensions, {"dependency"}, out_of_scope=set()) == {}


def test_therapeutic_window_is_exempt_from_negative_signal_rule():
    conv = {"safety": "highly_constrained_safety_concern"}
    clauses = {"therapeutic_window": {"support": ["safety"], "surfaced": []}}
    assert hc.coherence_violations(clauses, conv, [], [], {"safety"}, out_of_scope=set()) == {}


def test_out_of_scope_negative_not_flagged():
    conv = {"surface_modality": "neither_viable"}
    clauses = {"therapeutic_hypothesis": {"support": ["surface_modality"], "surfaced": []}}
    v = hc.coherence_violations(clauses, conv, [], [], {"surface_modality"}, out_of_scope={"surface_modality"})
    assert v == {}


# =============================== (a2) card-grain measured-negative =================================
def test_card_grain_negative_call_cited_as_support_is_flagged():
    conv = {"dependency": "strongly_selective_dependency"}
    card_calls = {"partner-conditional-dependency": "no_partner_mapped"}
    clauses = {"causal_rationale": {"support": ["partner-conditional-dependency"], "surfaced": []}}
    v = hc.coherence_violations(
        clauses, conv, [], [], {"partner-conditional-dependency"}, out_of_scope=set(), card_calls=card_calls
    )
    assert v["causal_rationale"][0]["dimension"] == "partner-conditional-dependency"


# =============================== (b) agent contradiction edge ======================================
def test_agent_contradiction_edge_unsurfaced_is_flagged():
    conv = {"combinatorial_dependency": "constitutive_combinatorial_dependency"}
    edges = [
        {
            "type": "contradicts",
            "from_dimension": "combinatorial_dependency",
            "to_dimension": "differentiation",
            "rationale": "x",
            "citations": ["combinatorial_dependency", "differentiation"],
        }
    ]
    present = {"combinatorial_dependency", "differentiation"}
    clauses = {"therapeutic_hypothesis": {"support": ["combinatorial_dependency"], "surfaced": []}}
    v = hc.coherence_violations(clauses, conv, edges, [], present, out_of_scope=set())
    assert any(x["type"] == "edge_contradiction_unsurfaced" for x in v["therapeutic_hypothesis"])
    clauses2 = {"therapeutic_hypothesis": {"support": ["combinatorial_dependency"], "surfaced": ["differentiation"]}}
    assert hc.coherence_violations(clauses2, conv, edges, [], present, out_of_scope=set()) == {}


def test_edge_contradiction_surfaced_via_dimension_member_cards_is_credited():
    """FALSE POSITIVE: an edge names the DIMENSION 'safety', but the LLM surfaces the
    safety tension by citing safety's underlying CARDS (gnomad-lof-constraint, ...), not the bare
    'safety' token. The detector must credit that card-grain surfacing against the dimension-grain
    edge — else it false-fires and blocks promotion of clear positives (KRAS/ERBB2/BRAF)."""
    conv = {"dependency": "lineage_selective", "safety": "wt_constraint_mechanism_mismatch"}
    edges = [
        {
            "type": "tensions_with",
            "from_dimension": "safety",
            "to_dimension": "dependency-lineage-selectivity",
            "citations": ["safety", "dependency-lineage-selectivity"],
        }
    ]
    present = {"dependency_lineage_selectivity", "safety"}
    clauses = {"causal_rationale": {"support": ["dependency-lineage-selectivity"], "surfaced": []}}
    # safety surfaced ONLY via its member cards in a principal tension (not the 'safety' token)
    tensions = [
        {
            "statement": "Safety mismatch: highly_constrained, narrow window",
            "citations": [
                "gnomad-lof-constraint",
                "normal-tissue-liability-gtex",
                "clingen-dosage",
                "mouse-ko-phenotype",
            ],
        }
    ]
    assert hc.coherence_violations(clauses, conv, edges, tensions, present, out_of_scope=set()) == {}
    # sanity: with NO surfacing tension at all, it STILL fires (teeth preserved)
    v = hc.coherence_violations(clauses, conv, edges, [], present, out_of_scope=set())
    assert any(x["type"] == "edge_contradiction_unsurfaced" for x in v["causal_rationale"])


def test_negative_dimension_surfaced_via_member_card_tension_is_credited():
    """Same grain fix for check (a): a measured-negative DIMENSION cited as support is surfaced when
    any of its member cards appears in a tension."""
    conv = {"safety": "highly_constrained_safety_concern"}
    clauses = {"causal_rationale": {"support": ["safety"], "surfaced": []}}
    present = {"safety"}
    tensions = [{"statement": "constraint", "citations": ["gnomad-lof-constraint"]}]
    assert hc.coherence_violations(clauses, conv, [], tensions, present, out_of_scope=set()) == {}


def test_dimension_cards_matches_spine():
    """DRIFT GUARD: DIMENSION_CARDS must mirror the authoritative target-profile
    SUB_SKILL_CARDS ∘ SUB_SKILLS (skill_dir → short). If the spine composition changes, this fails so
    the mirrored crosswalk is updated in lockstep. Skips if target-profile is not importable."""
    import sys
    from pathlib import Path

    tp_scripts = Path(hc.__file__).resolve().parents[2] / "target-profile" / "scripts"
    if not tp_scripts.exists():
        import pytest

        pytest.skip("target-profile scripts not present")
    sys.path.insert(0, str(tp_scripts))
    sys.path.insert(0, str(tp_scripts.parents[1]))  # skills/ for _skills_common
    try:
        import tp_fanout as f
    except Exception as e:  # noqa: BLE001 — env without spine deps → skip, don't fail
        import pytest

        pytest.skip(f"tp_fanout not importable: {e}")
    s2s = dict(f.SUB_SKILLS)
    spine = {}
    for skill_dir, cards in f.SUB_SKILL_CARDS.items():
        spine.setdefault(s2s.get(skill_dir, skill_dir), set()).update(cards)
    ours = {k: set(v) for k, v in hc.DIMENSION_CARDS.items()}
    assert ours == spine, (
        f"DIMENSION_CARDS drift from SUB_SKILL_CARDS: "
        f"missing={ {k: spine[k] - ours.get(k, set()) for k in spine if spine[k] - ours.get(k, set())} } "
        f"extra={ {k: ours[k] - spine.get(k, set()) for k in ours if ours[k] - spine.get(k, set())} }"
    )


# =============================== (c) INTRINSIC SL-vs-no_partner (the task example) =================
def test_intrinsic_sl_without_mapped_partner_flagged_even_when_uncited():
    """The exact skeptic-found class: a clause rests on the SL/combination strategy while
    partner-conditional-dependency=no_partner_mapped is PRESENT (even if the clause never cites it)."""
    conv = {
        "combinatorial_dependency": "constitutive_combinatorial_dependency",
        "partner_conditional_dependency": "no_partner_mapped",
    }
    clauses = {"therapeutic_hypothesis": {"support": ["combinatorial-dependency"], "surfaced": []}}
    present = {"combinatorial-dependency", "partner_conditional_dependency"}
    v = hc.coherence_violations(clauses, conv, [], [], present, out_of_scope=set())
    labels = [x.get("label") for x in v["therapeutic_hypothesis"]]
    assert "combination_or_sl_strategy_without_mapped_partner" in labels
    # surfacing the no-partner line clears it
    clauses2 = {
        "therapeutic_hypothesis": {
            "support": ["combinatorial-dependency"],
            "surfaced": ["partner_conditional_dependency"],
        }
    }
    assert hc.coherence_violations(clauses2, conv, [], [], present, out_of_scope=set()) == {}


# =============================== run() end-to-end: coherence teeth =================================
def _stub_incoherent(system, user, name, schema, **kw):
    """causal_rationale cites surface_modality=neither_viable (a measured-negative, IN scope under
    modality_agnostic) as SUPPORT without surfacing it."""
    if name == "cross_edges":
        return {"edges": [], "principal_tensions": [], "evidence_paths": []}
    return {
        "causal_rationale": {"statement": "driver", "citations": ["dependency", "surface_modality"]},
        "therapeutic_hypothesis": {"statement": "hit it", "modality": "modality_agnostic", "citations": ["dependency"]},
        "population": {"statement": "all", "citations": ["dependency"]},
        "therapeutic_window": {"statement": "ok", "citations": ["safety"]},
        "evidence_grade": {"overall": "moderate", "per_line": []},
        "proposed_verdict": "advanceable",
        "proposed_verdict_reason": "x",
        "go_forth": {"next_evidence": "y"},
    }


def test_run_coherence_blocks_promotion_and_caps_verdict():
    r = R.run(str(PKG), str(RISK), "vague objective", "modality_agnostic", str(DOSSIER), synthesize_fn=_stub_incoherent)
    d = r["defensibility"]
    assert d["n_coherence_violations"] >= 1
    assert "intra_package_coherence_violations" in d["promotion_blockers"]
    assert d["promotable"] is False
    assert hc.VERDICT_RANK[r["verdict"]["computed"]] <= hc.VERDICT_RANK["advanceable_flagged"]
    assert "surface_modality" in json.dumps(d["coherence_violations"])


# =============================== adversarial-survival (stubbed) ===================================
def _hyp_result():
    return {
        "target": "T",
        "indication": "I",
        "hypothesis": {
            "causal_rationale": {"statement": "A", "citations": ["dependency"]},
            "therapeutic_hypothesis": {"statement": "B", "citations": ["dependency"]},
            "population": {"statement": "C", "citations": ["MSS"]},
            "therapeutic_window": {"statement": "D", "citations": ["safety"]},
        },
    }


def test_survival_containment_discards_uncontained_refutation():
    def stub(system, user, name, schema, **kw):
        return {
            "clauses": [
                {"clause": k, "refuted": True, "refutation": "bad", "cited": ["totally_made_up_token_xyz"]}
                for k in ("causal_rationale", "therapeutic_hypothesis", "population", "therapeutic_window")
            ]
        }

    r = AS.adversarial_survival(_hyp_result(), str(PKG), str(RISK), str(DOSSIER), n_skeptics=3, synthesize_fn=stub)
    assert r["score"] == 1.0
    assert all(c["survives"] for c in r["clauses"].values())


def test_survival_majority_refutation_marks_not_survived():
    def stub(system, user, name, schema, **kw):
        return {
            "clauses": [
                {
                    "clause": "causal_rationale",
                    "refuted": True,
                    "refutation": "dependency does not support this",
                    "cited": ["dependency"],
                },
                {"clause": "therapeutic_hypothesis", "refuted": False, "refutation": "", "cited": []},
                {"clause": "population", "refuted": False, "refutation": "", "cited": []},
                {"clause": "therapeutic_window", "refuted": False, "refutation": "", "cited": []},
            ]
        }

    r = AS.adversarial_survival(_hyp_result(), str(PKG), str(RISK), str(DOSSIER), n_skeptics=3, synthesize_fn=stub)
    assert r["clauses"]["causal_rationale"]["survives"] is False
    assert r["clauses"]["causal_rationale"]["valid_refutations"] == 3
    assert r["score"] == 0.75
    gate = AS.adversarial_survival_gate(r, threshold=0.8)
    assert gate["passed"] is False and gate["below_threshold"] is True
    assert "causal_rationale" in gate["non_surviving_clauses"]


def test_survival_gate_pass():
    r = {"score": 1.0, "clauses": {"a": {"survives": True}}}
    assert AS.adversarial_survival_gate(r, 0.75)["passed"] is True


# =============================== (scope-aware) out-of-scope-modality exclusion =====================
def test_token_out_of_scope_maps_cards_to_dimensions():
    oos = {hc._norm(d) for d in hc.out_of_scope_dims("small_molecule")}  # {"surface_modality"}
    # surface/biologics CARDS belong to the out-of-scope surface_modality dimension
    assert hc.token_out_of_scope(hc._norm("adc-tce-modality-fit"), oos) is True
    assert hc.token_out_of_scope(hc._norm("modality-therapeutic-window"), oos) is True
    assert hc.token_out_of_scope(hc._norm("surface_modality"), oos) is True
    # dependency / SL / genomic cards stay IN scope (never excluded → MARK2-style primary preserved)
    for keep in (
        "crispr-rnai-dependency-concordance",
        "partner-conditional-dependency",
        "combinatorial-dependency",
        "dependency",
        "safety",
    ):
        assert hc.token_out_of_scope(hc._norm(keep), oos) is False
    # for an ADC objective, tractability (small-molecule) cards are the out-of-scope ones
    oos_adc = {hc._norm(d) for d in hc.out_of_scope_dims("adc")}  # {"tractability_sm"}
    assert hc.token_out_of_scope(hc._norm("known-drug-tractability"), oos_adc) is True
    assert hc.token_out_of_scope(hc._norm("adc-tce-modality-fit"), oos_adc) is False


def test_out_of_scope_card_violation_not_flagged_but_in_scope_is():
    """The KRAS defect: a small-molecule clause citing an ADC/surface card as support must NOT be a
    coherence violation (out-of-scope modality); the SAME clause citing an in-scope negative
    dependency line MUST be."""
    conv = {"dependency": "non_dependent_paralog_buffered"}
    card_calls = {
        "adc-tce-modality-fit": "neither_viable",
        "crispr-rnai-dependency-concordance": "moderately_concordant_non_dependent",
    }
    present = {hc._norm(x) for x in list(conv) + list(card_calls)}
    oos = hc.out_of_scope_dims("small_molecule")  # surface_modality out of scope

    # out-of-scope surface card cited as support → NO violation (scope-aware)
    only_surface = {"therapeutic_hypothesis": {"support": ["adc-tce-modality-fit"], "surfaced": []}}
    assert hc.coherence_violations(only_surface, conv, [], [], present, out_of_scope=oos, card_calls=card_calls) == {}
    # WITHOUT the modality scope (modality_agnostic) the SAME cite IS a violation — proves scope, not a blanket drop
    assert hc.coherence_violations(only_surface, conv, [], [], present, out_of_scope=set(), card_calls=card_calls) != {}

    # in-scope negative dependency card cited as support → STILL a violation (primary thesis preserved)
    in_scope = {"causal_rationale": {"support": ["crispr-rnai-dependency-concordance"], "surfaced": []}}
    v = hc.coherence_violations(in_scope, conv, [], [], present, out_of_scope=oos, card_calls=card_calls)
    assert "causal_rationale" in v


def test_mark2_style_sl_no_partner_survives_modality_scope():
    """MARK2 guard-rail: the intrinsic SL-without-mapped-partner violation is in-scope for a
    small-molecule objective and must NOT be excluded by the surface_modality scope."""
    conv = {
        "combinatorial_dependency": "constitutive_combinatorial_dependency",
        "partner_conditional_dependency": "no_partner_mapped",
    }
    present = {hc._norm(x) for x in list(conv)}
    clauses = {"therapeutic_hypothesis": {"support": ["combinatorial-dependency"], "surfaced": []}}
    v = hc.coherence_violations(clauses, conv, [], [], present, out_of_scope=hc.out_of_scope_dims("small_molecule"))
    labels = [x.get("label") for x in v.get("therapeutic_hypothesis", [])]
    assert "combination_or_sl_strategy_without_mapped_partner" in labels
