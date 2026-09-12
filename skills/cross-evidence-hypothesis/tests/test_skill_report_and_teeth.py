"""cross-evidence-hypothesis — the UNIFIED_OUTPUT_CONTRACT skill_report + the review pass that gave the
defensibility contract REAL teeth (v0.5.0 → v0.6.0).

Every test here pins a defect the production review found on the five 2026-09-10 finalized packages, so
each one has a REACHABLE FAIL branch (the anti-vacuous-pass discipline):

  * AXIS ROLES (`synthesis.skill_reports`) — the four GATELESS descriptive lenses
    (combination_vulnerability / literature_context / target_intrinsic / translational_readiness) have
    `verdict: None` BY DESIGN and were landing in `data_gaps` on every target; EGFR/NSCLC reported
    `limiting_dimension: target_intrinsic`, which the dashboard convergence layer renders verbatim.
  * RETRIEVE-DON'T-RECALL — `check_traceability` read `n=123456`, `chr7:140453136` and `TPM 1000000` as
    unretrieved PMIDs, and rejected the exact `PMID 12345678` format the prompt asks for. Each false
    positive set `promotable: false` and capped the verdict at `advanceable_flagged`.
  * INDEPENDENCE-BEFORE-CERTAINTY — every untagged card counted as its own independent unit, so real
    packages reported 121-125 units and the `< 2` cap was unreachable. It is now tagged-substrates-only
    with GRADED caps, and it ABSTAINS (rather than capping) when no unit view is authoritative.
  * CERTAINTY DISTRIBUTION — the weakest-link scalar is `low` on all five packages, so it cannot rank
    targets; the per-axis histogram is emitted alongside it.
  * SPINE-DISPOSED SAFETY GATE — the scalar safety cap re-imposed a hold for a hard-gates row the spine
    had marked `suppressed` (observed on KRAS/COADREAD).
  * ABSENCE-DISCIPLINE symmetry — traceability credited a citation for EMBEDDING a known token while
    absence-discipline only caught the bare axis string, so the same phrasing bought a free gap citation.

No Bedrock anywhere: the core functions are pure and the run()-level tests inject a stub synthesize_fn.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from _test_support import load_run_py

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import hypothesis_core as hc  # noqa: E402

R = load_run_py(SCRIPTS.parent, "ce_run_skill_report")

FIX = Path(__file__).resolve().parent / "fixtures"
PKG = FIX / "evidence_package_new_blocks.json"

# the four GATELESS lenses the spine carries as role=descriptive (verdict None, polarity not_scored)
_GATELESS = ("combination_vulnerability", "literature_context", "target_intrinsic", "translational_readiness")


def _pkg():
    return json.loads(PKG.read_text())


def _report(role, call=None):
    return {"call": call, "role": role, "polarity": "not_scored" if role != "gating" else "supportive"}


def _with_skill_reports(pkg):
    """Attach a realistic `synthesis.skill_reports`: every existing sub-verdict short is GATING, plus the
    four gateless descriptive lenses (verdict None) the real packages carry."""
    reports = {short: _report("gating", rec.get("verdict")) for short, rec in pkg["synthesis"]["sub_verdicts"].items()}
    for short in _GATELESS:
        reports[short] = _report("descriptive", None)
        pkg["synthesis"]["sub_verdicts"][short] = {"gate": None, "verdict": None, "fired_rule_ids": []}
    pkg["synthesis"]["skill_reports"] = reports
    return pkg


# =============================== parse_skill_reports (the role reader) =============================


def test_parse_skill_reports_absent_is_byte_stable_fallback():
    """A package predating the spine carry reports present=False and EMPTY role views, so every consumer
    falls back to its previous behaviour — an older package must not change verdict."""
    p = hc.parse_skill_reports(_pkg())
    assert p["present"] is False
    assert p["roles"] == {} and p["gating_axes"] == [] and p["not_scored_axes"] == []


def test_parse_skill_reports_splits_gating_from_gateless():
    p = hc.parse_skill_reports(_with_skill_reports(_pkg()))
    assert p["present"] is True
    assert set(p["not_scored_axes"]) == set(_GATELESS)
    assert "dependency" in p["gating_axes"] and "target_intrinsic" not in p["gating_axes"]


def test_descriptive_axis_that_DOES_carry_a_call_is_not_treated_as_unscored():
    """`role=descriptive` alone is not enough — a descriptive lens that actually produced a call is a real
    read and stays in the coverage picture. Only role ∈ {descriptive, inert} AND no `call` is unscored."""
    pkg = _with_skill_reports(_pkg())
    pkg["synthesis"]["skill_reports"]["literature_context"] = _report("descriptive", "high_risk")
    p = hc.parse_skill_reports(pkg)
    assert "literature_context" not in p["not_scored_axes"]


# =============================== data_gaps / certainty are role-aware ==============================


def test_gateless_lens_is_not_a_data_gap():
    """THE F1 DEFECT: a role=descriptive lens with verdict None is DECLARED absence of scoring, not
    MISSING data. Reachable fail branch — drop the not_scored argument and all four come back."""
    conviction = {"dependency": "selective_dependency", "expression": "insufficient", **{g: None for g in _GATELESS}}
    assert hc.data_gaps(conviction) == sorted(["expression", *_GATELESS])  # the OLD behaviour
    assert hc.data_gaps(conviction, not_scored=_GATELESS) == ["expression"]  # role-aware


def test_limiting_axis_is_restricted_to_gating_axes():
    """EGFR/NSCLC reported `limiting_dimension: target_intrinsic` — a lens that gates nothing — and the
    dashboard rendered it. The HEADLINE value is unchanged; only the attribution is narrowed."""
    conviction = {"dependency": "selective_dependency", "target_intrinsic": None}
    cba = {"dependency": "moderate"}
    worst_all, limiting_all = hc.weakest_link_certainty(conviction, ["dependency", "target_intrinsic"], cba)
    assert limiting_all == "target_intrinsic"  # the defect: a descriptive lens named as limiting
    worst_gated, limiting_gated = hc.weakest_link_certainty(
        conviction, ["dependency", "target_intrinsic"], cba, gating_axes=["dependency"]
    )
    assert limiting_gated == "dependency"
    assert worst_gated == worst_all == "low"  # conjunctive headline UNCHANGED by the restriction


def test_limiting_axis_is_none_when_every_gating_axis_is_high():
    conviction = {"dependency": "selective_dependency", "expression": "tumor_broadly_expressed"}
    worst, limiting = hc.weakest_link_certainty(
        conviction,
        ["dependency", "expression"],
        {"dependency": "high", "expression": "high"},
        gating_axes=["dependency", "expression"],
    )
    assert worst == "high" and limiting is None


def test_binding_axis_is_reported_when_the_limiting_axis_is_not_the_one_that_bound():
    """★ F18, the ERBB2/BRCA case: `low` beside `limiting_dimension: mechanism` when mechanism was
    MODERATE and the axis that actually bound was the non-gating `subtype_fit`.

    Both halves of the asymmetry are deliberate — the headline is the conjunctive minimum over EVERY
    scored axis, the attribution is gating-only (F1) — so the fix is to DISCLOSE the disagreement, not to
    change either number. This pins the exact shape that shipped."""
    in_scope = ["mechanism", "subtype_fit", "selectivity"]
    cba = {"mechanism": "moderate", "subtype_fit": "low", "selectivity": "high"}
    conviction = dict.fromkeys(in_scope, "ok")
    gating = ["mechanism", "selectivity"]  # subtype_fit declares no skill_report at all
    worst, limiting = hc.weakest_link_certainty(conviction, in_scope, cba, gating_axes=gating)
    assert (worst, limiting) == ("low", "mechanism")  # the incoherent pair, reproduced
    b = hc.binding_axis_attribution(conviction, in_scope, cba, gating_axes=gating, roles={"mechanism": "gating"})
    assert b["limiting_dimension_is_binding"] is False  # ← the disclosure
    assert b["binding_axis"] == "subtype_fit"
    assert b["binding_axis_level"] == "low" == worst  # it agrees with the HEADLINE, not with `limiting`
    assert b["binding_axis_is_gating"] is False
    assert b["binding_axis_role"] is None  # absent from skill_reports = role UNKNOWN, not "descriptive"
    assert b["n_binding_axes"] == 1  # a LONE non-gating axis at the minimum is the misleading case


def test_binding_axis_agrees_when_a_gating_axis_ties_at_the_minimum():
    """The masking case, and why 1-of-20 on the panel was luck rather than safety: as soon as ANY gating
    axis is also at the minimum, `limiting_dimension` lands on the right level and the disagreement is
    invisible — even though a non-gating axis is still sitting there."""
    in_scope = ["mechanism", "subtype_fit", "selectivity"]
    cba = {"mechanism": "low", "subtype_fit": "low", "selectivity": "high"}
    conviction = dict.fromkeys(in_scope, "ok")
    b = hc.binding_axis_attribution(
        conviction, in_scope, cba, gating_axes=["mechanism", "selectivity"], roles={"mechanism": "gating"}
    )
    assert b["limiting_dimension_is_binding"] is True
    assert b["n_binding_axes"] == 2  # the tie is what hides it
    assert b["binding_axis_level"] == "low"


def test_f18_attribution_moves_no_certainty_value():
    """Disclosure only: the attribution must not shift the headline, the limiting name, or the histogram
    for ANY role configuration. Compares roles-known against roles-absent on identical levels."""
    in_scope = ["mechanism", "subtype_fit"]
    cba = {"mechanism": "moderate", "subtype_fit": "low"}
    conviction = dict.fromkeys(in_scope, "ok")
    for gating in (None, ["mechanism"], in_scope):
        before = hc.weakest_link_certainty(conviction, in_scope, cba, gating_axes=gating)
        dist_before = hc.certainty_distribution(conviction, in_scope, cba, gating_axes=gating)
        hc.binding_axis_attribution(conviction, in_scope, cba, gating_axes=gating, roles={"mechanism": "gating"})
        assert hc.weakest_link_certainty(conviction, in_scope, cba, gating_axes=gating) == before
        assert hc.certainty_distribution(conviction, in_scope, cba, gating_axes=gating) == dist_before
        assert before[0] == "low"  # the headline is `low` in all three role configurations


def test_certainty_distribution_discriminates_where_the_scalar_cannot():
    """Two targets with the SAME weakest-link scalar and DIFFERENT shapes. The scalar is `low` for both
    (it is a conjunctive minimum — that is why it was constant across all five packages); the histogram
    separates them, and the gating-only slice separates them further."""
    in_scope = ["dependency", "expression", "selectivity"]
    strong = {"dependency": "high", "expression": "high", "selectivity": "low"}
    weak = {"dependency": "low", "expression": "low", "selectivity": "low"}
    conviction = dict.fromkeys(in_scope, "ok")
    assert hc.weakest_link_certainty(conviction, in_scope, strong)[0] == "low"
    assert hc.weakest_link_certainty(conviction, in_scope, weak)[0] == "low"  # SAME scalar
    d_strong = hc.certainty_distribution(conviction, in_scope, strong, gating_axes=in_scope)
    d_weak = hc.certainty_distribution(conviction, in_scope, weak, gating_axes=in_scope)
    assert d_strong["n_axes_by_level"] == {"low": 1, "moderate": 0, "high": 2}
    assert d_weak["n_axes_by_level"] == {"low": 3, "moderate": 0, "high": 0}
    assert d_strong["n_gating_axes_by_level"] != d_weak["n_gating_axes_by_level"]


def test_unknown_roles_report_the_gating_slice_as_unknown_not_empty():
    """A pre-#1310 package says NOTHING about roles. Emitting a zeroed gating histogram would assert
    "every axis of this target is decorative" — a claim the package does not make, and one a reviewer
    would act on. `None` is the honest value; `[]` (roles known, none gating) stays a real zero."""
    conviction = {"dependency": "selective_dependency"}
    unknown = hc.certainty_distribution(conviction, ["dependency"], {"dependency": "high"})
    assert unknown["gating_roles_known"] is False
    assert unknown["n_gating_axes_by_level"] is None and unknown["gating_by_axis"] is None
    known_empty = hc.certainty_distribution(conviction, ["dependency"], {"dependency": "high"}, gating_axes=[])
    assert known_empty["gating_roles_known"] is True
    assert known_empty["n_gating_axes_by_level"] == {"low": 0, "moderate": 0, "high": 0}


def test_certainty_distribution_separates_spine_sidecar_from_proxy():
    """A level the spine's CERTAINTY_MODEL sidecar supplied is authoritative; the rest is the binary
    gap/non-gap proxy. A reader must be able to tell them apart."""
    d = hc.certainty_distribution(
        {"dependency": "selective_dependency", "expression": "insufficient"},
        ["dependency", "expression"],
        {"dependency": "high"},
    )
    assert d["axes_from_spine_sidecar"] == ["dependency"] and d["axes_from_proxy"] == ["expression"]


# =============================== independence-before-certainty (made reachable) ====================


def _pkg_with_cards(specs):
    """specs = list of (card_id, evidence_substrate|None) or (card_id, substrate|None, measurement_type|None).

    The 3-tuple form is what F17 needs: an untagged card that DOES carry a measurement_type is a
    vocabulary gap, one that carries none is registry back-ref debt, and the two have different owners.
    """
    pkg = _pkg()
    cards = []
    for spec in specs:
        cid, sub = spec[0], spec[1]
        mt = spec[2] if len(spec) > 2 else None
        cards.append(
            {"card_id": cid, **({"evidence_substrate": sub} if sub else {}), **({"measurement_type": mt} if mt else {})}
        )
    pkg["cards"] = cards
    return pkg


def test_untagged_cards_do_not_count_as_independent_units():
    """THE F3 DEFECT: untagged cards used to each count as an independent unit, which is why real
    packages reported 121-125 units and the cap could never fire. An untagged card is MISSING PROVENANCE,
    not proven independence."""
    s = hc.substrate_independence(_pkg_with_cards([("a", "recount3"), ("b", "recount3"), ("c", None), ("d", None)]))
    assert s["n_independent_units"] == 1  # ONE substrate, not 1 + 2 untagged
    assert s["n_untagged_cards"] == 2 and s["n_tagged_cards"] == 2
    assert s["substrate_tagged_fraction"] == 0.5
    assert s["correlated_evidence_discounted"] is True


def test_tagging_sparse_is_declared_when_the_view_sees_a_minority():
    sparse = hc.substrate_independence(_pkg_with_cards([("a", "recount3")] + [(f"c{i}", None) for i in range(9)]))
    assert sparse["tagging_sparse"] is True and sparse["substrate_tagged_fraction"] == 0.1
    dense = hc.substrate_independence(_pkg_with_cards([("a", "recount3"), ("b", "depmap"), ("c", None)]))
    assert dense["tagging_sparse"] is False


def test_sparsity_is_attributed_to_the_vocabulary_or_to_missing_backrefs():
    """THE F17 DEFECT: `tagging_sparse` fired on 15/15 panel targets, so it could not inform a decision.

    The cause is structural, not per-target: `evidence_substrate` is declared on MEASUREMENT_TYPES, and the
    `evidence_substrates` vocab has two entries reaching ~16% of cards, so the 0.5 floor is unreachable by
    construction. The fix is not to move the floor but to say WHOSE gap it is, because the two remedies live
    in different repos. Both branches below are reachable — that is the point.
    """
    # (1) VOCABULARY-limited: every untagged card was stamped with a type; that type names no substrate.
    vocab = hc.substrate_independence(
        _pkg_with_cards([("a", "recount3", "expr")] + [(f"c{i}", None, f"t{i}") for i in range(9)])
    )
    assert vocab["tagging_sparse"] is True
    assert vocab["substrate_vocabulary_limited"] is True, "emitter did its job; the vocab names nothing"
    assert vocab["n_untagged_vocabulary_gap"] == 9 and vocab["n_untagged_no_measurement_type"] == 0

    # (2) BACK-REF debt: the untagged cards are un-migrated, so this IS a per-card registry gap.
    backref = hc.substrate_independence(
        _pkg_with_cards([("a", "recount3", "expr")] + [(f"c{i}", None) for i in range(9)])
    )
    assert backref["tagging_sparse"] is True
    assert backref["substrate_vocabulary_limited"] is False, "un-migrated cards are not a vocabulary excuse"
    assert backref["n_untagged_vocabulary_gap"] == 0 and backref["n_untagged_no_measurement_type"] == 9

    # (3) not sparse at all → nothing to attribute.
    dense = hc.substrate_independence(_pkg_with_cards([("a", "recount3", "e"), ("b", "depmap", "d"), ("c", None, "t")]))
    assert dense["tagging_sparse"] is False and dense["substrate_vocabulary_limited"] is False

    # the decomposition is EXHAUSTIVE — an untagged card is one of exactly these two, never neither.
    for s in (vocab, backref, dense):
        assert s["n_untagged_vocabulary_gap"] + s["n_untagged_no_measurement_type"] == s["n_untagged_cards"]


def test_f17_disclosure_does_not_move_any_verdict_or_unit_count():
    """F17 is DISCLOSURE. If it moved a count or a cap it would silently re-rank every target, so pin that:
    the same package must produce identical units/fraction/sparsity with and without measurement_type stamps.
    """
    without_mt = hc.substrate_independence(
        _pkg_with_cards([("a", "recount3"), ("b", "recount3")] + [(f"c{i}", None) for i in range(8)])
    )
    with_mt = hc.substrate_independence(
        _pkg_with_cards(
            [("a", "recount3", "e"), ("b", "recount3", "e2")] + [(f"c{i}", None, f"t{i}") for i in range(8)]
        )
    )
    for f in (
        "n_independent_units",
        "n_distinct_substrates",
        "n_tagged_cards",
        "n_untagged_cards",
        "substrate_tagged_fraction",
        "tagging_sparse",
        "correlated_evidence_discounted",
    ):
        assert without_mt[f] == with_mt[f], f"F17 changed {f} — it must be verdict-inert"
    # ...and only the attribution differs
    assert without_mt["substrate_vocabulary_limited"] is False
    assert with_mt["substrate_vocabulary_limited"] is True


def test_independence_cap_is_graded_and_reachable():
    """One unit → low; two → moderate; three+ → uncapped. The old single `< 2` rung is why the control
    was inert on every real package."""
    assert hc.discounted_certainty("high", 1, [])["final"] == "low"
    assert hc.discounted_certainty("high", 2, [])["final"] == "moderate"
    assert hc.discounted_certainty("high", 5, [])["final"] == "high"


def test_sparse_tagging_abstains_from_the_unit_cap_but_caps_at_moderate():
    """A metadata gap must not masquerade as measured non-independence: capping `low` on an untagged
    package would swap the old vacuous pass for an equally undiscriminating universal `low`, and would
    blame the target for a pipeline gap. So the substrate view ABSTAINS from the unit cap and only the
    declared-blindness `moderate` cap applies."""
    c = hc.discounted_certainty("high", 0, [], tagging_sparse=True)
    assert c["final"] == "moderate"
    assert c["independence_view_authoritative"] is False
    assert c["independence_cap_binding"] is False
    assert any("tagging sparse" in reason for reason in c["cap_reasons"])
    assert not any("independent evidence" in reason for reason in c["cap_reasons"])


def test_spine_gate_view_still_caps_when_substrate_tagging_is_sparse():
    """The spine's decision-gate-group view is derived from FIRED CARDS, so it is populated on real
    packages — it is the rung that actually bites when substrate tagging is absent."""
    c = hc.discounted_certainty("high", 0, [], n_independent_gate_groups=1, tagging_sparse=True)
    assert c["final"] == "low" and c["independence_view_authoritative"] is True
    assert c["independence_cap_binding"] is True
    assert c["independence_unit_kind"] == "decision-gate-group"


def test_an_authoritative_view_that_caps_nothing_is_not_reported_as_a_cap():
    """THE F14 DEFECT, caught on the live KRAS-COADREAD run: one flag answered two questions. A view
    that SPOKE and found >= 3 units caps nothing, but the old `independence_cap_applied: true` said a
    cap had been applied and a reviewer would go looking for it. `_view_authoritative` (could the read
    speak) and `_cap_binding` (did it lower anything) are now separate, and the FAIL branch is real:
    collapsing them back makes one of these two asserts false."""
    spoke_and_capped_nothing = hc.discounted_certainty("high", 0, [], n_independent_gate_groups=3, tagging_sparse=True)
    assert spoke_and_capped_nothing["independence_view_authoritative"] is True
    assert spoke_and_capped_nothing["independence_cap_binding"] is False
    # the unit cap permitted `high`; the separately-declared tagging-blindness cap is what holds it down
    assert spoke_and_capped_nothing["cap_ceiling"] == "moderate"
    assert not any("independent evidence" in r for r in spoke_and_capped_nothing["cap_reasons"])


def test_cap_ceiling_explains_a_non_binding_cap_list():
    """`cap_reasons` lists caps CONSIDERED. On a `low` base they bind nothing and `capped` is False —
    which used to read as a contradiction. `cap_ceiling` names the level the caps permit, so
    base/cap_ceiling/final/capped are one coherent statement."""
    c = hc.discounted_certainty("low", 0, [], n_independent_gate_groups=2, tagging_sparse=True)
    assert c["base"] == "low" and c["final"] == "low"
    assert c["capped"] is False, "a low base cannot be lowered further"
    assert c["cap_reasons"], "caps were still considered"
    assert c["cap_ceiling"] == "moderate", "and they permitted moderate — the base is what bound"


# =============================== retrieve-don't-recall (F2) ========================================

_SURFACE = {
    "card_ids": {"copy-number-distribution"},
    "sub_verdicts": {"dependency", "expression"},
    "rule_ids": {"dep_strongly_selective_v1"},
    "dossier_fields": set(),
    "strata": set(),
    "pmids": {"12345678"},
}


def test_correctly_formatted_retrieved_pmid_passes():
    """THE F2 DEFECT: the residual left after removing the digits was the bare word "PMID", which
    resolved to nothing → untraceable → promotable False → verdict capped. This is the EXACT citation
    format the prompt asks the agent to produce."""
    for cite in ("PMID 12345678", "PMID: 12345678", "pmid:12345678", "PubMed 12345678", "12345678"):
        assert hc.check_traceability([cite], _SURFACE) == [], cite


def test_self_invented_pmid_is_still_flagged():
    """The teeth must still bite: retrieve-don't-recall has no substring escape."""
    assert hc.check_traceability(["PMID 99999999"], _SURFACE) == ["PMID 99999999 (unretrieved PMID 99999999)"]
    # ...and an explicit cue is checked even where the digits sit in numeric context
    assert hc.check_traceability(["PMID=99999999"], _SURFACE) != []


def test_numeric_context_is_not_read_as_a_pmid():
    """Cohort sizes, genomic coordinates, TPM values and p-values are numbers the prompt explicitly asks
    the agent to quote. Each used to become an "unretrieved PMID" and cap the verdict."""
    for cite in (
        "dependency (n=123456)",
        "expression at chr7:140453136",
        "expression TPM 1000000",
        "dependency p=0.000123456",
        "dependency ENSG00000123456",
        "dependency 1.234567e-8",
    ):
        assert hc.check_traceability([cite], _SURFACE) == [], cite


def test_unresolvable_tail_is_not_masked_by_a_retrieved_pmid():
    """A retrieved PMID must not launder an otherwise unresolvable citation — the residual is checked."""
    assert hc.check_traceability(["PMID 12345678 shows myc amplification"], _SURFACE) != []


def test_uncued_digits_in_prose_are_still_rejected_just_not_as_a_pmid():
    """Confining the uncued digit scan to bare identifier lists costs NO teeth: the digits stay in the
    residual, and the residual must itself resolve. A confabulated author-year citation is still bad."""
    assert hc.pmid_claims("Smith et al. 34567890 shows myc amplification") == []
    assert hc.check_traceability(["Smith et al. 34567890 shows myc amplification"], _SURFACE) != []


def test_bare_pmid_list_is_read_as_pmid_claims():
    assert hc.pmid_claims("PMIDs 12345678, 34567890") == ["12345678", "34567890"]
    assert hc.check_traceability(["PMIDs 12345678, 34567890"], _SURFACE) == [
        "PMIDs 12345678, 34567890 (unretrieved PMID 34567890)"
    ]


def test_pmid_claims_is_the_single_definition():
    assert hc.pmid_claims("PMID 12345678 and n=98765432") == ["12345678"]
    assert hc.pmid_claims("PMID: 98765432 and n=98765432") == ["98765432"]  # cue wins over numeric context


# =============================== spine-DISPOSED safety hard gate (F6) =============================


def _with_safety_gate(pkg, status):
    pkg["synthesis"]["sub_verdicts"]["safety"]["verdict"] = "human_genetics_safety_concern"  # in SAFETY_HOLD
    pkg["synthesis"].setdefault("recommendation_gate", {})["hard_gates"] = [
        {"short": "safety", "verdict": "human_genetics_safety_concern", "disposition": "gated", "status": status}
    ]
    return pkg


def test_spine_suppressed_safety_row_is_not_re_imposed():
    """THE F6 DEFECT: the spine EVALUATED its safety gate and released it (`status: suppressed`), and the
    integrator re-derived the hold from the coarse scalar token — overriding the spine's per-run
    adjudication, which is the one thing this integrator must never do."""
    g = hc.gate_ceiling(_with_safety_gate(_pkg(), "suppressed"))
    assert g["safety_gate_disposed_by_spine"] is True
    assert g["ceiling"] == "advanceable"


def test_fired_safety_row_still_holds():
    g = hc.gate_ceiling(_with_safety_gate(_pkg(), "fired"))
    assert g["safety_gate_disposed_by_spine"] is False
    assert g["ceiling"] == "advanceable_flagged"


def test_absent_hard_gates_keeps_the_scalar_safety_cap_fail_closed():
    pkg = _pkg()
    pkg["synthesis"]["sub_verdicts"]["safety"]["verdict"] = "human_genetics_safety_concern"
    pkg["synthesis"]["recommendation_gate"] = {}
    g = hc.gate_ceiling(pkg)
    assert g["safety_gate_disposed_by_spine"] is False and g["ceiling"] == "advanceable_flagged"


# =============================== stratum AXIS tokens are citable (F9) =============================


def test_per_stratum_axis_names_are_citable():
    """The comment claimed the axis names joined the citation surface and the code never added them, so a
    clause citing a stratum axis was scored untraceable on a claim the package supports."""
    pkg = _pkg()
    pkg["subtype_resolved"] = {
        "requested_strata": ["MSS"],
        "available_strata": ["MSS", "MSI-H"],
        "per_stratum": [{"stratum": "MSS", "axes": {"dependency": {"subgroup_n_floor_met": True}}}],
    }
    st = hc.parse_subtype_resolved(pkg)
    assert "dependency" in st["stratum_tokens"] and "MSS" in st["stratum_tokens"]


# =============================== run()-level: skill_report + wiring ================================


def _stub(system, user, name, schema, **kw):
    if name == "cross_edges":
        return {"edges": [], "principal_tensions": [], "evidence_paths": []}
    return {
        "causal_rationale": {"statement": "x", "citations": ["dependency"]},
        "therapeutic_hypothesis": {"statement": "x", "modality": "small_molecule", "citations": ["dependency"]},
        "population": {"statement": "x", "citations": ["dependency"]},
        "therapeutic_window": {"statement": "x", "citations": ["safety"]},
        "evidence_grade": {"overall": "moderate", "per_line": []},
        "proposed_verdict": "advanceable",
        "proposed_verdict_reason": "x",
        "go_forth": {"next_evidence": "y"},
    }


def _run(tmp_path, pkg, **kw):
    p = tmp_path / "ep.json"
    p.write_text(json.dumps(pkg))
    return R.run(str(p), None, "small-molecule drug target", "small_molecule", None, synthesize_fn=_stub, **kw)


def _stub_untraceable(system, user, name, schema, **kw):
    """Same as `_stub` but one clause cites a PMID that is in no retrieved surface — so the PROMOTION cap
    fires while the gate has nothing to object to."""
    out = _stub(system, user, name, schema, **kw)
    if name != "cross_edges":
        out["population"] = {"statement": "x", "citations": ["PMID: 99999999"]}
    return out


def _run_with(tmp_path, pkg, fn):
    p = tmp_path / "ep.json"
    p.write_text(json.dumps(pkg))
    return R.run(str(p), None, "small-molecule drug target", "small_molecule", None, synthesize_fn=fn)


# ============ F16: the dossier arrives in TWO shapes, and presence must be EARNED =================


def _composed_dossier():
    """The shape a target-profile run writes: `subskills/target_intrinsic/package.json`. No `headline`."""
    return {
        "sub_skill": "target_intrinsic",
        "verdict": None,
        "claim_vector": {
            "MODALITY_ROUTING": {"signal": "moderate", "evidence": "inhibitor_sufficient"},
            "TRACTABILITY_PRECEDENT": {"signal": "strong", "evidence": "Tclin"},
            "_disclaimer": "not a gate",
        },
        "key_signals": {"headline": "Target-intrinsic context present.", "supports": ["TRACTABILITY: strong"]},
        "cards": [{"card_id": "target-development-level"}],
    }


def _assemble_with_dossier(tmp_path, doc):
    ep, dp = tmp_path / "ep.json", tmp_path / "dossier.json"
    ep.write_text(PKG.read_text())
    dp.write_text(json.dumps(doc))
    return hc.assemble(str(ep), None, str(dp), "small_molecule", substrate=None)


def test_composed_target_intrinsic_package_is_read_as_a_dossier(tmp_path):
    """THE F16 DEFECT: the reader accepted only a standalone `decision.json` (`headline`), but a
    target-profile run composes target_intrinsic INTO the profile and writes the shape below. So EVERY
    default-on chain run reported `degraded inputs: ['dossier']` and capped certainty `low` — a
    panel-wide constant that cannot rank targets, the same undiscriminating-by-construction failure the
    independence cap had. FAIL branch: drop the `sub_skill` branch and `dossier_present` goes False."""
    panel = _assemble_with_dossier(tmp_path, _composed_dossier())
    assert panel["dossier_present"] is True
    assert {"MODALITY_ROUTING", "TRACTABILITY_PRECEDENT"} <= set(panel["dossier"])
    assert "_disclaimer" not in panel["dossier"], "the disclaimer is not a citable biology field"
    assert "key_signals.headline" in panel["dossier"]
    # and its fields join the citation surface, so a clause may cite them
    assert "MODALITY_ROUTING" in panel["citation_surface"]["dossier_fields"]


def test_standalone_decision_dossier_still_reads(tmp_path):
    panel = _assemble_with_dossier(tmp_path, {"headline": {"target_class": "GTPase"}, "cards": []})
    assert panel["dossier_present"] is True and panel["dossier"]["target_class"] == "GTPase"


def test_an_empty_dossier_does_not_claim_presence(tmp_path):
    """Presence is EARNED, not asserted by the file existing: a dossier that parses to nothing would
    LIFT the degradation cap while contributing no citable field — fail-open."""
    for doc in ({"headline": {}, "cards": []}, {"sub_skill": "target_intrinsic", "claim_vector": {}}, {}):
        assert _assemble_with_dossier(tmp_path, doc)["dossier_present"] is False


def test_a_read_dossier_lifts_the_degradation_cap(tmp_path):
    """The consequence that matters: with the dossier read, certainty is no longer pinned `low` by a
    missing-input cap, so the scalar can DISCRIMINATE across a panel."""
    ep, dp = tmp_path / "ep.json", tmp_path / "dossier.json"
    ep.write_text(PKG.read_text())
    dp.write_text(json.dumps(_composed_dossier()))
    r = R.run(str(ep), None, "small-molecule drug target", "small_molecule", str(dp), synthesize_fn=_stub)
    assert not any("dossier" in reason for reason in r["uncertainty"]["cap_reasons"])
    without = _run(tmp_path, _pkg())
    assert any("dossier" in reason for reason in without["uncertainty"]["cap_reasons"])


# ================== F12: the gate clamp and the promotion cap are DIFFERENT mechanisms ==============


def test_promotion_cap_is_not_reported_as_a_gate_clamp(tmp_path):
    """THE F12 DEFECT, caught on the live KRAS-COADREAD run: the promotion cap reused the gate's
    `was_clamped` flag, so the artifact emitted `was_clamped: true` beside a `gate_ceiling` EQUAL to
    `proposed_by_agent` and `gate_clamp_tension: null` — three fields contradicting each other, reading
    as "the deterministic gate overruled the model" when the model had agreed with the gate exactly and
    was demoted for citation hygiene.

    The FAIL branch is real: reverting the split makes `was_clamped` true here."""
    r = _run_with(tmp_path, _pkg(), _stub_untraceable)
    v = r["verdict"]
    assert r["defensibility"]["promotable"] is False, "the untraceable citation must block promotion"
    assert v["computed"] == "advanceable_flagged", "the promotion cap lowered it"
    assert v["promotion_capped"] is True
    # the gate itself did NOT clamp: the proposal sat at or below the ceiling
    assert v["was_clamped"] is False
    assert v["verdict_after_gate"] == v["proposed_by_agent"]
    assert v["gate_clamp_tension"] is None


def test_a_promotion_cap_does_not_move_the_gate_agreement_atom(tmp_path):
    """ONE defect must not fire TWO of the four claim atoms. The untraceable citation is
    `clause_traceability`'s to report; letting it also flip `gate_agreement` to `opposing`
    double-counted it for any rollup that averages the vector."""
    chips = {c["key"]: c for c in _run_with(tmp_path, _pkg(), _stub_untraceable)["skill_report"]["claim_chips"]}
    assert chips["clause_traceability"]["signal"] == "opposing", "the real defect is reported once"
    assert chips["gate_agreement"]["signal"] == "supportive", "and not a second time as gate disagreement"
    # the atom still DISCLOSES the promotion cap in its evidence, attributed to the right mechanism
    assert "promotion-capped" in chips["gate_agreement"]["evidence"]
    assert "not the gate" in chips["gate_agreement"]["evidence"]


def test_a_real_gate_clamp_still_opposes(tmp_path):
    """The teeth are intact: when the SPINE's ceiling is what lowers the verdict, `was_clamped` is true,
    the tension is surfaced, and the atom opposes."""
    r = _run_with(tmp_path, _with_safety_gate(_pkg(), "fired"), _stub)
    v = r["verdict"]
    assert v["was_clamped"] is True and v["promotion_capped"] is False
    assert v["verdict_after_gate"] == v["computed"] == "advanceable_flagged"
    assert v["gate_clamp_tension"] and "deterministic gate caps" in v["gate_clamp_tension"]
    chips = {c["key"]: c for c in r["skill_report"]["claim_chips"]}
    assert chips["gate_agreement"]["signal"] == "opposing"
    assert "promotion-capped" not in chips["gate_agreement"]["evidence"]


def test_run_emits_a_top_level_skill_report(tmp_path):
    """F11: without this the framework's TERMINAL synthesis was the one artifact the shared
    report/rollup layer could not read, because every reader keys off `skill_report`."""
    r = _run(tmp_path, _pkg())
    sr = r["skill_report"]
    assert sr["role"] == "descriptive", "the integrator sits ABOVE the nomination — it must not gate it"
    assert sr["polarity"] == "not_scored"
    assert sr["call"] == r["verdict"]["computed"], "the report's call is the FINAL clamped verdict"
    assert {c["key"] for c in sr["claim_chips"]} == {
        "gate_agreement",
        "clause_traceability",
        "intra_package_coherence",
        "evidence_independence",
    }
    assert sr["provenance"]["cards_used"] == [] and sr["provenance"]["fired_rule_ids"] == []
    assert sr["_contract"] == "docs/UNIFIED_OUTPUT_CONTRACT.md"


def test_skill_report_call_reflects_the_promotion_cap(tmp_path):
    """`call` is built AFTER the promotion cap, so a non-promotable hypothesis cannot present a
    permissive call on the unified spine."""
    pkg = _pkg()
    r = _run(tmp_path, pkg)
    if not r["defensibility"]["promotable"]:
        assert hc.VERDICT_RANK[r["skill_report"]["call"]] <= hc.VERDICT_RANK["advanceable_flagged"]


def test_run_role_aware_gaps_and_counts(tmp_path):
    """End-to-end F1: the four gateless lenses leave data_gaps, are disclosed as not_scored_axes, and stop
    depressing the supporting-line count."""
    without = _run(tmp_path, _pkg())
    with_roles = _run(tmp_path, _with_skill_reports(_pkg()))
    assert with_roles["uncertainty"]["axis_roles_present"] is True
    assert set(with_roles["uncertainty"]["not_scored_axes"]) == set(_GATELESS)
    assert not (set(_GATELESS) & set(with_roles["uncertainty"]["data_gaps"]))
    # the gateless lenses were ADDED to the package as verdict-None axes; without roles they would each
    # be a gap and would NOT count as supporting lines
    assert (
        with_roles["degraded_mode"]["n_supporting_in_scope_lines"]
        == (without["degraded_mode"]["n_supporting_in_scope_lines"])
    )
    assert with_roles["degraded_mode"]["n_not_scored_in_scope_lines"] == len(_GATELESS)
    assert with_roles["uncertainty"]["limiting_dimension_scope"] == "gating_axes"


def test_limiting_scope_falls_back_when_the_package_carries_no_roles(tmp_path):
    """The OTHER branch of limiting_dimension_scope. `all_scored_in_scope_axes` appeared nowhere in the
    suite or the fixtures, and the 2026-09-12 panel takes the `gating_axes` branch on every target — so
    the fallback was live production code (every package predating #1310 has no `synthesis.skill_reports`)
    with nothing asserting it. Untested is not the same as unreachable.

    The pair of claims that must stay coupled: roles UNKNOWN is not the claim "nothing gates", so the
    scope widens to all scored in-scope axes AND the gating histogram is emitted as None rather than as
    an all-zero histogram a reviewer would read as "every axis here is decorative"."""
    u = _run(tmp_path, _pkg())["uncertainty"]
    assert u["axis_roles_present"] is False
    assert u["limiting_dimension_scope"] == "all_scored_in_scope_axes"
    assert u["n_gating_axes_by_level"] is None and u["gating_certainty_by_axis"] is None
    # the fallback pool is non-empty, so the field is attributed rather than silently dropped
    assert u["limiting_dimension"] in u["certainty_by_axis"]


def test_run_emits_the_certainty_distribution(tmp_path):
    r = _run(tmp_path, _pkg())
    u = r["uncertainty"]
    assert set(u["n_axes_by_level"]) == {"low", "moderate", "high"}
    assert sum(u["n_axes_by_level"].values()) == len(u["certainty_by_axis"])
    assert u["certainty_by_axis"], "the per-axis distribution must not be empty"


def test_run_absence_discipline_catches_a_phrased_gap_citation(tmp_path):
    """F7 symmetry: traceability credits a citation for EMBEDDING a known token, so absence-discipline
    must too — otherwise the same phrasing buys a free citation of a gap line."""
    pkg = _pkg()
    pkg["synthesis"]["sub_verdicts"]["dependency"]["verdict"] = "insufficient"  # make dependency a GAP

    def _phrased(system, user, name, schema, **kw):
        out = _stub(system, user, name, schema, **kw)
        if name != "cross_edges":
            out["causal_rationale"] = {"statement": "x", "citations": ["the dependency sub-verdict"]}
        return out

    p = tmp_path / "ep.json"
    p.write_text(json.dumps(pkg))
    r = R.run(str(p), None, "small-molecule drug target", "small_molecule", None, synthesize_fn=_phrased)
    assert "dependency" in r["uncertainty"]["data_gaps"]
    assert "causal_rationale" in r["uncertainty"]["absence_discipline_violations"]
    assert "absence_discipline_violations" in r["defensibility"]["promotion_blockers"]


def test_run_absence_discipline_does_not_fire_on_a_similarly_named_card(tmp_path):
    """...but the axis name must stand as its own token: the CARD `expression-and-specificity` is not the
    AXIS `expression`, so it is not a gap citation."""
    pkg = _pkg()
    pkg["synthesis"]["sub_verdicts"]["expression"]["verdict"] = "insufficient"

    def _card_cite(system, user, name, schema, **kw):
        out = _stub(system, user, name, schema, **kw)
        if name != "cross_edges":
            out["causal_rationale"] = {"statement": "x", "citations": ["expression-and-specificity"]}
        return out

    p = tmp_path / "ep.json"
    p.write_text(json.dumps(pkg))
    r = R.run(str(p), None, "small-molecule drug target", "small_molecule", None, synthesize_fn=_card_cite)
    assert "expression" in r["uncertainty"]["data_gaps"]
    assert "causal_rationale" not in r["uncertainty"]["absence_discipline_violations"]


def test_run_discloses_substrate_tagging_coverage(tmp_path):
    r = _run(tmp_path, _pkg())
    ei = r["evidence_independence"]
    assert {
        "n_tagged_cards",
        "substrate_tagged_fraction",
        "tagging_sparse",
        "independence_view_authoritative",
        "independence_cap_binding",
    } <= set(ei)
    # THE F13 DEFECT: every unit count in the block must say WHICH VIEW it is. `n_independent_units`
    # was the substrate count sitting beside `effective_independent_units` (the binding view) under a
    # name that claimed to be authoritative; on live KRAS they read 2 and 3 with no way to tell why.
    assert "n_independent_units" not in ei, "an unqualified unit count is ambiguous between the two views"
    assert ei["n_independent_substrate_units"] == ei["n_distinct_substrates"], "untagged must not inflate"
