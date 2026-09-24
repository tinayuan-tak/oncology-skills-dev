"""Unit tests for functional-requirement's claim vector (skills/_skills_common/dependency_claims.py),
the SECOND concrete over claim_vector_core. Pin the DEP/SEL/COND/CHEM tier mappings + the corroboration
combination (RNAi corroboration, Broad↔Sanger lift, omics-predictability, conflict caps) + the
deterministic key-signals read. Pure over a headline dict — no S3, no card reads.

The strong-case headline mirrors the frozen KRAS/COADREAD replay fixture
(functional-requirement/tests/fixtures/kras_coadread.yaml) so the unit-level expectations track the
integration replay.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.dependency_claims import (  # noqa: E402
    dependency_claim_vector,
    dependency_key_signals,
)


def _kras_headline():
    """KRAS/COADREAD-shaped: a selective, cross-consortium-corroborated, chemically-confirmed
    dependency with no curated SL partner (a GAP, not a negative)."""
    return {
        "crispr_call": "strongly_selective",
        "rnai_call": "strongly_selective",
        "concordance_call": "moderately_concordant_non_dependent",
        "lineage_selectivity": "lineage_selective",
        "n_lineages_evaluated": 26,
        "cross_consortium_class": "concordant_dependent",
        "predictability_class": "own_omics_driven",
        "partner_conditional_class": "no_partner_mapped",
        "partner_stratification_q": None,
        "n_partner_deficient": None,
        "prism_concordance_class": "triangulated_target_engaged",
        "n_compounds_evaluated": 21,
    }


def test_kras_claim_vector_tiers():
    vec = dependency_claim_vector(_kras_headline(), [])
    assert vec["DEP"]["signal"] == "strong"
    # base moderate (moderately_concordant_non_dependent) + RNAi corroboration + cross-consortium
    # replication + own-omics predictability → high
    assert vec["DEP"]["corroboration"] == "high"
    assert vec["DEP"]["conflict"] is None
    # SEL and CHEM are `single_arm`, not `high`: both used to grade the BREADTH of a single scan
    # (`n_lineages_evaluated`, compound count) on the corroboration axis. Breadth is how much ONE arm
    # saw — 20 lineages in one DepMap panel is still one panel — so the old `high` reported cross-source
    # agreement that no second source ever supplied. Contrast DEP above, which stays `high` because its
    # arms (CRISPR, RNAi, cross-consortium replication) really are independent.
    assert vec["SEL"] == {
        "signal": "strong",
        "corroboration": "single_arm",
        "evidence": vec["SEL"]["evidence"],
        "conflict": None,
        "informs": vec["SEL"]["informs"],
    }
    assert vec["CHEM"]["signal"] == "strong" and vec["CHEM"]["corroboration"] == "single_arm"


def test_no_partner_mapped_is_gap_not_absent():
    """COND on a target with no curated partner must be `unmeasured` (a coverage gap), NEVER `absent`
    (which would read as 'measured, not synthetic-lethal')."""
    vec = dependency_claim_vector(_kras_headline(), [])
    assert vec["COND"]["signal"] == "unmeasured"
    assert vec["COND"]["corroboration"] == "unmeasured"
    assert "GAP" in vec["COND"]["evidence"]


def test_kras_key_signals_deterministic():
    ks = dependency_key_signals(_kras_headline(), [])
    assert ks["headline"] == "Selective genetic dependency, chemically confirmed."
    # DEP, SEL, CHEM all >= moderate → all three cited; COND (gap) is gated out; top-3 cap holds
    assert len(ks["supports"]) == 3
    assert any("independently corroborated across consortia" in s for s in ks["supports"])
    # all critical claims strong → no caveat
    assert ks["caveat"] is None


def test_pan_essential_flags_broad_tox_conflict():
    h = _kras_headline()
    h["crispr_call"] = "common_essential"
    vec = dependency_claim_vector(h, [])
    assert vec["DEP"]["signal"] == "strong"  # strong MAGNITUDE
    assert "pan-essential" in (vec["DEP"]["conflict"] or "")  # …but flagged as a broad-tox liability


def test_rnai_disagreement_flags_conflict_and_caps_corroboration():
    h = _kras_headline()
    h["rnai_call"] = "non_dependent"
    h["cross_consortium_class"] = "single_consortium_only"  # remove the consortium lift
    h["predictability_class"] = "unpredictable"  # remove the predictability lift
    vec = dependency_claim_vector(h, [])
    assert vec["DEP"]["signal"] == "strong"
    assert "RNAi" in (vec["DEP"]["conflict"] or "")
    assert vec["DEP"]["corroboration"] in ("moderate", "low")  # capped, not high


def test_non_dependent_case():
    h = {
        "crispr_call": "non_dependent",
        "rnai_call": "non_dependent",
        "concordance_call": "strongly_concordant_non_dependent",
        "lineage_selectivity": "no_lineage_enrichment",
        "n_lineages_evaluated": 26,
        "cross_consortium_class": "concordant_non_dependent",
        "predictability_class": "unpredictable",
        "partner_conditional_class": "not_partner_stratified",
        "prism_concordance_class": "data_unavailable",
    }
    vec = dependency_claim_vector(h, [])
    assert vec["DEP"]["signal"] == "absent"
    assert vec["SEL"]["signal"] == "absent"
    assert vec["CHEM"]["signal"] == "unmeasured"
    ks = dependency_key_signals(h, [])
    assert ks["headline"] == "Not a genetic dependency in the pooled panel."
    assert ks["supports"] == []  # nothing >= moderate
    assert ks["caveat"] is not None  # weakest measured critical fires


def test_underpowered_is_gap_not_absent():
    h = _kras_headline()
    h["crispr_call"] = "non_dependent_underpowered"
    vec = dependency_claim_vector(h, [])
    assert vec["DEP"]["signal"] == "unmeasured"  # admissibility gap, not a trusted floor


def test_prism_off_target_is_negative_with_conflict():
    h = _kras_headline()
    h["prism_concordance_class"] = "discordant_off_target_likely"
    vec = dependency_claim_vector(h, [])
    assert vec["CHEM"]["signal"] == "negative"
    assert "off-target" in (vec["CHEM"]["conflict"] or "")


def test_prism_quorum_lifts_dep_corroboration():
    """QUORUM-awareness (2026-09-03): PRISM `triangulated_target_engaged` is a THIRD independent
    perturbation channel — with the genetic dependency present it lifts DEP corroboration one step. The
    only difference between the two headlines is the PRISM class (byte-isolated to the new arm)."""
    h = {
        "crispr_call": "strongly_selective",
        "rnai_call": None,
        "concordance_call": "moderately_concordant_dependent",
        "cross_consortium_class": "single_consortium_only",
        "predictability_class": "unpredictable",
        "prism_concordance_class": "triangulated_target_engaged",
        "n_compounds_evaluated": 15,
    }
    assert dependency_claim_vector(h, [])["DEP"]["corroboration"] == "high"
    h2 = dict(h, prism_concordance_class="thin_evidence")
    assert dependency_claim_vector(h2, [])["DEP"]["corroboration"] == "moderate"  # no PRISM arm → not lifted


def test_prism_quorum_no_bump_without_genetic_dependency():
    """The PRISM bump is gated on the genetic dependency being present — a compound-kill read on a
    non-dependent target must NOT manufacture DEP corroboration."""
    h = {
        "crispr_call": "non_dependent",
        "rnai_call": "non_dependent",
        "concordance_call": "moderately_concordant_dependent",
        "prism_concordance_class": "triangulated_target_engaged",
    }
    assert dependency_claim_vector(h, [])["DEP"]["corroboration"] == "moderate"  # base, un-bumped


def test_strong_paralog_surfaces_caveat_when_no_primary_conflict():
    """A STRONG paralog buffer is a decision-relevant caveat the four axes don't carry — surfaced in
    key_signals when no more-critical DEP conflict outranks it. Gated on the paralog_buffering_class
    HEADLINE field, so the KRAS unit fixture (which omits it → test_kras_key_signals_deterministic sees
    caveat=None) stays byte-stable; here we add the field to exercise the arm."""
    h = dict(_kras_headline(), paralog_buffering_class="strong", strongest_paralog_symbol="NRAS")
    ks = dependency_key_signals(h, [])
    assert ks["caveat"] and "paralog" in ks["caveat"].lower() and "NRAS" in ks["caveat"]


def test_pan_essential_conflict_outranks_paralog_caveat():
    """The sharper DEP conflict (pan-essential broad-tox) must win the single caveat slot over paralog."""
    h = dict(_kras_headline(), crispr_call="common_essential", paralog_buffering_class="strong")
    assert "pan-essential" in dependency_key_signals(h, [])["caveat"]


def test_partial_paralog_caveat_on_absence_verdict():
    """A PARTIAL paralog buffer on a discordant/non-dependent verdict (SMARCA4→SMARCA2 class) surfaces the
    paralog-masking caveat — the absence may under-call a paralog-buffered vulnerability. Gated on
    dependency_verdict ∈ {discordant, non_dependent}; byte-stable on the KRAS unit fixture (omits both)."""
    h = dict(
        _kras_headline(),
        crispr_call="non_dependent",
        rnai_call="non_dependent",
        paralog_buffering_class="partial",
        strongest_paralog_symbol="SMARCA2",
        dependency_verdict="discordant",
    )
    ks = dependency_key_signals(h, [])
    assert ks["caveat"] and "SMARCA2" in ks["caveat"] and "paralog" in ks["caveat"].lower()


def test_partial_paralog_no_caveat_on_positive_verdict():
    """A PARTIAL paralog on a POSITIVE call (e.g. BRAF/MAP3K7 lineage_selective) must NOT add noise —
    scoped to absence verdicts only."""
    h = dict(
        _kras_headline(),
        paralog_buffering_class="partial",
        strongest_paralog_symbol="MAP3K7",
        dependency_verdict="lineage_selective",
    )
    ks = dependency_key_signals(h, [])
    assert not (ks["caveat"] and "MAP3K7" in ks["caveat"])  # partial+positive → no paralog caveat


def test_partner_conditional_strong_signal():
    h = _kras_headline()
    h["partner_conditional_class"] = "partner_conditional_moderately_dependent"
    h["n_partner_deficient"] = 40
    h["partner_stratification_q"] = 0.01
    vec = dependency_claim_vector(h, [])
    assert vec["COND"]["signal"] == "moderate"
    # `single_arm`, not `high`. A significant q AND a large n are two statistics of the SAME partner
    # stratification test, not two independent arms agreeing — passing both means one arm is well
    # powered, which is the arm's STRENGTH, not its corroboration.
    assert vec["COND"]["corroboration"] == "single_arm"


# ── citable evidence atoms (values bound to {card_id, fields} + entity) ──────────────────────────────
def _kras_cards():
    """Minimal card summaries mirroring the KRAS/COADREAD fixture — the fields the atom_fns cite."""
    return [
        {
            "card_id": "pan-cancer-crispr-dependency-distribution",
            "summary": {
                "bimodality_coefficient": 0.70,
                "distribution_shape": "bimodal_selective",
                "fraction_strongly_dependent": 0.176,
                "median_chronos_panel": -0.457,
                "p5_chronos_panel": -2.105,
                "n_cell_lines_evaluated": 1538,
                "selectivity_index": 0.855,
                "dep_control_position_class": "between_controls",
            },
        },
        {
            "card_id": "dependency-lineage-selectivity",
            "summary": {
                "enrichment_class": "lineage_selective",
                "lineage_variance_explained": 0.186,
                "lineage_omnibus_kruskal_h": 304.6,
                "lineage_omnibus_effect_size_class": "large",
                "n_enriched_lineages": 3,
                "n_lineages_evaluated": 26,
            },
        },
        {
            "card_id": "prism-crispr-concordance",
            "summary": {
                "crispr_prism_concordance_class": "triangulated_target_engaged",
                "n_compounds_evaluated": 21,
                "n_dual_responders": 20,
                "best_spearman_r_crispr": 0.37,
                "best_spearman_r_rnai": 0.44,
            },
        },
    ]


def test_dependency_atoms_present_and_citable_with_cards():
    vec = dependency_claim_vector(_kras_headline(), _kras_cards())
    dep = vec["DEP"]["evidence_atom"]
    assert dep["cite"]["card_id"] == "pan-cancer-crispr-dependency-distribution"
    assert dep["values"]["bimodality_coefficient"] == 0.70  # the responder-shape signal, carried
    assert dep["values"]["fraction_strongly_dependent"] == 0.176
    assert "bimodality_coefficient" in dep["cite"]["fields"]  # citable by card_id.field
    assert dep["entity"]["sample_context"] == "cell_line"
    assert dep["entity"]["measurement_type"] == "crispr_lof_dependency"
    assert vec["SEL"]["evidence_atom"]["cite"]["card_id"] == "dependency-lineage-selectivity"
    assert vec["CHEM"]["evidence_atom"]["cite"]["card_id"] == "prism-crispr-concordance"
    # COND: no partner card in the fixture (KRAS = no_partner_mapped) → no atom (honest gap, byte-stable)
    assert "evidence_atom" not in vec["COND"]


def test_dependency_atoms_absent_without_cards():
    # cards=[] → atom_fns return None → every axis keeps the legacy 5-key shape (byte-stable)
    vec = dependency_claim_vector(_kras_headline(), [])
    for ax in ("DEP", "SEL", "COND", "CHEM"):
        assert "evidence_atom" not in vec[ax], f"{ax} gained an atom with no source card"


# ── L2b-2: cross-source essentiality concordance (CRISPR × RNAi) (SK#1533) ────────────────────────────
# A CROSS-SOURCE integration claim: CRISPR Chronos essentiality (pan-cancer-crispr-dependency-distribution
# .dependency_class) integrated with RNAi DEMETER2 essentiality (pan-cancer-rnai-dependency-distribution
# .rnai_dependency_class) — two ORTHOGONAL loss-of-function assays emitting the SAME vocabulary. Store the
# RAW per-assay tokens and RE-DERIVE the claim in-test — a derived fixture cannot fail; the tokens are the
# irreproducible inputs. The claim reads the cards directly, not the headline, so it is exercised through
# the same dependency_claim_vector(headline, cards) seam without touching the four verdict axes.
_ESS_KEY = "crispr_rnai_essentiality_concordance"


def _ess_cards(crispr="common_essential", rnai="common_essential"):
    """Card set carrying the two assay essentiality tokens. crispr/rnai=None omit the field (assay
    data-absence path); an off-scale token (e.g. data_unavailable / *_underpowered) is passed as-is."""
    crispr_summary = {"bimodality_coefficient": 0.70, "distribution_shape": "bimodal_selective"}
    if crispr is not None:
        crispr_summary["dependency_class"] = crispr
    rnai_summary = {}
    if rnai is not None:
        rnai_summary["rnai_dependency_class"] = rnai
    return [
        {"card_id": "pan-cancer-crispr-dependency-distribution", "summary": crispr_summary},
        {"card_id": "pan-cancer-rnai-dependency-distribution", "summary": rnai_summary},
    ]


def test_ess_concordant_dependent():
    # Both assays call a dependency → concordant_dependent, corroborated by two independent LoF arms.
    claim = dependency_claim_vector(_kras_headline(), _ess_cards(crispr="common_essential", rnai="broadly_dependent"))[
        _ESS_KEY
    ]
    assert claim["concordance_class"] == "essentiality_concordant_dependent"
    assert claim["corroboration"] == "high"  # two measured arms agree
    assert claim["integration_method"] == "explicit_deterministic"  # NO llm_inference: reproducible by contract
    assert claim["assay_support"]["agreed_direction"] == "dependent"
    # Provenance graph records BOTH source properties, recoverable, + an independence note.
    srcs = {s["property"]: s for s in claim["provenance"]["sources"]}
    assert srcs["crispr_essentiality"]["card_id"] == "pan-cancer-crispr-dependency-distribution"
    assert srcs["crispr_essentiality"]["fields"]["dependency_class"] == "common_essential"
    assert srcs["rnai_essentiality"]["card_id"] == "pan-cancer-rnai-dependency-distribution"
    assert srcs["rnai_essentiality"]["fields"]["rnai_dependency_class"] == "broadly_dependent"
    assert "independent" in claim["provenance"]["independence_note"].lower()


def test_ess_concordant_nondependent():
    # Both assays call non_dependent → concordant_nondependent (agree it is NOT a dependency).
    claim = dependency_claim_vector(_kras_headline(), _ess_cards(crispr="non_dependent", rnai="non_dependent"))[
        _ESS_KEY
    ]
    assert claim["concordance_class"] == "essentiality_concordant_nondependent"
    assert claim["corroboration"] == "high"
    assert claim["assay_support"]["agreed_direction"] == "nondependent"


def test_ess_discordant_carries_which_assay_supports():
    # CRISPR dependent, RNAi not → assay_discordant; the disagreement is NAMED (which assay supports
    # which call), never collapsed or averaged. Corroboration degrades to low (arms point opposite).
    claim = dependency_claim_vector(_kras_headline(), _ess_cards(crispr="common_essential", rnai="non_dependent"))[
        _ESS_KEY
    ]
    assert claim["concordance_class"] == "essentiality_assay_discordant"
    assert claim["corroboration"] == "low"
    assert claim["assay_support"]["dependency_supported_by"] == "crispr_chronos"
    assert claim["assay_support"]["nondependency_supported_by"] == "rnai_demeter"
    # symmetric: RNAi dependent, CRISPR not
    claim2 = dependency_claim_vector(_kras_headline(), _ess_cards(crispr="non_dependent", rnai="broadly_dependent"))[
        _ESS_KEY
    ]
    assert claim2["assay_support"]["dependency_supported_by"] == "rnai_demeter"
    assert claim2["assay_support"]["nondependency_supported_by"] == "crispr_chronos"


def test_ess_single_assay_only_when_one_arm_is_a_gap():
    # RNAi resolves, CRISPR is an admissibility GAP (data_unavailable) → single_assay_only, naming the
    # RESOLVED arm and carrying its raw call (recoverable); corroboration is single_arm (one measured arm).
    claim = dependency_claim_vector(_kras_headline(), _ess_cards(crispr="data_unavailable", rnai="common_essential"))[
        _ESS_KEY
    ]
    assert claim["concordance_class"] == "essentiality_single_assay_only"
    assert claim["corroboration"] == "single_arm"
    assert claim["assay_support"]["resolved_by"] == "rnai_demeter"
    assert claim["assay_support"]["resolved_call"] == "common_essential"
    assert claim["assay_support"]["resolved_direction"] == "dependent"
    # an *_underpowered token is likewise a gap, not a floor: CRISPR resolves, RNAi underpowered
    claim2 = dependency_claim_vector(
        _kras_headline(), _ess_cards(crispr="strongly_selective", rnai="common_essential_underpowered")
    )[_ESS_KEY]
    assert claim2["concordance_class"] == "essentiality_single_assay_only"
    assert claim2["assay_support"]["resolved_by"] == "crispr_chronos"


def test_ess_selective_distinction_carried_not_collapsed():
    # strongly_selective is a dependency, but a SELECTIVE one — the distinction is carried in the payload
    # (selective_assays + the raw token in provenance), never collapsed into a bare pan/broad dependent.
    claim = dependency_claim_vector(_kras_headline(), _ess_cards(crispr="strongly_selective", rnai="common_essential"))[
        _ESS_KEY
    ]
    assert claim["concordance_class"] == "essentiality_concordant_dependent"
    assert claim["selective_assays"] == ["crispr_chronos"]  # only CRISPR read selective
    # both selective → both listed
    both = dependency_claim_vector(
        _kras_headline(), _ess_cards(crispr="strongly_selective", rnai="strongly_selective")
    )[_ESS_KEY]
    assert both["selective_assays"] == ["crispr_chronos", "rnai_demeter"]
    # neither selective → empty list (not omitted — a stable, honest empty)
    neither = dependency_claim_vector(
        _kras_headline(), _ess_cards(crispr="common_essential", rnai="broadly_dependent")
    )[_ESS_KEY]
    assert neither["selective_assays"] == []


def test_ess_recoverability_round_trip():
    # FIDELITY: the actual per-assay VALUES round-trip through provenance, not merely a key. Re-derive
    # the concordance direction from the stored raw tokens the same way the claim does.
    crispr_tok, rnai_tok = "broadly_dependent", "non_dependent"
    claim = dependency_claim_vector(_kras_headline(), _ess_cards(crispr=crispr_tok, rnai=rnai_tok))[_ESS_KEY]
    srcs = {s["property"]: s for s in claim["provenance"]["sources"]}
    assert srcs["crispr_essentiality"]["fields"]["dependency_class"] == crispr_tok
    assert srcs["rnai_essentiality"]["fields"]["rnai_dependency_class"] == rnai_tok
    # a consumer can reconstruct the discordance purely from the recovered tokens
    assert (crispr_tok in {"common_essential", "broadly_dependent", "strongly_selective"}) is True
    assert (rnai_tok == "non_dependent") is True
    assert claim["concordance_class"] == "essentiality_assay_discordant"


def test_ess_is_verdict_inert_no_signal_and_axes_unperturbed():
    # Verdict-INERT: the claim carries NO `signal` key (never a chip, never a tier), and surfacing it
    # must not perturb the DEP/SEL/COND/CHEM axes / _disclaimer. Toggle ONLY the RNAi card presence — a
    # card the four verdict axes do NOT read (they read signals off the HEADLINE and cite the CRISPR
    # card's OTHER fields) — so any axis delta would be MY perturbation, not the L2b-2 claim's.
    base = dependency_claim_vector(_kras_headline(), _ess_cards(crispr="common_essential", rnai=None))
    withclaim = dependency_claim_vector(
        _kras_headline(), _ess_cards(crispr="common_essential", rnai="common_essential")
    )
    # base: rnai absent but crispr resolves → single_assay_only still present (one arm resolves)
    assert base[_ESS_KEY]["concordance_class"] == "essentiality_single_assay_only"
    claim = withclaim[_ESS_KEY]
    assert "signal" not in claim, "an L2b claim must never carry a signal tier"
    for ax in ("DEP", "SEL", "COND", "CHEM", "_disclaimer"):
        assert withclaim[ax] == base[ax], f"surfacing the essentiality-concordance claim perturbed {ax}"


def test_ess_single_arm_mutation_only_degrades_defeating_both_erases():
    # M3-vs-M4 reach: a SINGLE-arm mutation (kill one assay's supply) may only DEGRADE the read to
    # single_assay_only — the concept survives on the surviving arm. ERASING the claim (key omitted)
    # requires defeating BOTH assay supplies. This is the "defeat every supply path" discipline.
    both = dependency_claim_vector(_kras_headline(), _ess_cards(crispr="common_essential", rnai="common_essential"))
    assert both[_ESS_KEY]["concordance_class"] == "essentiality_concordant_dependent"
    # defeat ONE arm → degrades, does not erase
    one_gone = dependency_claim_vector(_kras_headline(), _ess_cards(crispr="common_essential", rnai=None))
    assert _ESS_KEY in one_gone, "defeating one assay must NOT erase the claim"
    assert one_gone[_ESS_KEY]["concordance_class"] == "essentiality_single_assay_only"
    # defeat the OTHER arm → still degrades, does not erase
    other_gone = dependency_claim_vector(_kras_headline(), _ess_cards(crispr=None, rnai="common_essential"))
    assert _ESS_KEY in other_gone
    assert other_gone[_ESS_KEY]["concordance_class"] == "essentiality_single_assay_only"
    # defeat BOTH → key omitted (byte-stable erasure)
    both_gone = dependency_claim_vector(_kras_headline(), _ess_cards(crispr=None, rnai=None))
    assert _ESS_KEY not in both_gone, "only defeating BOTH assay supplies erases the claim"


def test_ess_omitted_when_both_absent_or_both_gaps():
    # Byte-stability: the KEY is omitted (not None) unless at least one assay resolves.
    assert _ESS_KEY not in dependency_claim_vector(_kras_headline(), [])  # no cards
    assert _ESS_KEY not in dependency_claim_vector(_kras_headline(), _ess_cards(crispr=None, rnai=None))
    # both assays present but BOTH are admissibility gaps → neither resolves → omitted
    assert _ESS_KEY not in dependency_claim_vector(
        _kras_headline(), _ess_cards(crispr="data_unavailable", rnai="non_dependent_underpowered")
    )
    # an off-roster / unknown token is treated as unresolved (not a silent dependent)
    assert _ESS_KEY not in dependency_claim_vector(
        _kras_headline(), _ess_cards(crispr="some_future_token", rnai="data_unavailable")
    )
