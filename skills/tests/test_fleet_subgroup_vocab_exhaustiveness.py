"""Fleet-wide vocab-exhaustiveness guard for the signals-first sub-group panel's VALUE→TIER maps.

THE PATTERN (SK#1644, the "fix PATTERN not instance" culmination of the audit sextet). Every
subgroup-panel skill tiers one `*_class` field per source card with
`make_value_classifier(_<SKILL>_VALUE_TIERS, default=default_classify)`. Any producer token the map
OMITS falls through to the lens-blind `default_classify` substring heuristic — which returns `absent`
for anything without a strong/moderate/weak/sparse keyword, i.e. it silently INVERTS a present signal
to signal-absence. When a source card's live vocabulary grows or renames a token and the map is not
updated, that token reads `absent` in the emitted panel with nothing failing. This is the exact bug
this cluster has been filed for piecewise ≥10 times (#1550/#1559/#1563/#1587/#1595 token→tier drift;
immune-context comment on #1644). Guard B (target-intrinsic/tests/test_subgroup_value_tiers.py) proved
the data-driven mechanism on ONE skill; this generalizes it to all 12.

THE GUARD is data-driven off the CI-pinned target-contracts card contracts: for each skill it reproduces
derive_subgroups' binding (the per-skill reader spec for target-intrinsic/functional-requirement, else
the `_heuristic_reader` first-`*_class` pick) to find the bound field per panel source card, reads that
field's `outputs.summary_fields_vocabulary`, and asserts the map's keys and the skill's KNOWN-DEFAULTING
ledger PARTITION the live producer vocabulary:

    producer_vocab == keys(_<SKILL>_VALUE_TIERS) ∪ _KNOWN_DEFAULTING[skill]   (disjoint, no stale)

so a NEW/renamed producer token that is neither mapped nor ledgered fails HERE (forcing triage) instead
of silently becoming `absent` in a figure. This is the DETERMINISTIC_BIN_COMPLETENESS pattern (Cat-2 risk
bins) generalized to the Cat-1 `_*_VALUE_TIERS` family. Guards A/C anchor the SAME principle to the
resolver / nomination-gate producer vocabularies; Cat-3/4/5 frozensets + Cat-6 `*_SIGNAL` claim maps +
the field-level declares-consumed sibling guard remain follow-ons (issue #1644).

VERDICT-INERT + BYTE-STABLE: these maps feed only the `--figures` sub-group panel (never the spine,
claim_vector, rules or narrator), and this is a test-only addition — no map is edited, so `subgroup_signals`
output is byte-identical. _KNOWN_DEFAULTING PINS the CURRENT fleet state; it is a ratchet, NOT an
endorsement that the default tier is correct: of its 309 entries, 257 invert a present signal to `absent`
(real under-reads tracked by the piecewise issues above; the other 52 route to UNMEASURED abstention or a
non-absent tier and are already handled). Closing each piecewise instance moves its
tokens from _KNOWN_DEFAULTING into the skill's map. Two skills already carry a COMPLETE map (empty
ledger): cis-feature-coherence (#1595) and target-intrinsic (#1550).

S3-free; skips cleanly when target-contracts is not checked out (as Guard A/B already do).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SKILLS_ROOT = Path(__file__).resolve().parent.parent
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common.paths import target_contracts_root  # noqa: E402
from _skills_common.subgroup_derivation import _SIGNAL_KEY  # noqa: E402
from _test_support import load_run_py  # noqa: E402

CONTRACTS = target_contracts_root()

# (skill dir, _*_VALUE_TIERS var, reader-spec var or None). The reader-spec skills (target-intrinsic's
# full {class,n,label} spec, functional-requirement's 1-entry confidence-only spec) bind their class
# field explicitly; the other 9 fall to derive_subgroups' `_heuristic_reader` (first `*_class` field).
_SKILLS = [
    ("cis-feature-coherence", "_CIS_VALUE_TIERS", None),
    ("on-target-safety-liability", "_SAFETY_VALUE_TIERS", None),
    ("mechanism-and-pharmacology", "_MECHANISM_VALUE_TIERS", None),
    ("differentiation-landscape", "_DIFFERENTIATION_VALUE_TIERS", None),
    ("tractability-small-molecule", "_TRACT_VALUE_TIERS", None),
    ("surface-modality-fit", "_SURFACE_VALUE_TIERS", None),
    ("genomic-alteration-profile", "_GENOMIC_VALUE_TIERS", None),
    ("immune-context", "_IMMUNE_VALUE_TIERS", None),
    ("combination-and-vulnerability", "_COMBO_VALUE_TIERS", None),
    ("tumor-selectivity", "_SELECTIVITY_VALUE_TIERS", None),
    ("functional-requirement", "_FR_VALUE_TIERS", "_FR_SUBGROUP_READER"),
    ("target-intrinsic", "_TARGET_INTRINSIC_VALUE_TIERS", "_TARGET_INTRINSIC_SUBGROUP_READER"),
]

# Cards whose RUNTIME-emitted summary dict orders a DIFFERENT `*_class` field first than the card
# contract's `summary_fields` list does — so `_heuristic_reader` (which reads the runtime dict) binds
# the field named here, NOT the contract-order first `*_class`. Validated by replicating the heuristic
# over all 504 corpus evidence packages (2026-09-27): these are the only two panel-source divergences,
# and the guard must audit the field ACTUALLY bound at runtime or it checks the wrong vocabulary.
_RUNTIME_BOUND_OVERRIDE = {
    "genomic-event-model-match": "patient_functional_state_class",  # contract-order picks event_correspondence_class
    "tumor-vs-normal-selectivity": "selectivity_allgene_percentile_class",  # contract-order picks selectivity_class
}


# The currently-unmapped producer tokens per skill, pinned at the CI target-contracts SHA
# (28e992cd09a178fd36439fe65506315f2a614e38) with the exact binding this guard reproduces. This is the
# RATCHET, not an endorsement: each token here falls through _*_VALUE_TIERS to default_classify, and the
# per-skill comment records how many of them invert a PRESENT producer signal to `absent` (a real
# under-read tracked by the piecewise issues #1550/#1559/#1563/#1587/#1595 and the #1644 worklist). The
# guard asserts this set EQUALS (live producer vocab − map keys), so it cannot silently drift: a new or
# renamed producer token that is neither mapped nor listed here fails the partition and forces triage,
# and mapping a token without deleting it here (or deleting a vocab token without pruning here) also fails.
# To close a piecewise instance: add the token to the skill's _*_VALUE_TIERS map AND delete it here.
_KNOWN_DEFAULTING = {
    "cis-feature-coherence": frozenset(),  # map is COMPLETE against its live card vocab (#1595)
    # on-target-safety-liability: 34 unmapped (29 invert a present signal to `absent` = under-reads)
    "on-target-safety-liability": frozenset(
        {
            "broad_normal_protein",
            "broadly_dependent",
            "common_essential",
            # #1794 (card 3.1.0): anchor-unreachable well-powered pan-essential — LEDGERED beside its
            # sibling common_essential (mapping only the new token would rank an UNVERIFIED
            # pan-essential above the verified one in the panel); promoting the whole family out of
            # default_classify is the #1644 worklist's call, not this wiring's.
            "common_essential_unanchored",
            "common_essential_underpowered",
            "critical_organ_liability",
            "data_unavailable",
            "direction_unresolved",
            "dosage_sufficient",
            "germline_pathogenic_low_review",
            "high_intolerance",
            "indeterminate",
            "insufficient",
            "lethal_ko",
            "mild_phenotype",
            "moderate_intolerance",
            "moderate_normal_breadth",
            "moderate_normal_expression",
            "moderate_normal_protein",
            "no_clingen_entry",
            "no_clinvar_entry",
            "no_pathogenic_signal",
            "no_phenotype",
            "non_dependent",
            "non_dependent_underpowered",
            "not_detected_in_normal",
            "not_detected_in_normal_protein",
            "protective",
            "restricted_normal",
            "restricted_normal_protein",
            "severe_organ_phenotype",
            "somatic_only",
            "tolerant",
            "unresolved",
        }
    ),
    # mechanism-and-pharmacology: 30 unmapped (26 invert a present signal to `absent` = under-reads)
    "mechanism-and-pharmacology": frozenset(
        {
            "arm_level_cn",
            "bidirectionally_perturbed",
            "cross_gene_copy_number",
            "cross_gene_expression",
            "data_unavailable",
            "fusion",
            "lineage",
            "metabolomics",
            "methylation_tss",
            "mol_signature",
            "ms_protein",
            "msi_status",
            "not_measured",
            "oncokb_gof",
            "oncokb_lof",
            "own_copy_number",
            "own_expression",
            "own_mut_damaging",
            "own_mut_hotspot",
            "paralog_dep",
            "partial",
            "phospho_active",
            "phospho_low",
            "phospho_not_detected",
            "profiled",
            "rppa_protein",
            "sparse",
            "sv_gene",
            "unpredictable",
            "weakly_perturbed",
        }
    ),
    # differentiation-landscape: 7 unmapped (7 invert a present signal to `absent` = under-reads)
    "differentiation-landscape": frozenset(
        {
            "alteration_mutated_better_survival",
            "alteration_mutated_worse_survival",
            "no_subtype_survival_association",
            "stem_high",
            "stem_intermediate",
            "stem_low",
            "subtype_stratifies_survival",
        }
    ),
    # tractability-small-molecule: 23 unmapped (20 invert a present signal to `absent` = under-reads)
    "tractability-small-molecule": frozenset(
        {
            "af_only",
            "category_only",
            "clinically_actionable",
            "clinically_active",
            "crispr_confirmed_engagement",
            "data_unavailable",
            "discordant_off_target_likely",
            "druggable_genome",
            "interaction_only",
            "no_compounds_found",
            "no_known_drug_evidence",
            "no_measured_activity",
            "none",
            "partial",
            "plausible_untested",
            "potent_activity",
            "precedented_degradable",
            "rnai_confirmed_engagement",
            "strong",
            "thin_evidence",
            "tool_compound_only",
            "unfavorable_location",
            "weakly_active",
        }
    ),
    # surface-modality-fit: 62 unmapped (50 invert a present signal to `absent` = under-reads)
    "surface-modality-fit": frozenset(
        {
            "LOW_LIABILITY",
            "MODERATE_LIABILITY",
            "NOT_EXPRESSED",
            "af_only",
            "avidity_unconfirmed",
            "beta_barrel",
            "broad_normal_expression",
            "broadly_low",
            "cd_antigen",
            "cd_molecule",
            "clean_window",
            "confirmed",
            "data_unavailable",
            "enzyme_surface",
            "established_io_backbone",
            "exon_heterogeneity_flag",
            "gpcr",
            "growth_factor_receptor",
            "high_surface_on_normal_immune",
            "immune_receptor",
            "indeterminate",
            "insufficient_paired_tumors",
            "intermediate_presentation",
            "isoform_dependent_undefined",
            "kinase_surface",
            "low_surface_on_normal_immune",
            "malignant_subset_detected",
            "microenvironment_dominant",
            "modality_ambiguous",
            "moderate_surface_on_normal_immune",
            "narrow_window",
            "no_positive_epitopes",
            "no_selective_pair",
            "none",
            "not_detected_in_normal",
            "not_expressed_in_cohort",
            "not_in_product",
            "not_observed",
            "not_selective",
            "not_shed_membrane_retained",
            "not_surface",
            "not_surface_density_whole_cell_estimate",
            "not_surface_detected_normal_immune",
            "other_surface",
            "partial",
            "partial_proxy",
            "poor_proxy",
            "presented_not_tcell_confirmed",
            "restricted_normal_expression",
            "restricted_presentation",
            "same_cell_coordinated",
            "same_cell_independent",
            "same_cell_mutually_exclusive",
            "secretome_proxy_shed",
            "selective_but_broad_tissue_liability",
            "single_pass_type_1",
            "single_pass_type_2",
            "single_pass_type_other",
            "strong",
            "uniform_gene_window",
            "unmeasured",
            "very_low",
        }
    ),
    # genomic-alteration-profile: 63 unmapped (56 invert a present signal to `absent` = under-reads)
    "genomic-alteration-profile": frozenset(
        {
            "amp_expr_negative_more_dependent",
            "arm_level_cn",
            "bottom_decile",
            "concordant_non_dependent",
            "cross_gene_copy_number",
            "cross_gene_expression",
            "curated_cancer_gene",
            "data_unavailable",
            "discordant",
            "fusion",
            "fusion_negative_strongly_dependent",
            "inframe_indel",
            "insufficient",
            "insufficient_amp_expr_rate",
            "insufficient_amplification_rate",
            "insufficient_fusion_rate",
            "insufficient_mutant_or_drug_data",
            "insufficient_mutation_rate",
            "lineage",
            "lof",
            "mave_assayed",
            "mave_well_characterized",
            "metabolomics",
            "methylation_tss",
            "mid",
            "mixed",
            "mixed_clonality",
            "mol_signature",
            "ms_protein",
            "msi_status",
            "mutant_drug_resistant",
            "neutral_strongly_dependent",
            "no_on_target_compound",
            "no_registered_event",
            "none",
            "not_amp_expr_stratified",
            "not_assayed",
            "not_cn_stratified",
            "not_drug_response_stratified",
            "not_fusion_stratified",
            "not_mutation_stratified",
            "oncokb_gof",
            "oncokb_lof",
            "own_copy_number",
            "own_expression",
            "own_mut_damaging",
            "paralog_dep",
            "predictive_biomarker",
            "predominantly_monoallelic",
            "predominantly_subclonal",
            "profiled",
            "promiscuous_amplicon_fusion",
            "recurrent_biallelic_inactivation",
            "recurrent_fusion_driver",
            "rppa_protein",
            "single_consortium_only",
            "splice_event_off_indication",
            "sporadic_fusion",
            "sv_gene",
            "underpowered",
            "unpredictable",
            "vus",
            "wt_strongly_dependent",
        }
    ),
    # immune-context: 18 unmapped (18 invert a present signal to `absent` = under-reads)
    "immune-context": frozenset(
        {
            "caf_broadly_detected",
            "caf_low",
            "endothelial_niche_colocalized",
            "higher_in_nonresponders",
            "higher_in_responders",
            "immune_niche_colocalized",
            "myeloid_broadly_detected",
            "myeloid_low",
            "myeloid_subset_detected",
            "no_ici_association",
            "no_spatial_preference",
            "normal_epithelium_adjacent",
            "other_niche_colocalized",
            "stromal_niche_colocalized",
            "til_high",
            "til_intermediate",
            "til_low",
            "underpowered",
        }
    ),
    # combination-and-vulnerability: 4 unmapped (2 invert a present signal to `absent` = under-reads)
    "combination-and-vulnerability": frozenset(
        {
            "corroborated_multi_consortium",
            "no_cross_consortium_signal",
            "not_screened_off_panel",
            "single_consortium_corroboration",
        }
    ),
    # tumor-selectivity: 39 unmapped (29 invert a present signal to `absent` = under-reads)
    "tumor-selectivity": frozenset(
        {
            "LOW_LIABILITY",
            "MODERATE_LIABILITY",
            "NOT_EXPRESSED",
            "bottom_decile",
            "broadly_low",
            "clean_window",
            "data_unavailable",
            "endothelial_niche_colocalized",
            "enriched_subset",
            "immune_niche_colocalized",
            "malignant_subset_detected",
            "microenvironment_dominant",
            "mid",
            "minimally_enriched",
            "moderate_normal_protein",
            "modest_down",
            "narrow_window",
            "no_spatial_preference",
            "normal_epithelium_adjacent",
            "not_detected_in_normal_protein",
            "not_enriched",
            "not_expressed_in_cohort",
            "not_significant",
            "not_surface_density_whole_cell_estimate",
            "other_niche_colocalized",
            "restricted_normal_protein",
            "small_effect",
            "stromal_niche_colocalized",
            "strong_down",
            "strong_up",
            "tme_enriched_protein",
            "tme_enriched_rna",
            "top_1pct",
            "top_decile",
            "tumour_enriched_protein",
            "tumour_present_no_compartment_preference",
            "underpowered",
            "unmeasured",
            "very_low",
        }
    ),
    # functional-requirement: 32 unmapped (23 invert a present signal to `absent` = under-reads).
    # #1550: pan_organoid_essential / rare_organoid_dependency / not_organoid_dependent moved OUT of
    # this ledger into _FR_VALUE_TIERS (the phantom-token fix); they are no longer defaulting.
    "functional-requirement": frozenset(
        {
            "broadly_dependent",
            "broadly_lineage_dependent",
            "common_essential",
            # #1794 (card 3.1.0): anchor-unreachable well-powered pan-essential — LEDGERED beside its
            # sibling common_essential (same measured dependency magnitude, missing corroboration only;
            # the family's promotion out of default_classify belongs to the #1644 worklist).
            "common_essential_unanchored",
            "common_essential_underpowered",
            "crispr_confirmed_engagement",
            "data_unavailable",
            "discordant_off_target_likely",
            "insufficient_paired_models",
            "insufficient_partner_deficient_rate",
            "mixed_engagement",
            "no_correlation",
            "no_lineage_enrichment",
            "non_dependent_underpowered",
            "not_partner_stratified",
            "partially_assayed",
            "partner_conditional_moderately_dependent",
            "partner_conditional_strongly_dependent",
            "partner_neutral_strongly_dependent",
            "poorly_modeled",
            "positive_anomaly",
            "protein_predicts_dependency",
            "rnai_confirmed_engagement",
            "single_consortium_only",
            "strongly_concordant_dependent",
            "strongly_concordant_non_dependent",
            "thin_evidence",
            "well_modeled_off_lineage",
            # genomic-event-model-match::patient_functional_state_class (#948, TC PR#949 declared the
            # vocab). These are patient functional-STATE calls (tumor-suppressor biallelic-inactivation
            # prevalence), re-emitted verbatim from functional-gene-state's headline. They are NOT
            # functional-REQUIREMENT (dependency) magnitude signals: recurrent biallelic inactivation of
            # a tumor suppressor is loss-of-function, the opposite of a realized dependency, so none maps
            # to a strong/moderate/weak DEPENDENCY tier — genomic-alteration-profile tiers them under its
            # ALTERATION lens (rarely_altered=weak, sporadic=moderate), which does not transfer here.
            # FR's own reviewed field_disposition marks this field role=context ("qualifier not an
            # independent signal; no exact reader; the correspondence class integrates it"), and FR
            # consumes only event_correspondence_class from this card. The `absent` default is therefore
            # correct (no dependency signal), so these are LEDGERED not mapped. Verdict-inert: the
            # subgroup panel is --figures-gated and this field is a context qualifier, never a spine input.
            "predominantly_monoallelic",
            "rarely_altered",
            "recurrent_biallelic_inactivation",
            "sporadic_biallelic_inactivation",
        }
    ),
    "target-intrinsic": frozenset(),  # map is COMPLETE against its live card vocab (#1550)
}


def _norm(tokens):
    """Lowercase-normalise a token iterable — mirrors make_value_classifier (lowercases map keys) and
    default_classify (lowercases the value), so the partition compares apples to apples."""
    return {str(t).lower() for t in tokens}


def _card_contract(card_id):
    p = CONTRACTS / "cards" / f"{card_id}.card.yaml"
    if not p.exists():
        return None
    try:
        return yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError:
        return None


def _binding_measurement_types(skill):
    """The measurement_types the skill's question_hierarchy binds into sub-group signals."""
    hier_p = SKILLS_ROOT / skill / "question_hierarchy.yaml"
    hier = yaml.safe_load(hier_p.read_text()) or {}
    mts = set()
    for sg in hier.get("sub_groups", []):
        for q in sg.get("questions", []):
            for mt in q.get("measurement_types", []):
                mts.add(mt)
    return mts


def _heuristic_class_field(fields):
    """Contract-order proxy for derive_subgroups' `_heuristic_reader`: the first `*_class` field, else
    the first field matching `_SIGNAL_KEY`. `_heuristic_reader` reads the RUNTIME summary dict, whose key
    order matches the card contract's `summary_fields` for every panel source EXCEPT the two in
    `_RUNTIME_BOUND_OVERRIDE` (validated over the 504-package corpus, 2026-09-27)."""
    cls = next((f for f in fields if f.endswith("_class")), None)
    if cls:
        return cls
    return next((f for f in fields if _SIGNAL_KEY.search(f)), None)


def _panel_sources(skill, run, reader_var):
    """Reproduce derive_subgroups' per-source-card binding against the pinned contracts.

    Yields (card_id, measurement_type, bound_field, [producer tokens]) for each card the skill would
    read into a whole-cohort sub-group signal: card measurement_type is bound by the hierarchy, tier is
    not `subtype`, and the bound `*_class` field (explicit reader spec, else the heuristic pick with the
    two runtime overrides) has a summary_fields_vocabulary entry.
    """
    reader = getattr(run, reader_var) if reader_var else None
    mts = _binding_measurement_types(skill)
    for cid in getattr(run, "CARDS", []):
        c = _card_contract(cid)
        if c is None:
            continue
        mt = c.get("measurement_type")
        if mt not in mts or c.get("tier") == "subtype":
            continue
        outputs = c.get("outputs") or {}
        fields = [f for f in (outputs.get("summary_fields") or []) if isinstance(f, str)]
        vocabmap = outputs.get("summary_fields_vocabulary") or {}
        if reader is not None and mt in reader:
            spec = reader[mt]
            if not spec:  # falsy spec = confidence-only card, not a signal source (matches derive_subgroups)
                continue
            bound = spec.get("class")
        else:
            bound = _RUNTIME_BOUND_OVERRIDE.get(cid) or _heuristic_class_field(fields)
        if not bound:
            continue
        yield cid, mt, bound, [str(v) for v in (vocabmap.get(bound) or [])]


def _producer_vocab(skill, run, reader_var):
    """Union (lowercased) of every panel-source bound field's producer vocabulary for the skill."""
    vocab = set()
    for _cid, _mt, _bound, toks in _panel_sources(skill, run, reader_var):
        vocab |= _norm(toks)
    return vocab


# The monorepo carries target-contracts IN-REPO as contracts/ (SK#2063); CI always has it, so this
# guard must always RUN on CI. The skip path exists only for a local dev checkout that has somehow
# lost the contracts/ tree — gated on the in-repo path being ABSENT, never on an env var alone, so a
# CI shard (where contracts/cards is always present) can never take it.
_SKIP_NO_CONTRACTS = not (CONTRACTS and (CONTRACTS / "cards").is_dir())
_SKIP_REASON = "target-contracts not checked out; the fleet vocab-exhaustiveness guard is contract-driven"


def test_skills_discovery_floor():
    """Hard cardinality floor: exactly 12 subgroup-panel skills are wired into this guard, each with a
    non-empty producer vocab. This is the #1648 discovery-floor discipline: an accidental truncation of
    _SKILLS (or a skill whose panel-source binding silently resolves to nothing) must fail RED here,
    rather than letting test_value_tiers_partition_producer_vocab partition 0 keys against 0 vocab and
    pass vacuously green. Runs unconditionally (not contracts-gated) for the count; the per-skill
    producer_vocab check requires contracts and is skipped with the rest when absent."""
    assert len(_SKILLS) == 12, (
        f"expected exactly 12 subgroup-panel skills wired into the fleet vocab-exhaustiveness guard, "
        f"got {len(_SKILLS)}: {[s[0] for s in _SKILLS]}. A change here is a discovery-floor regression "
        f"unless this guard's cardinality is being deliberately updated alongside it."
    )
    if _SKIP_NO_CONTRACTS:
        pytest.skip(_SKIP_REASON)
    for skill, tiervar, readervar in _SKILLS:
        run = load_run_py(str(SKILLS_ROOT / skill), f"_vocabguard_floor_{skill.replace('-', '_')}")
        vocab = _producer_vocab(skill, run, readervar)
        assert vocab, (
            f"{skill}: producer_vocab resolved EMPTY — a binding/resolution regression would make the "
            f"partition test below pass vacuously (0 keys ⊇ 0 vocab). Check the skill's panel-source "
            f"card binding (question_hierarchy measurement_types, reader spec, or card contracts)."
        )


@pytest.mark.skipif(_SKIP_NO_CONTRACTS, reason=_SKIP_REASON)
@pytest.mark.parametrize("skill,tiervar,readervar", _SKILLS, ids=[s[0] for s in _SKILLS])
def test_value_tiers_partition_producer_vocab(skill, tiervar, readervar):
    """map keys + KNOWN_DEFAULTING PARTITION the live producer vocabulary — no gap, no overlap, no stale.

    (producer_vocab − map_keys) must EQUAL _KNOWN_DEFAULTING[skill]:
      * gap   (unmapped token not ledgered)  → a NEW/renamed producer token silently reading `absent`;
      * stale (ledgered token no longer unmapped) → the map grew or the vocab shrank, ratchet not pruned.
    map_keys and _KNOWN_DEFAULTING must be DISJOINT (a token cannot be both mapped and known-defaulting).
    Map keys MAY exceed the current vocab (a map can pre-declare tokens not yet emitted), so this is a
    partition of the PRODUCER vocab, not of the map.
    """
    run = load_run_py(str(SKILLS_ROOT / skill), f"_vocabguard_{skill.replace('-', '_')}")
    keys = _norm(getattr(run, tiervar).keys())
    ledger = _norm(_KNOWN_DEFAULTING[skill])

    overlap = keys & ledger
    assert not overlap, (
        f"{skill}: {sorted(overlap)} are BOTH in {tiervar} and _KNOWN_DEFAULTING — a mapped token must "
        f"be deleted from the ledger (it is no longer defaulting)."
    )

    producer = _producer_vocab(skill, run, readervar)
    unmapped = producer - keys
    gap = unmapped - ledger
    stale = ledger - unmapped
    assert not gap, (
        f"{skill}: producer tokens {sorted(gap)} are neither in {tiervar} nor _KNOWN_DEFAULTING. They "
        f"currently fall through to default_classify (likely `absent`). Either MAP them to the correct "
        f"tier in {tiervar}, or (if the default tier is genuinely right) add them to "
        f"_KNOWN_DEFAULTING['{skill}'] with a note. Do NOT silently leave them — that is the under-read "
        f"this guard exists to catch (#1644)."
    )
    assert not stale, (
        f"{skill}: _KNOWN_DEFAULTING['{skill}'] lists {sorted(stale)} which are no longer unmapped "
        f"producer tokens (mapped now, or dropped from the card vocabulary). Prune them from the ledger."
    )


@pytest.mark.skipif(_SKIP_NO_CONTRACTS, reason=_SKIP_REASON)
@pytest.mark.parametrize("card_id,expected_field", sorted(_RUNTIME_BOUND_OVERRIDE.items()))
def test_runtime_bound_override_is_a_real_load_bearing_field(card_id, expected_field):
    """Keep each _RUNTIME_BOUND_OVERRIDE honest against contract drift. An override redirects the guard
    from the contract-order `*_class` pick to the field the RUNTIME summary actually binds first, so it
    must name (a) a real `*_class` field the card declares in summary_fields (typo/rename guard) that
    (b) is NOT what the contract-order heuristic already picks (else the override is redundant and should
    be deleted). It intentionally does NOT require a declared summary_fields_vocabulary: a bound field may
    lack one (e.g. genomic-event-model-match.patient_functional_state_class), which the partition test
    then cannot audit — that undeclared-vocab gap is a separate contract-completeness follow-on, not this
    guard's Cat-1 map-exhaustiveness concern."""
    c = _card_contract(card_id)
    assert c is not None, f"{card_id}: card contract not found under the pinned target-contracts tree"
    outputs = c.get("outputs") or {}
    fields = [f for f in (outputs.get("summary_fields") or []) if isinstance(f, str)]
    assert expected_field.endswith("_class"), f"{card_id}: override {expected_field!r} is not a *_class field"
    assert expected_field in fields, (
        f"{card_id}: override field {expected_field!r} is not declared in summary_fields "
        f"(declared: {fields}) — the override is stale (field renamed/removed)."
    )
    contract_pick = _heuristic_class_field(fields)
    assert contract_pick != expected_field, (
        f"{card_id}: contract-order now picks {expected_field!r} on its own — the "
        f"_RUNTIME_BOUND_OVERRIDE entry is redundant and should be removed."
    )


@pytest.mark.skipif(_SKIP_NO_CONTRACTS, reason=_SKIP_REASON)
def test_guard_has_teeth():
    """Mutation check: an injected NEW producer token that is neither mapped nor ledgered MUST be caught.

    Guards A/B taught us an all-empty ledger makes the partition vacuously green (a derived fixture that
    can never fail); here the ledger is non-empty and computed LIVE, but this proves the gap arm actually
    fires — feed a synthetic producer vocab carrying an un-accounted token and assert the partition logic
    flags it, so the real test above cannot pass merely because the arithmetic is inert."""
    keys = _norm({"strong_dependency", "moderate_dependency"})
    ledger = _norm({"data_unavailable"})
    producer = keys | ledger | {"brand_new_producer_token"}
    unmapped = producer - keys
    gap = unmapped - ledger
    assert gap == {"brand_new_producer_token"}, "partition gap arm failed to catch an un-accounted token"
