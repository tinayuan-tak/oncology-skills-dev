"""Unified-output completion for genomic-alteration-profile (v2.18.0). Four guards, all verdict-INERT:

1. VERDICT-TOKEN CLOSURE (de-vacuumed): every token the skill can publish — enumerated from the
   resolver YAML itself, plus data_unavailable and the skill-side reconciler token — lands in exactly
   one _GA_* strength bucket. Adding a rung with a NEW verdict fails this test rather than silently
   falling through _ga_availability's `return "measured_positive"`. That fall-through is the defect
   this module exists to keep fixed: recurrent_snv_subclonal_uncertain and
   biomarker_dependency_unconfirmed — tokens whose entire purpose is to withhold a driver call — were
   published as measured POSITIVES with a `none` magnitude.
2. SHADOW/VERDICT COHERENCE: _claim_record and _strength_certainty score the RECONCILED word, so the
   factored record can no longer contradict the verdict the same run publishes.
3. MODALITY SCOPE: the FOR-WHAT projection's four states, its two deliberate always-constant
   choices (biologics=na, no _refinements), and the two over-read guards that shaped it (spectrum
   shape tokens excluded; positive selectable-allele evidence required).
4. SPINE PASS-THROUGH: skill_report carries subgroup_signals + modality_scope.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent
ga = load_run_py(SKILL_DIR, "ga_run_modality")

# the fleet vocabulary this projection reads, so the fixtures below fire the REAL rule ids
_ELIGIBILITY, _REQUIRED_ROLE, _DISQUALIFIERS = ga._allele_selectivity_vocab()
_HOMDEL_CARDS = [
    {
        "card_id": "copy-number-distribution",
        "summary": {"cn_homozygous_deletion_recurrent": "recurrent_homozygous_deletion"},
    }
]


def _fired(*rule_ids):
    return [{"rule_id": r} for r in rule_ids]


def _allele_selective_fired(*extra):
    """The minimal REAL fired set that clears the shared allele-selectivity triple."""
    return _fired(*sorted(_ELIGIBILITY)[:1], *sorted(_REQUIRED_ROLE), *extra)


# --- 1. verdict-token closure ---------------------------------------------------------------


def _publishable_verdict_tokens():
    """Every verdict token this skill can publish, read from the resolver contract (NOT restated here —
    a restated list is how a new rung goes uncovered)."""
    spec = yaml.safe_load((ga.target_contracts_root() / "resolvers" / "genomic_alteration.resolver.yaml").read_text())
    tokens = {rung["verdict"] for rung in spec["resolve"]}
    tokens.add(spec["default"])
    tokens.add("data_unavailable")  # card-level open-world token
    tokens.add(ga.BIOMARKER_DEPENDENCY_UNCONFIRMED)  # skill-side reconciler demotion
    return tokens


def test_every_publishable_verdict_is_bucketed():
    buckets = {
        "_GA_STRONG_POS": ga._GA_STRONG_POS,
        "_GA_MOD_POS": ga._GA_MOD_POS,
        "_GA_NEG": ga._GA_NEG,
        "_GA_NEUTRAL": ga._GA_NEUTRAL,
        "_GA_NONE": ga._GA_NONE,
    }
    unbucketed, multi = [], []
    for token in sorted(_publishable_verdict_tokens()):
        hits = [name for name, members in buckets.items() if token in members]
        if not hits:
            unbucketed.append(token)
        elif len(hits) > 1:
            multi.append((token, hits))
    assert not unbucketed, (
        f"verdict tokens in NO _GA_* bucket: {unbucketed}. _genomic_strength returns 'none' and "
        "_ga_availability falls through to 'measured_positive' for these — a token nobody bucketed is "
        "published as a measured positive finding."
    )
    assert not multi, f"tokens in MORE than one bucket (ambiguous strength): {multi}"


def test_the_sanity_check_can_actually_fail():
    """The closure test above is only meaningful if an unbucketed token would be detected. It reads the
    resolver, so pin that a token absent from every bucket is in fact absent."""
    assert "a_token_no_rung_emits" not in (
        ga._GA_STRONG_POS | ga._GA_MOD_POS | ga._GA_NEG | ga._GA_NEUTRAL | ga._GA_NONE
    )


@pytest.mark.parametrize("token", sorted(ga._GA_NEUTRAL))
def test_neutral_family_is_neutral_and_insufficient_not_measured_positive(token):
    """The full neutral family — the two reconciler/backtest demotion tokens (_GA_UNCONFIRMED), the
    spectrum-SHAPE tokens lof/missense_dominant_pattern (a variant-composition shape, not a driver
    call), and mixed_pattern — must publish neutral strength + neutral direction + `insufficient`
    availability. v2.18.0 fixed the demotion tokens (they fell through to measured_positive); v2.19.0
    folds in the spectrum-shape tokens, which _GA_WEAK_POS had published as measured POSITIVES /
    `supports` while the verdict spine and _ga_modality_scope already read them as non-driver."""
    assert ga._genomic_strength(token) == "neutral"
    assert ga._ga_direction(token) == "neutral"
    assert ga._ga_availability(token) == "insufficient", (
        f"{token} is not a driver call; publishing it as measured_positive asserts the opposite"
    )


# --- 2. shadow / verdict coherence ---------------------------------------------------------


def _contradicting_dep_cards():
    """The exact card state reconcile_genomic_verdict demotes on: BOTH KO-dependency confidence cards
    oppose the claimed biomarker dependency (the live TP53/COADREAD configuration)."""
    return [
        {"card_id": "cross-consortium-dependency", "summary": {"cross_consortium_class": "concordant_non_dependent"}},
        {
            "card_id": "genomic-event-model-match",
            "summary": {"event_correspondence_class": "event_matched_not_dependent"},
        },
    ]


def test_claim_record_scores_the_reconciled_word_not_the_raw_ladder():
    cards = _contradicting_dep_cards()
    rec = ga._claim_record(
        cards,
        fired=_fired("mutant-strongly-dependent-supportive"),
        verdict_pair=("biomarker_stratified_dependency", "mutant-strongly-dependent-supportive"),
    )
    f = rec["finding"]
    assert f["state"] == ga.BIOMARKER_DEPENDENCY_UNCONFIRMED
    assert f["direction"] == "neutral"
    assert f["availability"] == "insufficient"
    # and the raw ladder still resolves to the un-demoted word, so this is reconciliation not a rung change
    assert ga.reconciled_verdict_from_cards("biomarker_stratified_dependency", []) == "biomarker_stratified_dependency"


def test_strength_certainty_scores_the_reconciled_word():
    sc = ga._strength_certainty(
        _contradicting_dep_cards(), fired=[], verdict_pair=("biomarker_stratified_dependency", None)
    )
    assert sc["strength"] == "neutral", "a demoted dependency must not score as strong_positive"


def test_reconciliation_only_demotes_the_dependency_family():
    cards = _contradicting_dep_cards()
    for token in ("confirmed_driver", "recurrent_deletion_driver", "passenger_pattern", "insufficient"):
        assert ga.reconciled_verdict_from_cards(token, cards) == token


# --- 3. modality scope ---------------------------------------------------------------------


def test_recurrent_homozygous_deletion_is_small_molecule_unfavorable():
    scope = ga._ga_modality_scope(_HOMDEL_CARDS, fired=[], verdict="multi_class_lof_driver")
    assert scope["small_molecule"] == "unfavorable"  # no protein to inhibit or degrade


def test_gof_driver_with_selectable_allele_is_favorable():
    scope = ga._ga_modality_scope(
        [], fired=_allele_selective_fired("snv-recurrence-top-driver-supportive"), verdict="confirmed_driver"
    )
    assert scope["small_molecule"] == "favorable"


def test_gof_driver_without_selectable_allele_is_conditional_not_favorable():
    """The amplicon/fusion/WT-binding targets (ERBB2, FGFR2, CCND1, MYC): a small molecule is viable but
    engages WILD-TYPE protein. The shared eligibility triple is a NEGATIVE screen only — it never
    establishes that a selectable lesion exists — so without positive allele evidence the answer is
    `conditional`. This is the guard that keeps OncoKB-gene-list-only surface antigens (TACSTD2, FOLR1,
    whose alteration_role reads direct_driver_gof with intogen_role absent) out of `favorable`."""
    scope = ga._ga_modality_scope([], fired=_allele_selective_fired(), verdict="multi_class_driver")
    assert scope["small_molecule"] == "conditional"


def test_amplification_disqualifier_blocks_favorable():
    scope = ga._ga_modality_scope(
        [],
        fired=_allele_selective_fired("snv-recurrence-top-driver-supportive", *sorted(_DISQUALIFIERS)[:1]),
        verdict="recurrent_amplification_driver",
    )
    assert scope["small_molecule"] == "conditional"


@pytest.mark.parametrize(
    "verdict",
    [
        "missense_dominant_pattern",
        "lof_dominant_pattern",
        "passenger_pattern",
        "mixed_pattern",
        "insufficient",
        "confirmed_lof_driver",
        ga.BIOMARKER_DEPENDENCY_UNCONFIRMED,
    ],
)
def test_non_gof_driver_verdicts_are_na(verdict):
    """Spectrum SHAPE is not a driver call: missense_dominant fires for 62% of the review panel including
    both the GAPDH and ACTB negative controls, so admitting it put both controls at `conditional`."""
    scope = ga._ga_modality_scope(
        [], fired=_allele_selective_fired("snv-recurrence-top-driver-supportive"), verdict=verdict
    )
    assert scope["small_molecule"] == "na"


@pytest.mark.parametrize(
    "verdict", ["confirmed_driver", "multi_class_lof_driver", "passenger_pattern", "insufficient", None]
)
def test_biologics_is_always_na_and_refinements_always_absent(verdict):
    """Deliberate, not a gap. genomic-alteration is an intracellular-INTRINSIC axis with no localization
    read: a focal amplification says nothing about whether the protein reaches the cell surface (that is
    surface-modality-fit's call), and asserting otherwise is how CD19/TACSTD2/FOLR1 would acquire a
    fabricated biologics favorability. _refinements stays absent because 0 of 59 genomic-card rules
    diverge between small_molecule and degrader, and the degrader's WT-engagement refinement is already
    owned by the safety axis."""
    scope = ga._ga_modality_scope(_HOMDEL_CARDS, fired=_allele_selective_fired(), verdict=verdict)
    assert scope["biologics"] == "na"
    assert "_refinements" not in scope


def test_modality_scope_degrades_to_none_on_a_contracts_read_fault(monkeypatch):
    monkeypatch.setattr(ga, "_allele_selectivity_vocab", lambda: (_ for _ in ()).throw(OSError("no contracts")))
    assert ga._ga_modality_scope([], fired=[], verdict="confirmed_driver") is None


# --- 4. spine pass-through ------------------------------------------------------------------


def test_skill_report_carries_modality_scope_and_subgroup_signals():
    cards = [{"card_id": cid, "summary": {}} for cid in ga.CARDS]
    hl = ga._build_headline(
        cards,
        "confirmed_driver",
        "cn-patient-focal-amplified-supportive",
        {},
        fired=_allele_selective_fired("snv-recurrence-top-driver-supportive"),
    )
    sr = hl["skill_report"]
    assert sr["modality_scope"] == {"small_molecule": "favorable", "biologics": "na"}
    # subgroup_signals is computed into the headline and must not be dropped at the call site
    assert sr["subgroup_signals"] == hl.get("subgroup_signals")


def test_claim_record_shadow_carries_modality_scope():
    rec = ga._claim_record(
        _HOMDEL_CARDS,
        fired=_fired("cn-recurrent-homozygous-deletion-supportive"),
        verdict_pair=("recurrent_deletion_driver", "cn-recurrent-homozygous-deletion-supportive"),
    )
    # top-level FOR-WHAT coordinate on the record (assemble_claim_record), beside finding/mechanism
    assert rec["modality_scope"] == {"small_molecule": "unfavorable", "biologics": "na"}
