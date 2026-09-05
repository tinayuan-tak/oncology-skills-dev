"""cross-evidence-hypothesis — offline guards for the deterministic spine + the two-call
pipeline (LLM injected). No Bedrock, no S3: the LLM is a stub `synthesize_fn`, the panel is a
synthesized fixture carrying the three landed blocks (hard_gates + subtype_resolved +
evidence_substrate). Verifies: fail-closed gate-complete clamp respects hard_gates; correlated cards
discounted; subtype tokens traceable; retrieve-don't-recall + absence-discipline WITH TEETH; degraded
mode; byte/schema sanity."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from _test_support import load_run_py

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import hypothesis_core as hc  # noqa: E402

R = load_run_py(SCRIPTS.parent, "ce_run_main")

FIX = Path(__file__).resolve().parent / "fixtures"
PKG = FIX / "evidence_package_new_blocks.json"
DOSSIER = FIX / "dossier.json"
RISK = FIX / "risk.json"


def _pkg():
    return json.loads(PKG.read_text())


# =============================== deterministic gate ceiling ===============================
def test_ceiling_clean_hard_gates_is_advanceable():
    g = hc.gate_ceiling(_pkg())
    assert g["ceiling"] == "advanceable"
    assert g["hard_gates_present"] is True
    assert g["active_vetoes"] == [] and g["blind_gates"] == []
    # the modality-scoped surface foreclosure is surfaced, NOT a blanket veto
    assert any("surface_modality" in e for e in g["excluded"])


def test_ceiling_fired_hard_gate_declines():
    pkg = _pkg()
    for row in pkg["synthesis"]["recommendation_gate"]["hard_gates"]:
        if row["short"] == "dependency" and row["verdict"] == "non_dependent":
            row["status"] = "fired"
    g = hc.gate_ceiling(pkg)
    assert g["ceiling"] == "declined"
    assert "dependency:non_dependent" in g["active_vetoes"]


def test_ceiling_blind_gated_VETO_axis_fails_closed_to_declined():
    """A VETO-capable axis (dependency) with no verdict this run (status=blind, disposition=gated) →
    the veto cannot be ruled out → fail-closed to declined."""
    pkg = _pkg()
    hit = False
    for row in pkg["synthesis"]["recommendation_gate"]["hard_gates"]:
        if row["short"] == "dependency":
            row["status"] = "blind"; row["live_verdict"] = None; hit = True
    assert hit, "fixture must carry a dependency hard-gate"
    g = hc.gate_ceiling(pkg)
    assert g["ceiling"] == "declined"
    assert g["fail_closed"] is True
    assert any(t.startswith("dependency:") for t in g["blind_gates"])


def test_ceiling_blind_gated_HOLD_axis_fails_closed_to_hold_not_declined():
    """a HOLD-grade axis (safety) blind → fail-closed to a HOLD (advanceable_flagged), NEVER a
    decline — safety mirrors the spine's safety→hold policy (mechanism-conditionable window)."""
    pkg = _pkg()
    for row in pkg["synthesis"]["recommendation_gate"]["hard_gates"]:
        # neutralize any dependency veto so safety is the load-bearing blind axis
        if row["short"] == "dependency":
            row["status"] = "latent"
        if row["short"] == "safety":
            row["status"] = "blind"; row["live_verdict"] = None
    g = hc.gate_ceiling(pkg)
    assert g["ceiling"] == "advanceable_flagged", g
    assert "safety" not in [t.split(":")[0] for t in g["blind_gates"]]  # not a fail-closed veto


def test_ceiling_fired_safety_gate_is_hold_not_decline():
    """a FIRED safety hard-gate caps at advanceable_flagged (hold), NEVER declined — even a
    hold-grade verdict formerly in SAFETY_KILL (highly_constrained_safety_concern). Approved ADCs /
    recover targets were being wrongly killed on hold-grade safety."""
    pkg = _pkg()
    for row in pkg["synthesis"]["recommendation_gate"]["hard_gates"]:
        if row["short"] == "dependency":
            row["status"] = "latent"
        if row["short"] == "safety":
            row["status"] = "fired"; row["verdict"] = "highly_constrained_safety_concern"
            row["live_verdict"] = "highly_constrained_safety_concern"
    # make the sub-verdict agree so the hold-grade line also sees it
    pkg["synthesis"]["sub_verdicts"]["safety"] = {"verdict": "highly_constrained_safety_concern"}
    g = hc.gate_ceiling(pkg)
    assert g["ceiling"] == "advanceable_flagged", g
    assert not any(t.startswith("safety:") for t in g["active_vetoes"])  # safety is not a veto


def test_ceiling_dependency_veto_excluded_for_surface_biologic():
    """dependency is out-of-scope for a surface/ligand biologic (adc/bite_tce/antibody), so a
    fired dependency:non_dependent must NOT veto — a surface antigen need not be a genetic dependency
    (e.g. DLL3/tarlatamab). The SAME package DOES decline under a small-molecule modality."""
    pkg = _pkg()
    for row in pkg["synthesis"]["recommendation_gate"]["hard_gates"]:
        if row["short"] == "dependency":
            row["status"] = "fired"; row["verdict"] = "non_dependent"; row["live_verdict"] = "non_dependent"
        if row["short"] == "safety":
            row["status"] = "latent"
    assert hc.gate_ceiling(pkg, modality="small_molecule")["ceiling"] == "declined"   # SM: dependency decides
    g = hc.gate_ceiling(pkg, modality="bite_tce")                                     # TCE: dependency out-of-scope
    assert g["ceiling"] != "declined", g
    assert any(t.startswith("dependency:") for t in g["excluded"])


def test_ceiling_non_dependent_mechanism_excluded_for_mutant_selective():
    """a fired dependency:non_dependent must NOT veto a MUTANT-SELECTIVE / GoF driver (signalled by
    safety=wt_*_mechanism_mismatch — the WT-LoF constraint does not align with the oncogenic mechanism,
    so an allele-selective agent need not make the WT gene a fitness dependency; e.g. IDH1/ivosidenib).
    Orthogonal to the modality exclusion — this holds at ANY modality, including small_molecule."""
    pkg = _pkg()
    for row in pkg["synthesis"]["recommendation_gate"]["hard_gates"]:
        if row["short"] == "dependency":
            row["status"] = "fired"; row["verdict"] = "non_dependent"; row["live_verdict"] = "non_dependent"
        if row["short"] == "safety":
            row["status"] = "latent"
    pkg["synthesis"]["sub_verdicts"]["safety"] = {"verdict": "wt_human_genetics_mechanism_mismatch"}
    g = hc.gate_ceiling(pkg, modality="small_molecule")
    assert g["ceiling"] != "declined", g
    assert any(t.startswith("dependency:") for t in g["excluded"])
    assert not any(t.startswith("dependency:") for t in g["active_vetoes"])
    # NARROW: pan_essential_killer (no selectivity window) STILL vetoes even when mutant-selective
    for row in pkg["synthesis"]["recommendation_gate"]["hard_gates"]:
        if row["short"] == "dependency":
            row["verdict"] = "pan_essential_killer"; row["live_verdict"] = "pan_essential_killer"
    assert hc.gate_ceiling(pkg, modality="small_molecule")["ceiling"] == "declined"


def test_coherence_non_dependent_benign_for_mutant_selective():
    """(coherence half): a positive-thesis clause may rest on a target whose dependency reads
    non_dependent WITHOUT it counting as an unsurfaced negative — when the target is mutant-selective
    (safety=wt_*_mechanism_mismatch). Same signal/discriminator as the gate. At BOTH grains (dimension
    + dependency-family card)."""
    clauses = {"therapeutic_hypothesis": {"support": ["dependency", "pan-cancer-crispr-dependency-distribution"],
                                          "surfaced": []}}
    card_calls = {"pan-cancer-crispr-dependency-distribution": "non_dependent"}
    # mutant-selective → benign, no violation
    conv_ms = {"safety": "wt_human_genetics_mechanism_mismatch", "dependency": "non_dependent"}
    v_ms = hc.coherence_violations(clauses, conv_ms, [], [], set(), card_calls=card_calls)
    assert not v_ms, f"mutant-selective non_dependent should be benign, got {v_ms}"
    # NOT mutant-selective (plain safety) → the negative_signal_asserted DOES fire (guard intact)
    conv_plain = {"safety": "tolerant_reduced_safety_risk", "dependency": "non_dependent"}
    v_plain = hc.coherence_violations(clauses, conv_plain, [], [], set(), card_calls=card_calls)
    assert v_plain, "non-mutant-selective non_dependent must still count as a contradiction"


def test_ceiling_opposing_caps_below_advanceable():
    pkg = _pkg()
    pkg["synthesis"]["recommendation_gate"]["hard_gates"].append(
        {"short": "selectivity", "verdict": "not_selective", "disposition": "contradiction",
         "status": "opposing", "live_verdict": "not_selective", "policy_source": "vocab"})
    g = hc.gate_ceiling(pkg)
    assert g["ceiling"] == "advanceable_with_caveat"
    assert "selectivity:not_selective" in g["opposing"]


def test_ceiling_safety_hold_caps_at_flagged():
    pkg = _pkg()
    pkg["synthesis"]["sub_verdicts"]["safety"] = {"verdict": "human_genetics_safety_concern"}
    g = hc.gate_ceiling(pkg)
    assert g["ceiling"] == "advanceable_flagged"


def test_ceiling_missing_synthesis_fails_closed():
    g = hc.gate_ceiling({"cards": []})
    assert g["ceiling"] == "declined"
    assert g["fail_closed"] is True


def test_ceiling_no_hard_gates_block_uses_failclosed_fallback():
    """Older package with NO hard_gates: fall back to rec-gate + sub-verdict kill scan — never the
    prototype's fail-open behaviour."""
    pkg = _pkg()
    pkg["synthesis"]["recommendation_gate"].pop("hard_gates")
    pkg["synthesis"]["sub_verdicts"]["dependency"] = {"verdict": "non_dependent"}
    g = hc.gate_ceiling(pkg)
    assert g["hard_gates_present"] is False
    assert g["ceiling"] == "declined"
    assert "dependency:non_dependent" in g["active_vetoes"]


def test_clamp_respects_ceiling():
    assert hc.clamp("advanceable", "declined") == ("declined", True)
    assert hc.clamp("advanceable_flagged", "advanceable") == ("advanceable_flagged", False)
    # unrecognized proposed verdict is never assumed permissive
    assert hc.clamp("banana", "advanceable")[0] == "needs_data"


# =============================== modality controlled enum ===============================
def test_modality_enum_explicit_and_inference():
    assert hc.resolve_modality("small_molecule", None) == ("small_molecule", False)
    assert hc.resolve_modality(None, "small-molecule drug target")[0] == "small_molecule"
    assert hc.resolve_modality(None, "an ADC program")[0] == "adc"
    # unknown objective → agnostic (all in scope), flagged inferred
    m, inferred = hc.resolve_modality(None, "vague")
    assert m == "modality_agnostic" and inferred is True
    with pytest.raises(ValueError):
        hc.resolve_modality("teleporter", None)


def test_modality_scope_excludes_surface_for_small_molecule():
    assert "surface_modality" in hc.out_of_scope_dims("small_molecule")
    assert "tractability_sm" in hc.out_of_scope_dims("adc")
    assert hc.out_of_scope_dims("modality_agnostic") == set()


# =============================== subtype-resolved consumption ===============================
def test_subtype_parse_tokens_and_floor():
    s = hc.parse_subtype_resolved(_pkg())
    assert s["present"] is True
    assert {"MSS", "MSI-H"} <= s["stratum_tokens"]
    by = {r["stratum"]: r for r in s["per_stratum"]}
    assert by["MSS"]["n_floor_met_by_axis"]["dependency"] is True
    assert by["MSI-H"]["n_floor_met_by_axis"]["dependency"] is False


def test_subtype_absent_tolerated():
    pkg = _pkg()
    pkg.pop("subtype_resolved")
    s = hc.parse_subtype_resolved(pkg)
    assert s["present"] is False and s["stratum_tokens"] == set()


# =============================== evidence-substrate discount ===============================
def test_correlated_cards_share_substrate_and_count_once():
    ind = hc.substrate_independence(_pkg())
    assert ind["correlated_evidence_discounted"] is True
    assert "recount3_tcga_gtex_bulk_rna" in ind["correlated_groups"]
    grp = ind["correlated_groups"]["recount3_tcga_gtex_bulk_rna"]
    assert set(grp) == {"tumor-vs-normal-selectivity", "tumor-rna-distribution"}


def test_substrate_discount_lowers_certainty_when_single_substrate():
    """If ALL evidence collapses to one substrate (n_independent < 2), certainty is capped low —
    the correlated pair no longer inflates certainty."""
    pkg = _pkg()
    # keep ONLY the two cards that share recount3 → one independent substrate, zero untagged
    pkg["cards"] = [c for c in pkg["cards"]
                    if c.get("evidence_substrate") == "recount3_tcga_gtex_bulk_rna"]
    ind = hc.substrate_independence(pkg)
    assert ind["n_independent_units"] == 1
    cert = hc.discounted_certainty("moderate", ind["n_independent_units"], [])
    assert cert["final"] == "low" and cert["capped"] is True


# =============================== traceability WITH TEETH ===============================
def _surface():
    panel = hc.assemble(str(PKG), str(RISK), str(DOSSIER), "small_molecule")
    return panel["citation_surface"]


def test_pmid_must_be_exact_member_no_substring_escape():
    surf = _surface()
    assert hc.check_traceability(["34567890"], surf) == []          # retrieved
    bad = hc.check_traceability(["99999999"], surf)                 # confabulated
    assert bad and "99999999" in bad[0]


def test_known_card_and_stratum_tokens_traceable():
    surf = _surface()
    assert hc.check_traceability(["crispr-lof-dependency"], surf) == []
    assert hc.check_traceability(["MSS"], surf) == []
    assert hc.check_traceability(["dependency"], surf) == []        # sub-verdict name
    # a phrase embedding a known card id passes (non-PMID substring escape)
    assert hc.check_traceability(["tumor-vs-normal-selectivity card"], surf) == []
    # an unknown free-text token is untraceable
    assert hc.check_traceability(["made up assertion"], surf)


# =============================== end-to-end run() with a stubbed LLM ===============================
def _stub_clean(system, user, name, schema, **kw):
    """A well-behaved model: cites only real spine tokens; proposes advanceable."""
    if name == "cross_edges":
        return {"edges": [{"type": "corroborates", "from_dimension": "dependency",
                           "to_dimension": "selectivity", "rationale": "both positive",
                           "citations": ["dependency", "selectivity"]}],
                "principal_tensions": [{"statement": "surface not viable",
                                        "citations": ["surface_modality"]}],
                "evidence_paths": [{"claim": "MSS dependent population", "leads_to": "population",
                                    "steps": [{"signal": "dep strong in MSS",
                                               "citation": "MSS"}]}]}
    return {
        "causal_rationale": {"statement": "KRAS drives MAPK", "citations": ["dependency", "34567890"]},
        "therapeutic_hypothesis": {"statement": "inhibit KRAS", "modality": "small_molecule",
                                   "citations": ["dependency", "crispr-lof-dependency"]},
        "population": {"statement": "MSS COADREAD", "indication": "COADREAD",
                       "subtype_or_biomarker": "MSS", "citations": ["MSS", "selectivity"]},
        "therapeutic_window": {"statement": "tolerable", "citations": ["safety"],
                               "contradicting_citations": []},
        "evidence_grade": {"overall": "moderate",
                           "per_line": [{"dimension": "dependency", "strength": "strong"}]},
        "proposed_verdict": "advanceable",
        "proposed_verdict_reason": "strong dependency + selectivity",
        "go_forth": {"next_evidence": "MSI-H cohort dependency", "value_of_information": "high"},
    }


def _stub_teeth(system, user, name, schema, **kw):
    """A misbehaving model: cites a confabulated PMID and a GAP-line sub-verdict as support."""
    if name == "cross_edges":
        return {"edges": [], "principal_tensions": [], "evidence_paths": []}
    return {
        "causal_rationale": {"statement": "driven", "citations": ["differentiation", "88888888"]},
        "therapeutic_hypothesis": {"statement": "inhibit", "modality": "small_molecule",
                                   "citations": ["dependency"]},
        "population": {"statement": "all", "citations": ["dependency"]},
        "therapeutic_window": {"statement": "ok", "citations": ["safety"]},
        "evidence_grade": {"overall": "moderate", "per_line": []},
        "proposed_verdict": "advanceable",
        "proposed_verdict_reason": "x",
        "go_forth": {"next_evidence": "y"},
    }


def test_end_to_end_clean_run_promotable_and_clamped_to_ceiling():
    r = R.run(str(PKG), str(RISK), "small-molecule drug target", "small_molecule",
              str(DOSSIER), synthesize_fn=_stub_clean)
    # clean hard_gates → ceiling advanceable; proposed advanceable → not clamped
    assert r["verdict"]["gate_ceiling"] == "advanceable"
    assert r["verdict"]["computed"] == "advanceable"
    assert r["defensibility"]["promotable"] is True
    assert r["defensibility"]["clause_traceability"] == 1.0
    # subtype consumed + correlated evidence flagged
    assert r["subtype_resolved"]["present"] is True
    assert r["subtype_resolved"]["scoped_subtype"] == "MSI_status"
    assert r["evidence_independence"]["correlated_evidence_discounted"] is True
    # surface_modality is out of scope for small_molecule → not a data gap
    assert "surface_modality" not in r["uncertainty"]["data_gaps"]
    assert "differentiation" in r["uncertainty"]["data_gaps"]   # a real in-scope gap
    # byte/schema sanity: fully JSON-serializable
    json.dumps(r)


def test_end_to_end_teeth_block_promotion_and_cap_verdict():
    r = R.run(str(PKG), str(RISK), "small-molecule drug target", "small_molecule",
              str(DOSSIER), synthesize_fn=_stub_teeth)
    d = r["defensibility"]
    assert d["promotable"] is False
    assert "untraceable_citations" in d["promotion_blockers"]
    assert "absence_discipline_violations" in d["promotion_blockers"]
    # confabulated PMID caught by retrieve-don't-recall
    assert any("88888888" in str(v) for v in d["untraceable_citations"].values())
    # citing the `differentiation` GAP line as support flagged
    assert "causal_rationale" in r["uncertainty"]["absence_discipline_violations"]
    # a non-promotable hypothesis can never present a permissive verdict
    assert hc.VERDICT_RANK[r["verdict"]["computed"]] <= hc.VERDICT_RANK["advanceable_flagged"]


def test_end_to_end_degraded_mode_when_inputs_missing():
    r = R.run(str(PKG), None, "small-molecule drug target", "small_molecule",
              None, synthesize_fn=_stub_clean)
    dm = r["degraded_mode"]
    assert dm["dossier_present"] is False and dm["risk_present"] is False
    assert set(dm["degraded_inputs"]) == {"dossier", "risk"}
    # a missing input must never inflate certainty; the degradation cap is recorded
    assert r["uncertainty"]["overall_certainty"] == "low"
    assert any("degraded inputs" in reason for reason in r["uncertainty"]["cap_reasons"])
    # with risk missing there are no allowed PMIDs → the clean stub's real PMID is now untraceable
    assert r["defensibility"]["promotable"] is False


# ======================= NATIVE GROUNDED-SUBSTRATE WIRING =======================
def _substrate_discordant():
    """A per-subskill grounded substrate (ground_axis output): safety axis whose literature
    CONTRADICTS the deterministic verdict, plus a concordant selectivity axis in the BARE-block shape."""
    return {
        "safety": {"axis": "safety", "deterministic": {"verdict": "tolerant_reduced_safety_risk"},
                   "grounded": {"findings": [{"finding": "class-wide ocular toxicity reported",
                                              "kind": "on-target normal-tissue tox",
                                              "cited_pmids": ["29999999"]}],
                                "corroborations": [], "contradicts_deterministic": True,
                                "anchor_verdict": "tolerant_reduced_safety_risk",
                                "escalate_only": True, "corpus_pin": {"mindate": "2015"}}},
        # BARE grounded block (no {axis, deterministic, grounded} wrapper) — tolerance
        "selectivity": {"findings": [{"finding": "some normal expression", "kind": "normal-tissue",
                                      "cited_pmids": ["28888888"]}],
                        "contradicts_deterministic": False, "anchor_verdict": "selective",
                        "escalate_only": True},
        "junk": "not a dict — must be skipped",
    }


def test_parse_grounded_substrate_shapes_pmids_and_discordance():
    g = hc.parse_grounded_substrate(_substrate_discordant())
    assert g["present"] is True
    assert g["pmids"] == {"29999999", "28888888"}     # collected across BOTH record shapes
    assert g["discordant_axes"] == ["safety"]          # only the contradicting axis
    assert g["n_findings"] == 2
    # absence tolerated
    empty = hc.parse_grounded_substrate(None)
    assert empty["present"] is False and empty["pmids"] == set() and empty["discordant_axes"] == []


def test_assemble_folds_grounded_pmids_into_citation_surface():
    """The design-correct literature path: a grounded PMID becomes CITABLE (traceable) ONLY because the
    substrate was fed in natively — proving literature reaches the hypothesis via grounding, not risk."""
    sub = {"safety": {"grounded": {"findings": [{"finding": "x", "kind": "y",
                                                 "cited_pmids": ["29999999"]}],
                                    "contradicts_deterministic": False, "anchor_verdict": "v"}}}
    surf = hc.assemble(str(PKG), None, None, "small_molecule", substrate=sub)["citation_surface"]
    assert "29999999" in surf["pmids"]
    assert hc.check_traceability(["29999999"], surf) == []          # now citable
    # WITHOUT the substrate the same PMID is confabulation (untraceable)
    surf0 = hc.assemble(str(PKG), None, None, "small_molecule")["citation_surface"]
    assert hc.check_traceability(["29999999"], surf0)


def test_run_surfaces_grounded_discordance_and_is_escalate_only():
    base = R.run(str(PKG), str(RISK), "small-molecule drug target", "small_molecule",
                 str(DOSSIER), synthesize_fn=_stub_clean)
    withsub = R.run(str(PKG), str(RISK), "small-molecule drug target", "small_molecule",
                    str(DOSSIER), synthesize_fn=_stub_clean, substrate=_substrate_discordant())
    gs = withsub["grounded_substrate"]
    assert gs["present"] is True and gs["n_findings"] == 2
    assert gs["discordant_axes"] == ["safety"] and gs["n_grounded_pmids"] == 2
    # the engine↔literature discordance is surfaced as a DETERMINISTIC tension
    ts = withsub["hypothesis"]["tensions"]
    assert any(t.get("source") == "grounded_substrate_discordance" and t.get("axis") == "safety"
               for t in ts)
    assert gs["n_discordance_tensions_surfaced"] == 1
    # ESCALATE-ONLY: grounded literature never moves the deterministic ceiling / verdict / promotability
    assert withsub["verdict"]["gate_ceiling"] == base["verdict"]["gate_ceiling"]
    assert withsub["verdict"]["computed"] == base["verdict"]["computed"]
    assert withsub["defensibility"]["promotable"] == base["defensibility"]["promotable"]
    assert withsub["degraded_mode"]["grounded_substrate_present"] is True
    json.dumps(withsub)   # fully serializable


def test_run_without_substrate_leaves_grounded_absent_and_stable():
    """No --substrate → grounded_substrate absent, no discordance tension, presence flag False. This is
    the drift-CI invariant: the golden cases pass no substrate, so the deterministic spine is unmoved."""
    r = R.run(str(PKG), str(RISK), "small-molecule drug target", "small_molecule",
              str(DOSSIER), synthesize_fn=_stub_clean)
    gs = r["grounded_substrate"]
    assert gs["present"] is False and gs["n_findings"] == 0 and gs["discordant_axes"] == []
    assert not any(t.get("source") == "grounded_substrate_discordance"
                   for t in r["hypothesis"]["tensions"])
    assert r["degraded_mode"]["grounded_substrate_present"] is False


def _stub_clean_with_skeptic(system, user, name, schema, **kw):
    """_stub_clean, plus a benign skeptic that refutes nothing (every clause survives)."""
    if name == "skeptic_refutation":
        return {"clauses": []}   # no valid refutations → all clauses survive → score 1.0
    return _stub_clean(system, user, name, schema, **kw)


def test_adversarial_off_by_default_leaves_quality_slot_null():
    r = R.run(str(PKG), str(RISK), "small-molecule drug target", "small_molecule",
              str(DOSSIER), synthesize_fn=_stub_clean)
    # default: the slot is present but null (no skeptic pass, byte-stable to the pre-flag output)
    assert r["quality"]["adversarial_survival"] is None
    assert "adversarial_gate" not in r["quality"]


def test_adversarial_flag_populates_quality_slot_and_gate():
    r = R.run(str(PKG), str(RISK), "small-molecule drug target", "small_molecule",
              str(DOSSIER), synthesize_fn=_stub_clean_with_skeptic, adversarial=True, n_skeptics=3)
    surv = r["quality"]["adversarial_survival"]
    assert surv is not None and surv["score"] == 1.0
    assert surv["n_surviving"] == surv["n_clauses"] and surv["n_clauses"] > 0
    gate = r["quality"]["adversarial_gate"]
    assert gate["passed"] is True and gate["non_surviving_clauses"] == []
    # INTRINSIC-quality: the deterministic spine is identical to the adversarial-off run
    base = R.run(str(PKG), str(RISK), "small-molecule drug target", "small_molecule",
                 str(DOSSIER), synthesize_fn=_stub_clean)
    assert r["verdict"] == base["verdict"] and r["defensibility"] == base["defensibility"]


# =============================== grounding + schema-correctness guards ===============================
def test_generation_prompts_carry_evidence_only_fence():
    # both generation prompts must append the shared anti-lore directive (this skill names the gene
    # and GENERATES biology — the KRAS-blinding case the directive was written for).
    marker = "EVIDENCE-ONLY GROUNDING"
    assert marker in R.EDGE_SYSTEM
    assert marker in R.HYP_SYSTEM


def test_contradicting_citations_declared_on_every_assertive_clause():
    # the coherence teeth + _all_clause_citations READ contradicting_citations from all four clauses;
    # the schema must DECLARE it on all four (not just therapeutic_window) or the acknowledged-tension
    # escape hatch depends on an undeclared field.
    props = R.HYPOTHESIS_SCHEMA["properties"]
    for clause in ("causal_rationale", "therapeutic_hypothesis", "population", "therapeutic_window"):
        assert "contradicting_citations" in props[clause]["properties"], clause


def test_modality_is_enum_constrained_to_scope():
    modality = R.HYPOTHESIS_SCHEMA["properties"]["therapeutic_hypothesis"]["properties"]["modality"]
    assert modality.get("enum") == sorted(hc.MODALITY_SCOPE)


def test_run_surfaces_llm_field_recovery_provenance():
    r = R.run(str(PKG), str(RISK), "small-molecule drug target", "small_molecule",
              str(DOSSIER), synthesize_fn=_stub_clean)
    rec = r["provenance"]["llm_field_recovery"]
    # clean stubs → no salvage/recovery, but the audit slot is present + shaped for both calls
    assert set(rec.keys()) == {"edges", "hypothesis"}
    assert rec["edges"] == {} and rec["hypothesis"] == {}


def test_skeptic_prompt_is_fenced_and_hash_is_stable():
    import adversarial_survival as AS
    assert "EVIDENCE-ONLY GROUNDING" in AS.SKEPTIC_SYSTEM
    assert AS.skeptic_prompt_hash() == AS.skeptic_prompt_hash()   # deterministic
    assert len(AS.skeptic_prompt_hash()) == 64                    # sha256 hex
