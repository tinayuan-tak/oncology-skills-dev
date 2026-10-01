#!/usr/bin/env python3
"""Teeth for eval/loop/critic/containment.py — the containment guard (SK#2303 WI-D, #2356).

Containment is the fail-closed guard between the propose-only judge (#2355) and tier routing: it
re-verifies each finding against the RAW L2b island (never a re-normalised copy) AND against the cited
field's CONTRACT. These teeth gate the two load-bearing properties the pilot established (plan §5A.9/§5A.11):

  - the ACCEPTANCE contrast: on the pilot finding set, the true findings PASS and the two known
    false-premise findings are REJECTED — (1) CD274 ``corroboration:high`` "overstated" (correct by
    contract: corroboration is independence-agreement, not strength) is DROPPED; (2) ERBB2 "empty arms"
    is DEMOTED to a substrate-shape note (dict-vs-list ``source_support`` artifact);
  - the MUTATION TOOTH: a finding citing a field whose contract contradicts the claim FAILS containment
    only BECAUSE of the contract check — neuter the contract check and it wrongly passes (this test reds);
  - ref re-resolution against the RAW island through the shape-aware ``iter_source_support`` primitive
    (``.token`` maps to the raw ``concordance_class`` / ``qualifier_class`` key; a dict ``source_support``
    is never read as empty); confabulation (no ref resolves) is DROPPED; a dead/NULL substrate contains
    NOTHING (fail-closed).

The fixtures are the real emitted packages for CD274×LUAD + ERBB2×BRCA (the pilot targets, trimmed to
``evidence_package`` + ``run_health``) and the pilot's validated finding sets transcribed into the
production single-array schema (``judge_response_cd274_luad.json`` = the 5 contract-aware TRUE findings;
``judge_findings_false_premise.json`` = the two known false-premise findings + a pure confabulation).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

_LOOP = Path(__file__).resolve().parents[1]  # eval/loop
_CRITIC = _LOOP / "critic"
for _p in (str(_LOOP), str(_CRITIC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import containment as C  # noqa: E402
import substrate as S  # noqa: E402

_FIX = Path(__file__).resolve().parent / "fixtures"


def _substrate(name: str) -> dict:
    d = json.loads((_FIX / f"{name}_emitted.json").read_text())
    return S.assemble_from_objects(d["evidence_package"], d["decision"])


def _true_findings() -> list[dict]:
    return json.loads((_FIX / "judge_response_cd274_luad.json").read_text())["findings"]["value"]


def _false(name: str) -> dict:
    return json.loads((_FIX / "judge_findings_false_premise.json").read_text())[name]


# ── ACCEPTANCE: the pilot finding set — true findings pass, both false-premise findings rejected ──────
def test_true_pilot_findings_all_pass_containment():
    """On the CD274 pilot finding set (the 5 contract-aware TRUE findings), containment passes EVERY one:
    each is grounded against the raw island and none contradicts a field contract."""
    sub = _substrate("cd274_luad")
    rep = C.contain({"findings": _true_findings(), "skipped": None}, sub)
    assert rep["n_in"] == 5
    assert rep["n_contained"] == 5, [f["_containment"] for f in rep["all"]]
    assert rep["n_dropped"] == 0 and rep["n_demoted"] == 0
    for f in rep["contained"]:
        assert f["_containment"]["status"] == C.CONTAINED
        assert f["_containment"]["resolved_refs"]  # each true finding is grounded


def test_corroboration_overstated_finding_is_dropped_by_contract():
    """CATCH 1 (acceptance): the CD274 `corroboration:high` 'overstated' finding is REJECTED — corroboration
    is independence-agreement, not within-arm strength, so proposing to lower it for a weakly-detected arm
    contradicts the contract. It is DROPPED (false premise), never routed."""
    sub = _substrate("cd274_luad")
    out = C.check_finding(_false("corroboration_overstated_cd274"), sub)
    assert out["_containment"]["status"] == C.DROPPED_CONTRACT
    assert "INDEPENDENCE-AGREEMENT" in out["_containment"]["reason"]


def test_empty_arms_finding_is_demoted_as_substrate_shape_artifact():
    """CATCH 2 (acceptance): the ERBB2 'empty arms' finding is REJECTED — a shape-aware re-read of the RAW
    island's dict `source_support` finds the arms, so the emptiness is a substrate-shape artifact. It is
    DEMOTED to the outer loop's schema-coherence lane, never routed to a tier."""
    sub = _substrate("erbb2_brca")
    out = C.check_finding(_false("empty_arms_erbb2"), sub)
    assert out["_containment"]["status"] == C.DEMOTED_SHAPE
    assert "shape" in out["_containment"]["reason"] or "artifact" in out["_containment"]["reason"]


def test_acceptance_mixed_set_partitions_true_from_false():
    """The whole acceptance in one pass: a mixed judge result (3 true CD274 findings + the corroboration
    false premise + a pure confabulation) partitions into contained vs dropped — the false ones never
    land in `contained`."""
    sub = _substrate("cd274_luad")
    mixed = _true_findings()[:3] + [_false("corroboration_overstated_cd274"), _false("pure_confabulation")]
    rep = C.contain({"findings": mixed, "skipped": None}, sub)
    assert rep["n_in"] == 5
    assert rep["n_contained"] == 3
    assert rep["n_dropped"] == 2
    dropped_reasons = {f["_containment"]["status"] for f in rep["dropped"]}
    assert dropped_reasons == {C.DROPPED_CONTRACT, C.DROPPED_UNRESOLVED}


# ── the MUTATION TOOTH: the contract check is what rejects the corroboration misread ──────────────────
def test_mutation_tooth_removing_contract_check_lets_the_false_finding_pass(monkeypatch):
    """TOOTH (acceptance): a finding citing a field whose contract contradicts the claim FAILS containment
    BECAUSE of the contract check. Neuter the contract check and the corroboration-overstated finding
    wrongly passes (its refs DO resolve) — proving the contract check, not mere ref-resolution, is what
    catches the semantic misread. Reinstating the check reds this difference."""
    sub = _substrate("cd274_luad")
    finding = _false("corroboration_overstated_cd274")

    guarded = C.check_finding(finding, sub)
    assert guarded["_containment"]["status"] == C.DROPPED_CONTRACT  # with the contract check: dropped

    monkeypatch.setattr(C, "_corroboration_contract_contradiction", lambda f, b: None)
    unguarded = C.check_finding(finding, sub)
    assert unguarded["_containment"]["status"] == C.CONTAINED  # without it: a false premise would route
    assert unguarded["_containment"]["resolved_refs"]  # (ref-resolution alone is necessary-not-sufficient)


def test_contract_check_does_not_fire_on_a_contract_affirming_finding():
    """The contract check must NOT reject a finding that AFFIRMS a corroboration field is correct-by-
    contract (true finding #3 says exactly that). It cites arm datums + the L3 headline, not a
    `.corroboration` ref, so the structural pre-condition keeps it out of the contract check."""
    sub = _substrate("cd274_luad")
    affirming = next(f for f in _true_findings() if "CORRECT BY CONTRACT" in f.get("finding", ""))
    out = C.check_finding(affirming, sub)
    assert out["_containment"]["status"] == C.CONTAINED


# ── ref re-resolution against the RAW island (shape-aware) ────────────────────────────────────────────
def test_token_ref_resolves_against_raw_island_concordance_key():
    """`l2b.<fam>.token` is the substrate's abstraction; re-resolution maps it to the RAW island's
    per-family token key (`concordance_class`) — not a re-normalised copy."""
    sub = _substrate("cd274_luad")
    assert C.resolve_ref("l2b.tumor_presence_concordance.token", sub) == "tumor_presence_discordant"
    assert C.resolve_ref("l2b.bulk_vs_singlecell_coverage_concordance.token", sub) == "bulk_masks_low_coverage"


def test_arm_datum_resolves_shape_aware_for_both_container_shapes():
    """An arm datum resolves through `iter_source_support` for BOTH a list `source_support`
    (tumor_presence_concordance) and a dict-keyed one (bulk_vs_singlecell_coverage_concordance — the ERBB2
    'empty arms' artifact's root cause); a dict is never iterated as a list → never read as empty."""
    sub = _substrate("cd274_luad")
    val = C.resolve_ref("l2b.tumor_presence_concordance.arms[bulk_rna].datum.high_fraction", sub)
    assert isinstance(val, (int, float))
    # the dict-source_support family's arm is reachable (the ERBB2 'empty arms' artifact's root cause)
    arm = C.resolve_ref(
        "l2b.bulk_vs_singlecell_coverage_concordance.arms[bulk_tumor_presence]", _substrate("erbb2_brca")
    )
    assert isinstance(arm, dict) and arm


def test_unresolved_ref_returns_missing_sentinel():
    sub = _substrate("cd274_luad")
    assert C.resolve_ref("l2b.no_such_family.token", sub) is C._MISSING
    assert C.resolve_ref("l2a.no_such_family.anchors.x", sub) is C._MISSING
    assert C.resolve_ref("l3.no_such_key", sub) is C._MISSING


def test_resolved_falsy_value_is_not_mistaken_for_absent():
    """A resolved field whose value is falsy (0 / None / []) must still count as RESOLVED — presence, not
    truthiness, decides grounding. (n_cohorts anchors are small ints incl. possibly 0.)"""
    sub = _substrate("cd274_luad")
    v = C.resolve_ref("l2a.tumor_elevation_breadth.anchors.n_cohorts_elevated", sub)
    assert v is not C._MISSING


# ── confabulation + fail-closed on a dead/empty substrate ─────────────────────────────────────────────
def test_pure_confabulation_is_dropped():
    sub = _substrate("cd274_luad")
    out = C.check_finding(_false("pure_confabulation"), sub)
    assert out["_containment"]["status"] == C.DROPPED_UNRESOLVED
    assert out["_containment"]["resolved_refs"] == []


def test_null_substrate_contains_nothing_fail_closed():
    """A dead / NULL-everything substrate re-verifies NOTHING: no finding may route (fail closed)."""
    d = json.loads((_FIX / "cd274_luad_emitted.json").read_text())
    dead = S.assemble_from_objects(d["evidence_package"], {"run_health": {"n_cards_resolved": 0}})
    assert dead["null_everything"] is True
    rep = C.contain({"findings": _true_findings(), "skipped": None}, dead)
    assert rep["skipped"] and rep["n_contained"] == 0
    assert rep["contained"] == []


def test_skipped_judge_result_passes_skip_through():
    sub = _substrate("cd274_luad")
    rep = C.contain({"findings": [], "skipped": "null_everything: dead package"}, sub)
    assert rep["skipped"] == "null_everything: dead package"
    assert rep["n_contained"] == 0 and rep["n_dropped"] == 0


def test_report_is_propose_only_no_verdict_surface():
    """STOP-A: containment never asserts a verdict/recommendation; `report_only` stays True."""
    sub = _substrate("cd274_luad")
    rep = C.contain({"findings": _true_findings(), "skipped": None}, sub)
    assert rep["report_only"] is True
    forbidden = {"verdict", "recommendation", "go_forth", "proposed_verdict", "decision"}
    assert not (set(rep) & forbidden)


def test_check_finding_does_not_mutate_input():
    sub = _substrate("cd274_luad")
    f = _false("corroboration_overstated_cd274")
    before = copy.deepcopy(f)
    C.check_finding(f, sub)
    assert f == before  # the input finding is not mutated (the result is a fresh dict)


# ── Adversarial-verify extension (SK#2303 follow-on): tail/max class-semantics + consumption + ──────────
#    provenance.sources arm materialization. Synthetic dependency bundle built through the REAL substrate
#    assembler so the new l3_claims + _class_semantics wiring is exercised end-to-end.
def _dep_package() -> dict:
    """A minimal `--emit-envelope`-shaped dependency package: a strongly_selective (tail) crispr essentiality
    property, a 'strong' (max) paralog property, a chemical-genetic property, a concordance island that
    materializes its arms under provenance.sources (NO source_support), and L3 claims citing two of the
    L2a cards."""
    return {
        "source_properties": {
            "crispr_essentiality": {
                "card_id": "pan-cancer-crispr-dependency-distribution",
                "property": "strongly_selective",
                "anchors": [
                    {"field": "fraction_strongly_dependent", "value": 0.0636},
                    {"field": "median_chronos_panel", "value": -0.14},
                    {"field": "selectivity_index", "value": 0.93},
                ],
            },
            "paralog_buffering": {
                "card_id": "paralog-buffering",
                "property": "strong",
                "anchors": [
                    {"field": "n_paralogs_annotated", "value": 12},
                    {"field": "n_paralogs_functionally_buffering", "value": 6},
                    {"field": "strongest_paralog_delta", "value": 0.72},
                ],
            },
            "chemical_genetic_engagement": {
                "card_id": "prism-crispr-concordance",
                "property": "triangulated_target_engaged",
                "anchors": [{"field": "best_spearman_r_crispr", "value": 0.37}],
            },
        },
        "integrated_properties": {
            "crispr_rnai_essentiality_concordance": {
                "concordance_class": "essentiality_concordant_dependent",
                "corroboration": "high",
                "provenance": {
                    "sources": [
                        {
                            "property": "crispr_essentiality",
                            "assay": "crispr_chronos",
                            "card_id": "pan-cancer-crispr-dependency-distribution",
                            "fields": {"dependency_class": "strongly_selective"},
                        },
                        {
                            "property": "rnai_essentiality",
                            "assay": "rnai_demeter",
                            "card_id": "pan-cancer-rnai-dependency-distribution",
                            "fields": {"rnai_dependency_class": "strongly_selective"},
                        },
                    ],
                    "independence_note": "two independent assays",
                },
            },
        },
        "local_composites": {
            "epistemic_type": "composed",
            "claims": {
                "DEP": {"evidence_atom": {"cite": {"card_id": "pan-cancer-crispr-dependency-distribution"}}},
                "CHEM": {"evidence_atom": {"cite": {"card_id": "prism-crispr-concordance"}}},
            },
        },
    }


def _dep_substrate() -> dict:
    return S.assemble_from_objects(_dep_package(), {"run_health": {"n_cards_resolved": 3}})


def _dep_finding(**kw) -> dict:
    base = {"kind": "", "target": "", "finding": "", "why": "", "datum_refs": []}
    base.update(kw)
    return base


def test_substrate_surfaces_l3_claims_and_class_semantics():
    """The substrate wiring the extension depends on: local_composites.claims → l3_claims.cited_card_ids,
    and the _class_semantics contract rides on field_contracts."""
    sub = _dep_substrate()
    assert set(sub["l3_claims"]["cited_card_ids"]) == {
        "pan-cancer-crispr-dependency-distribution",
        "prism-crispr-concordance",
    }
    assert "crispr_essentiality" in sub["field_contracts"]["_class_semantics"]


def test_tail_class_misread_dropped_by_contract():
    """A class_not_supported_by_datum finding attacking the TAIL class `strongly_selective` on its near-zero
    MEDIAN (the wrong axis) contradicts the class-semantics contract ⇒ DROPPED."""
    sub = _dep_substrate()
    f = _dep_finding(
        kind="class_not_supported_by_datum",
        target="L2a.crispr_essentiality.property (strongly_selective)",
        finding="labels strongly_selective but median_chronos_panel=-0.14 is near zero / non-dependent in the typical line; the strong signal rests on a thin tail.",
        datum_refs=["l2a.crispr_essentiality.property", "l2a.crispr_essentiality.anchors.median_chronos_panel"],
    )
    out = C.check_finding(f, sub)
    assert out["_containment"]["status"] == C.DROPPED_CONTRACT
    assert "tail-defined" in out["_containment"]["reason"]


def test_max_class_misread_dropped_by_contract():
    """A class_not_supported_by_datum finding attacking the MAX class `strong` paralog_buffering on a
    FRACTION of members (6 of 12) contradicts the class-semantics contract ⇒ DROPPED."""
    sub = _dep_substrate()
    f = _dep_finding(
        kind="class_not_supported_by_datum",
        target="L2a.paralog_buffering.property",
        finding="property 'strong' but only 6 of 12 annotated paralogs buffer — not clearly licensed when only half buffer.",
        datum_refs=["l2a.paralog_buffering.property", "l2a.paralog_buffering.anchors.n_paralogs_annotated"],
    )
    out = C.check_finding(f, sub)
    assert out["_containment"]["status"] == C.DROPPED_CONTRACT
    assert "max-defined" in out["_containment"]["reason"]


def test_class_semantics_does_not_fire_on_a_non_tail_class():
    """Guard against over-firing: if the family's CURRENT class token is not one of the basis's tail/max
    classes, a central-tendency dispute is a legitimate finding, left to a human (CONTAINED)."""
    pkg = _dep_package()
    pkg["source_properties"]["crispr_essentiality"]["property"] = "common_essential"
    sub = S.assemble_from_objects(pkg, {"run_health": {"n_cards_resolved": 3}})
    f = _dep_finding(
        kind="class_not_supported_by_datum",
        target="L2a.crispr_essentiality.property",
        finding="median_chronos_panel near zero contradicts the common_essential class.",
        datum_refs=["l2a.crispr_essentiality.property"],
    )
    out = C.check_finding(f, sub)
    assert out["_containment"]["status"] == C.CONTAINED


def test_mutation_tooth_removing_class_check_lets_the_misread_pass(monkeypatch):
    """The class-semantics check is load-bearing: neuter it and the tail-class misread wrongly routes."""
    sub = _dep_substrate()
    f = _dep_finding(
        kind="class_not_supported_by_datum",
        target="L2a.crispr_essentiality.property (strongly_selective)",
        finding="median near zero / non-dependent in the typical line; rests on a thin tail.",
        datum_refs=["l2a.crispr_essentiality.property"],
    )
    assert C.check_finding(f, sub)["_containment"]["status"] == C.DROPPED_CONTRACT
    monkeypatch.setattr(C, "_class_semantics_contradiction", lambda *_: None)
    assert C.check_finding(f, sub)["_containment"]["status"] == C.CONTAINED


def test_unused_signal_dropped_when_card_cited_by_an_l3_claim():
    """A 'surface_unused_signal' whose L2a card IS cited by an L3 claim has a false premise ⇒ DROPPED."""
    sub = _dep_substrate()
    f = _dep_finding(
        kind="surface_unused_signal",
        target="L2a.chemical_genetic_engagement",
        finding="chemical_genetic_engagement sits isolated in l2a and is never surfaced / uncaptured.",
        datum_refs=["l2a.chemical_genetic_engagement.anchors.best_spearman_r_crispr"],
    )
    out = C.check_finding(f, sub)
    assert out["_containment"]["status"] == C.DROPPED_CONTRACT
    assert "uncaptured" in out["_containment"]["reason"]


def test_unused_signal_contained_when_card_absent_from_l3_claims():
    """Conservative: a property genuinely NOT cited by any L3 claim (paralog_buffering) is NOT force-dropped
    — the 'not surfaced' observation is left for a human / the LLM critic (CONTAINED)."""
    sub = _dep_substrate()
    f = _dep_finding(
        kind="surface_unused_signal",
        target="L2a.paralog_buffering",
        finding="paralog_buffering is computed but never surfaced into an L2b family or an L3 claim.",
        datum_refs=["l2a.paralog_buffering.property"],
    )
    assert C.check_finding(f, sub)["_containment"]["status"] == C.CONTAINED


def test_mutation_tooth_removing_l3_claims_lets_the_unused_misread_pass():
    """The consumption check is load-bearing: with no l3_claims the 'uncaptured' misread wrongly routes."""
    sub = _dep_substrate()
    f = _dep_finding(
        kind="surface_unused_signal",
        target="L2a.chemical_genetic_engagement",
        finding="chemical_genetic_engagement sits isolated and is uncaptured / never surfaced.",
        datum_refs=["l2a.chemical_genetic_engagement.anchors.best_spearman_r_crispr"],
    )
    assert C.check_finding(f, sub)["_containment"]["status"] == C.DROPPED_CONTRACT
    sub["l3_claims"] = {"axes": [], "cited_card_ids": []}
    assert C.check_finding(f, sub)["_containment"]["status"] == C.CONTAINED


def test_empty_arms_under_provenance_sources_is_demoted():
    """An 'empty arms[]' claim against a family that materializes its arms under provenance.sources (NO
    source_support) is a schema-shape note ⇒ DEMOTED, never a tier finding."""
    sub = _dep_substrate()
    f = _dep_finding(
        kind="regroup_arms",
        target="L2b.crispr_rnai_essentiality_concordance.arms",
        finding="declares corroboration:high but the materialized `arms` array is EMPTY; the two arms exist only inside provenance.sources.",
        datum_refs=["l2b.crispr_rnai_essentiality_concordance.raw_island.provenance.sources"],
    )
    out = C.check_finding(f, sub)
    assert out["_containment"]["status"] == C.DEMOTED_SHAPE
    assert "provenance.sources" in out["_containment"]["reason"]


def test_mutation_tooth_empty_arms_without_provenance_sources_is_not_demoted():
    """Removing provenance.sources (and leaving no source_support) means the empty-arms refutation finds no
    arms ⇒ the demotion no longer fires (the provenance.sources extension is load-bearing)."""
    pkg = _dep_package()
    pkg["integrated_properties"]["crispr_rnai_essentiality_concordance"]["provenance"]["sources"] = []
    sub = S.assemble_from_objects(pkg, {"run_health": {"n_cards_resolved": 3}})
    f = _dep_finding(
        kind="regroup_arms",
        target="L2b.crispr_rnai_essentiality_concordance.arms",
        finding="the materialized `arms` array is EMPTY.",
        datum_refs=["l2b.crispr_rnai_essentiality_concordance.raw_island.provenance.sources"],
    )
    assert C.check_finding(f, sub)["_containment"]["status"] != C.DEMOTED_SHAPE
