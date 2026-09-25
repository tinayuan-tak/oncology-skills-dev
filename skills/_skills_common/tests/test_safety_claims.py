"""Unit tests for on-target-safety-liability's claim vector (skills/_skills_common/safety_claims.py),
the FIFTH concrete over claim_vector_core. Pins the INVERSE-valence LIABILITY tiers (strong = concern,
tolerant = absent, protective = negative) + the citable atoms + the mutant-selective-GoF conditioning
conflict. Pure over a headline dict + card summaries — no S3."""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.safety_claims import safety_claim_vector  # noqa: E402


def _headline(**over):
    h = {
        "constraint_class": "highly_constrained",
        "pli_score": 0.99,
        "loeuf_score": 0.21,
        "obs_lof_count": 2,
        "exp_lof_count": 40.0,
        "burden_safety_class": "lof_risk_phenotype",
        "burden_min_pvalue": 3e-9,
        "burden_top_disease": "cardiomyopathy",
        "dosage_sensitivity_class": "autosomal_dominant_loss",
        "germline_inheritance_mode": "dominant",
        "clinvar_pathogenic_class": "germline_pathogenic",
        "clinvar_top_disease": "Noonan",
        "mouse_ko_phenotype_class": "lethal_ko",
        "mouse_ko_top_lethal": "embryonic_lethal",
        "alteration_functional_direction": "loss_of_function",
    }
    h.update(over)
    return h


def _cards():
    return [
        {
            "card_id": "gnomad-lof-constraint",
            "summary": {
                "constraint_class": "highly_constrained",
                "pli_score": 0.99,
                "loeuf_score": 0.21,
                "mis_z_score": 3.1,
                "obs_lof_count": 2,
                "exp_lof_count": 40.0,
            },
        },
        {
            "card_id": "gene-burden-safety",
            "summary": {
                "burden_safety_class": "lof_risk_phenotype",
                "min_pvalue": 3e-9,
                "top_disease": "cardiomyopathy",
            },
        },
        {
            "card_id": "clingen-dosage",
            "summary": {"dosage_sensitivity_class": "autosomal_dominant_loss", "germline_inheritance_mode": "dominant"},
        },
        {
            "card_id": "clinvar-pathogenicity-safety",
            "summary": {"clinvar_pathogenic_class": "germline_pathogenic", "top_disease": "Noonan"},
        },
        {
            "card_id": "mouse-ko-phenotype",
            "summary": {"ko_phenotype_class": "lethal_ko", "top_lethal_label": "embryonic_lethal"},
        },
    ]


def test_liability_tiers_strong_when_constrained():
    vec = safety_claim_vector(_headline(), _cards())
    assert vec["CONSTRAINT"]["signal"] == "strong"  # highly_constrained = strong CONCERN
    assert vec["BURDEN"]["signal"] == "strong"  # lof_risk_phenotype
    assert vec["DOSAGE"]["signal"] == "strong"  # autosomal_dominant_loss
    assert vec["CLINVAR"]["signal"] == "strong" and vec["MOUSE_KO"]["signal"] == "strong"


def test_inverse_valence_tolerant_is_absent_protective_is_negative():
    vec = safety_claim_vector(
        _headline(
            constraint_class="tolerant",
            burden_safety_class="protective",
            dosage_sensitivity_class="dosage_sufficient",
            mouse_ko_phenotype_class="no_phenotype",
        ),
        _cards(),
    )
    assert vec["CONSTRAINT"]["signal"] == "absent"  # MEASURED LoF-tolerant → not a concern
    assert vec["BURDEN"]["signal"] == "negative"  # protective → measured opposite
    assert vec["DOSAGE"]["signal"] == "absent"
    assert vec["MOUSE_KO"]["signal"] == "absent"


def test_gap_is_unmeasured_not_absent():
    vec = safety_claim_vector(_headline(constraint_class="indeterminate"), _cards())
    assert vec["CONSTRAINT"]["signal"] == "unmeasured"  # gap ≠ measured-tolerant


def test_atoms_present_and_citable():
    vec = safety_claim_vector(_headline(), _cards())
    a = vec["CONSTRAINT"]["evidence_atom"]
    assert a["cite"]["card_id"] == "gnomad-lof-constraint"
    assert a["values"]["pli_score"] == 0.99 and a["values"]["loeuf_score"] == 0.21
    assert a["entity"]["valence"] == "liability"
    assert vec["BURDEN"]["evidence_atom"]["values"]["min_pvalue"] == 3e-9


def test_mutant_selective_gof_conditions_constraint_conflict():
    # activating-GoF mechanism → the WT-constraint concern is flagged as MODALITY-CONDITIONAL (a conflict
    # tension pointing at the per-modality safety verdict), tier kept. The scalar downgrade was retired
    # (safety.resolver 2.0.0); the conflict must NOT claim the scalar verdict was downgraded.
    vec = safety_claim_vector(_headline(alteration_functional_direction="activating"), _cards())
    assert vec["CONSTRAINT"]["signal"] == "strong"  # tier unchanged (this is the SIGNAL)
    conflict = vec["CONSTRAINT"]["conflict"] or ""
    assert "MODALITY-CONDITIONAL" in conflict
    assert "NOT downgraded" in conflict  # scalar verdict is the raw concern


def test_gof_driver_flags_germline_legs_as_not_lof_corroboration_993():
    # #993 pt2: for an activating (GoF) driver the burden/dosage/clinvar germline legs are GoF-syndrome-
    # associated (RASopathy/Noonan/activating-mosaic), NOT WT-LoF-intolerance — each carries a "do NOT
    # count as LoF-corroboration / MODALITY-CONDITIONAL" conflict. Tiers are UNCHANGED (verdict-inert;
    # the scalar safety verdict is the resolver's raw concern).
    vec = safety_claim_vector(_headline(alteration_functional_direction="activating"), _cards())
    for ax in ("BURDEN", "DOSAGE", "CLINVAR"):
        assert vec[ax]["signal"] == "strong"  # tier byte-stable
        conflict = vec[ax]["conflict"] or ""
        assert "activating (GoF)" in conflict and "NOT" in conflict
        assert "NOT downgraded" in conflict


def test_lof_driver_germline_legs_have_no_gof_caveat_993():
    # a genuine LoF target (the default): NO GoF direction caveat on the germline legs.
    vec = safety_claim_vector(_headline(alteration_functional_direction="loss_of_function"), _cards())
    for ax in ("BURDEN", "DOSAGE", "CLINVAR"):
        assert not (vec[ax]["conflict"] or "")


def test_impc_viability_surfaced_when_coarse_class_is_a_gap_1001():
    # #1001: the coarse mouse_ko_phenotype_class reads a gap (insufficient / no_phenotype) but the IMPC
    # preweaning screen recorded a lethal call → surface it + flag the COVERAGE GAP. Tier stays as the
    # coarse class (NOT promoted — the verdict-moving promotion is deferred pending a panel backtest).
    vec = safety_claim_vector(
        _headline(mouse_ko_phenotype_class="insufficient", impc_viability_class="lethal_preweaning"),
        _cards(),
    )
    mk = vec["MOUSE_KO"]
    assert "IMPC-viability=lethal_preweaning" in mk["evidence"]
    assert "COVERAGE GAP" in (mk["conflict"] or "")
    assert mk["signal"] == "unmeasured"  # insufficient -> unmeasured; NOT promoted (verdict-inert)


def test_impc_viable_adds_no_mouseko_gap_note_1001():
    # a 'viable' / 'unmeasured' IMPC read adds no evidence line and no gap note.
    vec = safety_claim_vector(_headline(impc_viability_class="viable"), _cards())
    assert "IMPC-viability" not in (vec["MOUSE_KO"]["evidence"] or "")


def test_atoms_absent_without_cards():
    vec = safety_claim_vector(_headline(), [])
    for ax in ("CONSTRAINT", "BURDEN", "DOSAGE", "CLINVAR", "MOUSE_KO"):
        assert "evidence_atom" not in vec[ax], f"{ax} atom present with no source card"


# ── 2026-09-04 signal-surfacing: PHARMACOVIGILANCE context axis + rich CLINVAR/MOUSE_KO sub-fields ──
def test_pharmacovigilance_axis_is_verdict_inert_context():
    # a black-box-warned target-engaging drug is a STRONG clinical liability SIGNAL, but corroboration is
    # CAPPED (never `high`) and the confound rides in the conflict slot — it ORIENTS, never a resolver HOLD.
    vec = safety_claim_vector(
        _headline(
            drug_warning_class="black_box_warned",
            drug_warning_has_black_box=True,
            drug_warning_toxicity_classes=["hepatotoxicity", "cardiotoxicity"],
            onsides_example_boxed_warning_terms="Hepatotoxicity",
        ),
        _cards(),
    )
    p = vec["PHARMACOVIGILANCE"]
    assert p["signal"] == "strong"
    # `single_arm`: the reading rests on ONE source (the drug-warning label lane). The old `moderate` was a
    # CAP applied for the on/off-target confound — but a cap expresses distrust of an arm, and the arm count
    # is a separate fact. The confound is already carried, precisely and unambiguously, in the `conflict`
    # slot asserted two lines down; encoding it a second time as a corroboration tier made the axis read as
    # "partly agreed with something", which no second source ever did.
    assert p["corroboration"] == "single_arm"
    assert "hepatotoxicity" in p["evidence"]  # the rich toxicity CLASSES the capsule carried
    assert "CONFOUNDED" in (p["conflict"] or "")  # confound flagged, not the verdict
    assert "CONTEXT" in vec["_disclaimer"]  # doubly-inert note present


def test_pharmacovigilance_measured_absent_vs_unmeasured_gap():
    # engaging drug(s) exist but NONE warned = MEASURED absent; no engaging drug at all = coverage gap.
    assert (
        safety_claim_vector(_headline(drug_warning_class="no_warning"), _cards())["PHARMACOVIGILANCE"]["signal"]
        == "absent"
    )
    gap = safety_claim_vector(_headline(drug_warning_class="no_targeted_drug"), _cards())["PHARMACOVIGILANCE"]
    assert gap["signal"] == "unmeasured" and gap["corroboration"] == "unmeasured"


def test_pharmacovigilance_onsides_fallback_when_drug_warning_thin():
    # a boxed-warning ADE profile is a strong clinical signal even when the OT drug-warning leg is thin.
    v = safety_claim_vector(_headline(drug_warning_class="no_targeted_drug", onsides_has_boxed_warning=True), _cards())
    assert v["PHARMACOVIGILANCE"]["signal"] == "moderate"


def test_clinvar_evidence_surfaces_confident_variant_count():
    vec = safety_claim_vector(_headline(clinvar_n_pathogenic_germline_confident=109), _cards())
    assert "confident-germline-pathogenic-variants=109" in vec["CLINVAR"]["evidence"]
    # a zero/absent count must NOT clutter the evidence
    assert (
        "confident-germline-pathogenic-variants"
        not in safety_claim_vector(_headline(clinvar_n_pathogenic_germline_confident=0), _cards())["CLINVAR"][
            "evidence"
        ]
    )


def test_mouseko_evidence_surfaces_organ_systems():
    vec = safety_claim_vector(
        _headline(mouse_ko_organ_systems=["hematopoietic system phenotype", "cardiovascular system phenotype"]),
        _cards(),
    )
    ev = vec["MOUSE_KO"]["evidence"]
    assert "organ-systems=" in ev and "hematopoietic system phenotype" in ev


def test_pharmacovigilance_atom_cites_drug_warning_card():
    cards = _cards() + [
        {
            "card_id": "drug-warning-safety",
            "summary": {
                "drug_warning_class": "black_box_warned",
                "has_black_box": True,
                "toxicity_classes": ["hepatotoxicity"],
                "warning_types": ["black box warning"],
                "n_targeted_warned_drugs": 8,
            },
        }
    ]
    a = safety_claim_vector(_headline(drug_warning_class="black_box_warned"), cards)["PHARMACOVIGILANCE"][
        "evidence_atom"
    ]
    assert a["cite"]["card_id"] == "drug-warning-safety"
    assert a["entity"]["valence"] == "liability"


# ── L2b-3: cross-source normal-tissue safety-liability concordance (SK#1546) ──────────────────────
# A CROSS-SOURCE integration claim over THREE genuinely INDEPENDENT normal-tissue liability lenses:
# GTEx bulk RNA (normal-tissue-liability-gtex.liability_class) × scRNA cell-type-resolved
# (sc-normal-celltype-expression.sc_normal_expression_class) × HPA-IHC protein
# (normal-tissue-liability.essential_tissue_flag). Store the RAW per-source tokens and RE-DERIVE the
# claim in-test — a derived fixture cannot fail; the tokens are the irreproducible inputs. The claim
# reads the cards directly (not the headline), so it is exercised through the same
# safety_claim_vector(headline, cards) seam without touching the seven verdict-liability axes.
_LIAB_KEY = "normal_liability_concordance"


def _liab_cards(gtex="critical_organ_liability", sc="HIGH_LIABILITY", hpa="present"):
    """Card set carrying the three normal-tissue source tokens. Any of gtex/sc/hpa=None OMITS that
    field (source data-absence path); an abstain sentinel (data_unavailable / unknown / MODERATE_LIABILITY)
    is passed as-is and must NOT resolve into a high/clean bucket."""
    cards = []
    if gtex is not None:
        cards.append({"card_id": "normal-tissue-liability-gtex", "summary": {"liability_class": gtex}})
    if sc is not None:
        cards.append({"card_id": "sc-normal-celltype-expression", "summary": {"sc_normal_expression_class": sc}})
    if hpa is not None:
        cards.append({"card_id": "normal-tissue-liability", "summary": {"essential_tissue_flag": hpa}})
    return cards


def test_liab_concordant_high_three_sources_agree():
    # All three lenses flag a normal-tissue liability → concordant_high, corroborated by 3 independent arms.
    claim = safety_claim_vector(
        _headline(), _liab_cards(gtex="broadly_expressed_normal", sc="HIGH_LIABILITY", hpa="present")
    )[_LIAB_KEY]
    assert claim["concordance_class"] == "liability_concordant_high"
    assert claim["corroboration"] == "high"  # >=2 measured arms, all agree
    assert claim["integration_method"] == "explicit_deterministic"  # NO llm_inference: reproducible by contract
    assert claim["source_support"]["agreed_direction"] == "high"
    assert claim["source_support"]["sources_agree"] == ["gtex_bulk_rna", "hpa_ihc_protein", "sc_normal_rna"]
    # Provenance records ALL THREE source properties, recoverable, + an independence note.
    srcs = {s["property"]: s for s in claim["provenance"]["sources"]}
    assert srcs["normal_tissue_liability_rna_bulk"]["fields"]["liability_class"] == "broadly_expressed_normal"
    assert srcs["normal_tissue_liability_rna_singlecell"]["fields"]["sc_normal_expression_class"] == "HIGH_LIABILITY"
    assert srcs["normal_tissue_liability_protein_ihc"]["fields"]["essential_tissue_flag"] == "present"
    assert "independent" in claim["provenance"]["independence_note"].lower()


def test_liab_concordant_low_three_sources_read_clean():
    # All three lenses read clean → concordant_low (agree there is NO normal-tissue liability).
    claim = safety_claim_vector(_headline(), _liab_cards(gtex="restricted_normal", sc="NOT_EXPRESSED", hpa="absent"))[
        _LIAB_KEY
    ]
    assert claim["concordance_class"] == "liability_concordant_low"
    assert claim["corroboration"] == "high"
    assert claim["source_support"]["agreed_direction"] == "clean"


def test_liab_discordant_names_which_source_flags_vs_clean():
    # GTEx bulk-high but scRNA cell-type-resolved clean + HPA clean → assay_discordant; the split is NAMED
    # (which sources flag liability vs read clean), never collapsed. Corroboration degrades to low.
    claim = safety_claim_vector(
        _headline(), _liab_cards(gtex="critical_organ_liability", sc="NOT_EXPRESSED", hpa="absent")
    )[_LIAB_KEY]
    assert claim["concordance_class"] == "liability_assay_discordant"
    assert claim["corroboration"] == "low"
    assert claim["source_support"]["liability_flagged_by"] == ["gtex_bulk_rna"]
    assert claim["source_support"]["read_clean_by"] == ["hpa_ihc_protein", "sc_normal_rna"]
    # symmetric: protein flags, both RNA lenses read clean (transcript-vs-protein discordance)
    claim2 = safety_claim_vector(_headline(), _liab_cards(gtex="restricted_normal", sc="LOW_LIABILITY", hpa="present"))[
        _LIAB_KEY
    ]
    assert claim2["source_support"]["liability_flagged_by"] == ["hpa_ihc_protein"]
    assert claim2["source_support"]["read_clean_by"] == ["gtex_bulk_rna", "sc_normal_rna"]


def test_liab_single_source_only_when_two_arms_are_gaps():
    # HPA resolves, both RNA lenses are admissibility GAPS → single_source_only, naming the RESOLVED arm
    # and carrying its raw call (recoverable); corroboration is single_arm (one measured arm).
    claim = safety_claim_vector(
        _headline(), _liab_cards(gtex="data_unavailable", sc="data_unavailable", hpa="present")
    )[_LIAB_KEY]
    assert claim["concordance_class"] == "liability_single_source_only"
    assert claim["corroboration"] == "single_arm"
    assert claim["source_support"]["resolved_by"] == "hpa_ihc_protein"
    assert claim["source_support"]["resolved_call"] == "present"
    assert claim["source_support"]["resolved_direction"] == "high"


def test_liab_moderate_and_unknown_abstain_not_a_silent_vote():
    # scRNA MODERATE_LIABILITY and HPA `unknown` are ABSTAIN sentinels — they must NOT resolve into a
    # high/clean bucket. Here only GTEx resolves → single_source_only (not a concordance / discordance).
    claim = safety_claim_vector(
        _headline(), _liab_cards(gtex="critical_organ_liability", sc="MODERATE_LIABILITY", hpa="unknown")
    )[_LIAB_KEY]
    assert claim["concordance_class"] == "liability_single_source_only"
    assert claim["source_support"]["resolved_by"] == "gtex_bulk_rna"
    # the abstaining tokens still ride in provenance (recoverable), just don't vote
    srcs = {s["property"]: s for s in claim["provenance"]["sources"]}
    assert (
        srcs["normal_tissue_liability_rna_singlecell"]["fields"]["sc_normal_expression_class"] == "MODERATE_LIABILITY"
    )
    assert srcs["normal_tissue_liability_protein_ihc"]["fields"]["essential_tissue_flag"] == "unknown"


def test_liab_recoverability_round_trip():
    # FIDELITY: the actual per-source VALUES round-trip through provenance, not merely a key. A consumer
    # can reconstruct the discordance purely from the recovered tokens the same way the claim does.
    gtex_tok, sc_tok, hpa_tok = "broadly_expressed_normal", "NOT_EXPRESSED", "absent"
    claim = safety_claim_vector(_headline(), _liab_cards(gtex=gtex_tok, sc=sc_tok, hpa=hpa_tok))[_LIAB_KEY]
    srcs = {s["property"]: s for s in claim["provenance"]["sources"]}
    assert srcs["normal_tissue_liability_rna_bulk"]["fields"]["liability_class"] == gtex_tok
    assert srcs["normal_tissue_liability_rna_singlecell"]["fields"]["sc_normal_expression_class"] == sc_tok
    assert srcs["normal_tissue_liability_protein_ihc"]["fields"]["essential_tissue_flag"] == hpa_tok
    # bulk flags a liability, both cell-type RNA + protein read clean → a discordance, re-derivable from tokens
    assert (gtex_tok in {"critical_organ_liability", "broadly_expressed_normal"}) is True
    assert (sc_tok in {"LOW_LIABILITY", "NOT_EXPRESSED"}) is True
    assert claim["concordance_class"] == "liability_assay_discordant"


def test_liab_is_verdict_inert_no_signal_and_axes_unperturbed():
    # Verdict-INERT: the claim carries NO `signal` key (never a chip, never a tier), and surfacing it must
    # not perturb the seven liability axes / _disclaimer. Toggle ONLY sc_normal_expression_class — a field
    # the safety intracellular_intrinsic verdict path does NOT read (its sc-normal rules are on the surface
    # axis; the veto keys on sc_normal_essential_veto_grade, a DIFFERENT field) — so any axis delta would be
    # a real perturbation, not the L2b-3 claim's.
    base = safety_claim_vector(
        _headline(), _liab_cards(gtex="critical_organ_liability", sc="LOW_LIABILITY", hpa="present")
    )
    toggled = safety_claim_vector(
        _headline(), _liab_cards(gtex="critical_organ_liability", sc="HIGH_LIABILITY", hpa="present")
    )
    # the concordance class DID move with the sc field (discordant → concordant_high) — the claim is live ...
    assert base[_LIAB_KEY]["concordance_class"] == "liability_assay_discordant"
    assert toggled[_LIAB_KEY]["concordance_class"] == "liability_concordant_high"
    # ... but nothing else did:
    claim = toggled[_LIAB_KEY]
    assert "signal" not in claim, "an L2b claim must never carry a signal tier"
    for ax in (
        "CONSTRAINT",
        "BURDEN",
        "DOSAGE",
        "CLINVAR",
        "MOUSE_KO",
        "PAN_ESSENTIAL",
        "NORMAL_TISSUE",
        "_disclaimer",
    ):
        assert toggled[ax] == base[ax], f"surfacing the normal-liability-concordance claim perturbed {ax}"


def test_liab_single_source_mutation_only_degrades_defeating_all_three_erases():
    # M3-vs-M4 reach: killing ONE source's supply may only DEGRADE the read — the concept survives on the
    # surviving arms. ERASING the claim (key omitted) requires defeating ALL THREE supplies.
    three = safety_claim_vector(
        _headline(), _liab_cards(gtex="critical_organ_liability", sc="HIGH_LIABILITY", hpa="present")
    )
    assert three[_LIAB_KEY]["concordance_class"] == "liability_concordant_high"
    # defeat ONE arm → still a 2-source concordance, not erased
    one_gone = safety_claim_vector(_headline(), _liab_cards(gtex="critical_organ_liability", sc=None, hpa="present"))
    assert _LIAB_KEY in one_gone
    assert one_gone[_LIAB_KEY]["concordance_class"] == "liability_concordant_high"
    assert one_gone[_LIAB_KEY]["corroboration"] == "high"  # two arms still agree
    # defeat TWO arms → degrades to single_source_only, still not erased
    two_gone = safety_claim_vector(_headline(), _liab_cards(gtex=None, sc=None, hpa="present"))
    assert _LIAB_KEY in two_gone
    assert two_gone[_LIAB_KEY]["concordance_class"] == "liability_single_source_only"
    # defeat ALL THREE (fields absent) → key omitted (byte-stable erasure)
    all_gone = safety_claim_vector(_headline(), _liab_cards(gtex=None, sc=None, hpa=None))
    assert _LIAB_KEY not in all_gone, "only defeating ALL THREE supplies erases the claim"


def test_liab_omitted_when_no_source_resolves():
    # Byte-stability: the KEY is omitted (not None) unless at least one source resolves.
    assert _LIAB_KEY not in safety_claim_vector(_headline(), [])  # no cards
    assert _LIAB_KEY not in safety_claim_vector(_headline(), _liab_cards(gtex=None, sc=None, hpa=None))
    # all three present but ALL are abstain sentinels → none resolve → omitted
    assert _LIAB_KEY not in safety_claim_vector(
        _headline(), _liab_cards(gtex="data_unavailable", sc="MODERATE_LIABILITY", hpa="unknown")
    )
    # an off-roster / unknown token is treated as unresolved (not a silent liability)
    assert _LIAB_KEY not in safety_claim_vector(
        _headline(), _liab_cards(gtex="some_future_token", sc="data_unavailable", hpa=None)
    )


# ── SK#1582 G3.2: PRESENTATION-SUPPORT fields on the claim (surface-consumption, NOT verdict-routing) ─
# Additive to the existing claim shape (source_support/provenance UNCHANGED). Exactly ONE of
# positive/qualifying is non-null; the encouraging direction is a CLEAN concordance, every other class is
# a qualifying caveat. boundary_sensitive is a deterministic read of corroboration (!= high). None of
# these carry a signal tier / polarity / drives_rule_id — they route nothing.
def test_liab_presentation_concordant_low_is_positive_only():
    claim = safety_claim_vector(_headline(), _liab_cards(gtex="restricted_normal", sc="NOT_EXPRESSED", hpa="absent"))[
        _LIAB_KEY
    ]
    assert claim["positive_signal"] and claim["qualifying_signal"] is None
    assert claim["boundary_sensitive"] is False  # 3 clean arms → corroboration high
    assert "CLEAN" in claim["positive_signal"]["statement"]
    assert claim["positive_signal"]["provenance_ref"] == "source_support.sources_agree"


def test_liab_presentation_qualifying_classes_are_qualifying_only():
    for gtex, sc, hpa, klass in (
        ("critical_organ_liability", "HIGH_LIABILITY", "present", "liability_concordant_high"),
        ("critical_organ_liability", "NOT_EXPRESSED", "absent", "liability_assay_discordant"),
        ("data_unavailable", "data_unavailable", "present", "liability_single_source_only"),
    ):
        claim = safety_claim_vector(_headline(), _liab_cards(gtex=gtex, sc=sc, hpa=hpa))[_LIAB_KEY]
        assert claim["concordance_class"] == klass, klass
        assert claim["positive_signal"] is None and claim["qualifying_signal"], klass


def test_liab_presentation_boundary_sensitive_tracks_corroboration():
    # high corroboration (>=2 agreeing arms) → not boundary-sensitive; a discordance / single arm → yes.
    conc_high = safety_claim_vector(
        _headline(), _liab_cards(gtex="critical_organ_liability", sc="HIGH_LIABILITY", hpa="present")
    )[_LIAB_KEY]
    assert conc_high["corroboration"] == "high" and conc_high["boundary_sensitive"] is False
    disc = safety_claim_vector(
        _headline(), _liab_cards(gtex="critical_organ_liability", sc="NOT_EXPRESSED", hpa="absent")
    )[_LIAB_KEY]
    assert disc["corroboration"] == "low" and disc["boundary_sensitive"] is True
    single = safety_claim_vector(_headline(), _liab_cards(gtex="critical_organ_liability", sc=None, hpa=None))[
        _LIAB_KEY
    ]
    assert single["corroboration"] == "single_arm" and single["boundary_sensitive"] is True


def test_liab_presentation_fields_carry_no_signal_tier():
    # the presentation fields must never introduce a `signal` tier (the L2b verdict-inertness contract).
    claim = safety_claim_vector(
        _headline(), _liab_cards(gtex="critical_organ_liability", sc="HIGH_LIABILITY", hpa="present")
    )[_LIAB_KEY]
    assert "signal" not in claim
    for f in ("positive_signal", "qualifying_signal"):
        v = claim.get(f)
        if v:
            assert set(v) == {"statement", "source", "provenance_ref"}, f
