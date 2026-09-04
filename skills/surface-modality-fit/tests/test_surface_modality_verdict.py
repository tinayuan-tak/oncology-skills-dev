"""surface-modality-fit _verdict coverage (2026-07-20).

surface-modality-fit shipped with NO tests (one of 3 test-less wired skills) AND its
composed adc-tce-modality-fit card can emit fit_class `modality_ambiguous`, which had
no rule + no verdict branch → silent fall-through to insufficient. These tests
pin EVERY fit_class rule_id → verdict mapping (EXHAUSTIVE over the 6-value fit_class
vocabulary), so a future fall-through fails CI rather than silently collapsing.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("smf_run", RUN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


smf = _load()


def _v(rule_id):
    return smf._verdict([{"rule_id": rule_id}])


def test_adc_preferred():
    assert _v("adc-preferred-supportive") == ("adc_preferred", "adc-preferred-supportive")


def test_tce_preferred():
    assert _v("tce-preferred-supportive") == ("tce_preferred", "tce-preferred-supportive")


def test_both_viable():
    assert _v("both-viable-supportive") == ("both_viable", "both-viable-supportive")


def test_neither_viable_killer():
    assert _v("neither-viable-killer") == ("neither_viable", "neither-viable-killer")


def test_isoform_dependent():
    assert _v("isoform-dependent-modality-suppression")[0] == "isoform_dependent_undefined"


def test_modality_ambiguous_is_explicit_not_silent_C2_regression():
    """modality_ambiguous must resolve to an EXPLICIT verdict with a
    driving rule_id — NOT the silent (insufficient, None) fall-through it was before."""
    v, drv = _v("modality-ambiguous-insufficient")
    assert v == "modality_ambiguous"
    assert drv == "modality-ambiguous-insufficient", "must carry provenance, not a bare None"


def test_nothing_fired_is_bare_insufficient():
    # genuinely-nothing-fired is distinct from modality_ambiguous (which names WHY)
    assert smf._verdict([]) == ("insufficient", None)


def test_fit_class_vocabulary_is_exhaustively_handled():
    """EXHAUSTIVENESS guard: every fit_class value the card can emit must map to a
    verdict branch (this is the manual precursor to the exhaustiveness
    validator). If the card gains a new fit_class, this test must be extended — a
    new unhandled value would otherwise silently fall through to insufficient."""
    # the 6 fit_class values (adc-tce-modality-fit.card.yaml summary_fields_vocabulary),
    # each via the rule_id that fires on it:
    fit_class_to_rule = {
        "ADC_preferred": "adc-preferred-supportive",
        "TCE_preferred": "tce-preferred-supportive",
        "both_viable": "both-viable-supportive",
        "neither_viable": "neither-viable-killer",
        "isoform_dependent_undefined": "isoform-dependent-modality-suppression",
        "modality_ambiguous": "modality-ambiguous-insufficient",
    }
    for fit_class, rule_id in fit_class_to_rule.items():
        v, drv = _v(rule_id)
        assert v != "insufficient" or drv is not None, (
            f"fit_class {fit_class} must map to an EXPLICIT verdict (rule {rule_id}), "
            f"not a silent insufficient fall-through")
        assert drv == rule_id


# ---------------------------------------------------------------------------
# SAFETY/DENSITY/SHED integration (2026-08-09, modality-fit review + density-integrity).
# The verdict was topology-only (keyed on fit_class); the cards' KILLER/downgrade signals
# fired into the narrative but could NOT move the verdict. These resolver combination rungs
# (when_all_fired: fit-positive AND a liability rule) refine the call. Pin the biology + the two
# validated-antigen guardrails (CEACAM5 ADC survives, CD19 not killed by low density).
# ---------------------------------------------------------------------------

def _vv(*rule_ids):
    return smf._verdict([{"rule_id": r} for r in rule_ids])


def test_protein_absent_forecloses_both_modalities():
    # No surface substrate → both ADC + TCE dead, regardless of favorable topology.
    assert _vv("both-viable-supportive", "ihc-not-detected-killer")[0] == "neither_viable"


def test_essential_normal_tissue_drops_tce_but_preserves_adc_CEACAM5_guardrail():
    # bite_tce-ONLY killer: a both_viable target with essential-normal-tissue expression keeps its
    # ADC arm (CEACAM5 = validated ADC target w/ normal-gut expression must NOT be killed for ADC).
    assert _vv("both-viable-supportive", "normal-tissue-essential-bite-killer")[0] == "adc_preferred_tce_unsafe"
    # sc-normal HIGH_LIABILITY behaves identically.
    assert _vv("both-viable-supportive", "sc-normal-high-liability-bite-killer")[0] == "adc_preferred_tce_unsafe"
    # a TCE-only target with the same liability has no safe arm left.
    assert _vv("tce-preferred-supportive", "normal-tissue-essential-bite-killer")[0] == "tce_unsafe_normal_liability"


def test_measured_low_density_is_a_downgrade_never_a_veto_CD19_guardrail():
    # MEASURED grade-A/B below-TCE-floor density → caveat, NEVER neither_viable. CD19 (~110 copies/cell)
    # is a validated CAR-T/TCE antigen; a hard density veto would false-negative it.
    v = _vv("both-viable-supportive", "surface-density-below-tce-floor-measured-downgrade")[0]
    assert v == "surface_viable_density_caveated"
    assert v != "neither_viable", "measured low density must NOT foreclose the target (CD19 trap)"


def test_dominant_shed_ectodomain_caveats_the_call():
    assert _vv("both-viable-supportive", "shed-ectodomain-clinical-opposing")[0] == "shed_dominant_opposed"


def test_therapeutic_window_essential_liability_drops_tce_preserves_adc_2026_08_24():
    # SAFETY mover (promoted 2026-08-24): the modality-therapeutic-window essential_tissue_liability
    # (CEACAM5 ~558x-window-yet-lung-positive pattern) now moves the verdict — same semantics as the
    # normal-tissue killer: drop TCE, preserve ADC (moderate-tier bystander buffer).
    assert _vv("both-viable-supportive", "modality-window-essential-liability-tce-opposing")[0] == "adc_preferred_tce_unsafe"
    assert _vv("tce-preferred-supportive", "modality-window-essential-liability-tce-opposing")[0] == "tce_unsafe_normal_liability"


def test_exon_window_essential_liability_drops_tce_preserves_adc():
    # SAFETY mover (2026-08-28, distillation assessment): exon-grain essential-window liability mirrors the
    # transcript-window rungs (7/8) at the finer EXON resolution — drop TCE, preserve ADC.
    assert _vv("both-viable-supportive", "exon-window-essential-liability-tce-opposing")[0] == "adc_preferred_tce_unsafe"
    assert _vv("tce-preferred-supportive", "exon-window-essential-liability-tce-opposing")[0] == "tce_unsafe_normal_liability"


def test_pmhc_normal_presentation_vetoes_pmhc_support():
    # SAFETY veto (2026-08-28, distillation assessment): a pMHC epitope BROADLY PRESENTED on normal tissue
    # withdraws the un-earned pmhc_tce_supported promotion → tce_unsafe_normal_liability (the 3-condition
    # veto rung at priority 19/20 outranks the 2-condition pmhc_tce_supported at 21/22).
    assert _vv("neither-viable-killer", "pmhc-iedb-tcell-validated-tce-supportive")[0] == "pmhc_tce_supported"
    assert smf._verdict([{"rule_id": "neither-viable-killer"}, {"rule_id": "pmhc-iedb-tcell-validated-tce-supportive"},
                         {"rule_id": "pmhc-broadly-presented-normal-tce-opposing"}])[0] == "tce_unsafe_normal_liability"
    assert smf._verdict([{"rule_id": "neither-viable-killer"}, {"rule_id": "pmhc-iedb-presented-tce-supportive"},
                         {"rule_id": "pmhc-broadly-presented-normal-tce-opposing"}])[0] == "tce_unsafe_normal_liability"


def test_tce_antigen_escape_is_an_efficacy_mover_distinct_from_safety_2026_08_24():
    # EFFICACY mover (new 2026-08-24): within-tumor antigen escape (escape_risk_high) forecloses the TCE
    # arm on EFFICACY (antigen-low escape reservoir), a DISTINCT verdict from the safety tce_unsafe rungs.
    # ADC preserved (bystander-tolerant).
    assert _vv("both-viable-supportive", "sc-antigen-escape-high-tce-opposing")[0] == "adc_preferred_tce_escape_risk"
    assert _vv("tce-preferred-supportive", "sc-antigen-escape-high-tce-opposing")[0] == "tce_escape_risk"
    # escape is a TCE concern only — an ADC_preferred target is unchanged by it.
    assert _vv("adc-preferred-supportive", "sc-antigen-escape-high-tce-opposing")[0] == "adc_preferred"


def test_tce_antigen_escape_patient_variable_tempers_not_forecloses_2026_09_04():
    # EFFICACY mover (#979): the MIDDLE escape band (escape_risk_patient_variable) TEMPERS the TCE arm with
    # a patient-selection caveat → OWN positive-caveated verdicts, distinct from the escape_risk_high
    # foreclosure. ADC preserved.
    assert _vv("both-viable-supportive", "sc-antigen-escape-patient-variable-tce-opposing")[0] == "adc_preferred_tce_patient_variable"
    assert _vv("tce-preferred-supportive", "sc-antigen-escape-patient-variable-tce-opposing")[0] == "tce_patient_variable"
    # an ADC_preferred base is unaffected (escape is a TCE concern only).
    assert _vv("adc-preferred-supportive", "sc-antigen-escape-patient-variable-tce-opposing")[0] == "adc_preferred"
    # DON'T-OVER-PENALIZE: unlike tce_escape_risk (a _SM_NEG negative), the patient_variable tokens are
    # positive-caveated (_SM_MOD_POS) — a validated antigen with normal patient-variability stays a positive.
    assert "adc_preferred_tce_patient_variable" in smf._SM_MOD_POS
    assert "tce_patient_variable" in smf._SM_MOD_POS
    assert "tce_patient_variable" not in smf._SM_NEG


def test_patient_variable_ranks_below_high_escape_and_above_density():
    # The escape class is single-valued so the two escape rungs cannot co-fire on live data; the ordering
    # is still priority-pinned. escape_risk_high (harder foreclosure) outranks patient_variable.
    assert _vv("both-viable-supportive", "sc-antigen-escape-high-tce-opposing",
               "sc-antigen-escape-patient-variable-tce-opposing")[0] == "adc_preferred_tce_escape_risk"
    # patient_variable (an efficacy TCE caveat) outranks the density caveat.
    assert _vv("both-viable-supportive", "sc-antigen-escape-patient-variable-tce-opposing",
               "surface-density-below-tce-floor-measured-downgrade")[0] == "adc_preferred_tce_patient_variable"
    # SAFETY still outranks the patient-variable efficacy caveat.
    assert _vv("both-viable-supportive", "modality-window-essential-liability-tce-opposing",
               "sc-antigen-escape-patient-variable-tce-opposing")[0] == "adc_preferred_tce_unsafe"


def test_liability_precedence_absence_beats_safety_beats_escape_beats_density():
    # protein-absence (both dead) > TCE-safety downgrade > TCE-efficacy escape > density caveat (first-match).
    assert _vv("both-viable-supportive", "ihc-not-detected-killer", "shed-ectodomain-clinical-opposing")[0] == "neither_viable"
    assert _vv("both-viable-supportive", "normal-tissue-essential-bite-killer",
               "surface-density-below-tce-floor-measured-downgrade")[0] == "adc_preferred_tce_unsafe"
    # safety (window-essential) outranks efficacy (escape) when both fire.
    assert _vv("both-viable-supportive", "modality-window-essential-liability-tce-opposing",
               "sc-antigen-escape-high-tce-opposing")[0] == "adc_preferred_tce_unsafe"
    # efficacy escape outranks the density caveat.
    assert _vv("both-viable-supportive", "sc-antigen-escape-high-tce-opposing",
               "surface-density-below-tce-floor-measured-downgrade")[0] == "adc_preferred_tce_escape_risk"


def test_plain_fit_class_still_byte_stable_without_liabilities():
    # ADDITIVE-REFINEMENT guarantee: with NO liability rule fired, the original fit_class verdicts
    # are unchanged (the 64 pre-existing golden combos are byte-identical).
    assert _vv("both-viable-supportive")[0] == "both_viable"
    assert _vv("adc-preferred-supportive")[0] == "adc_preferred"
    assert _vv("tce-preferred-supportive")[0] == "tce_preferred"


# ---------------------------------------------------------------------------
# biologics-augment (2026-08-06): protein-surface-evidence (CSPA) +
# shed-ectodomain-liability were wired into the skill's CARDS. Their surface-
# intrinsic rules existed but were UNREACHABLE (no skill composed the cards).
# These rules are ADDITIVE (supportive/opposing, no `dominant`, no resolver rung),
# so composing the cards must NOT move the verdict — it only enriches the headline
# + fires the previously-inert signals. Pin that byte-stability here.
# ---------------------------------------------------------------------------

# The two newly-reachable rule_ids (surface-intrinsic.rules.yaml):
_NEWLY_REACHABLE_RULES = [
    "protein-surface-confirmed-supportive",   # CSPA cell_surface_confirmed
    "protein-not-surface-opposing",           # CSPA not_surface (measured-negative; NOT killer)
    # NOTE (2026-08-09 modality-fit review): shed-ectodomain-clinical-opposing was PROMOTED to a
    # resolver combination rung (→ shed_dominant_opposed) and is therefore NO LONGER signal-only;
    # its verdict-moving behavior is pinned by test_dominant_shed_ectodomain_caveats_the_call above.
    # The secretome-proxy + measured-media shed variants remain signal-only (not promoted).
    "shed-ectodomain-secretome-proxy-opposing",
    "shed-ectodomain-measured-media-opposing",  # enrichment — measured Olink conditioned-media shed (media_shed_high)
    # biologics-augment — within-tumor antigen-ESCAPE (single-cell Census); REWIRED onto the superior
    # tce_antigen_escape_class 2026-08-24 (was the lenient tce_homogeneity_class). NOTE: the escape-HIGH
    # rule (sc-antigen-escape-high-tce-opposing) was PROMOTED to a resolver rung (→ adc_preferred_tce_escape_risk
    # / tce_escape_risk) 2026-08-24 and is therefore NO LONGER signal-only — pinned by
    # test_tce_antigen_escape_is_an_efficacy_mover_distinct_from_safety_2026_08_24 above. The escape-LOW
    # supportive variant remains signal-only.
    "sc-antigen-escape-low-tce-supportive",   # escape_risk_low → TCE supportive (signal-only)
    # biologics-augment window arc — modality therapeutic-window (tumor / max-essential-normal). NOTE:
    # the essential-liability rule was PROMOTED to a resolver rung (→ adc_preferred_tce_unsafe /
    # tce_unsafe_normal_liability) 2026-08-24 and is NO LONGER signal-only — pinned by
    # test_therapeutic_window_essential_liability_drops_tce_preserves_adc_2026_08_24 above.
    "modality-window-clean-supportive",       # clean_window → supportive (signal-only)
    "modality-window-narrow-opposing",        # narrow_window → opposing (signal-only)
    # enrichment — peptide-centric HLA presentation (bite_tce-only):
    "pmhc-restricted-presentation-tce-supportive",   # restricted → TCE supportive
    # NOTE (2026-08-28 distillation assessment): pmhc-broadly-presented-normal-tce-opposing was PROMOTED
    # to a resolver veto rung (→ tce_unsafe_normal_liability, priority 19/20; withdraws the un-earned
    # pmhc_tce_supported promotion when the epitope is broadly presented on normal tissue) and is NO LONGER
    # signal-only — pinned by test_pmhc_normal_presentation_vetoes_pmhc_support below.
    # enrichment — modality exon-window (per-exon tumor-vs-normal + heterogeneity flag):
    "exon-window-heterogeneity-flag-supportive",     # exon_heterogeneity_flag → secondary supportive (hypothesis)
    # NOTE (2026-08-28 distillation assessment): exon-window-essential-liability-tce-opposing was PROMOTED
    # to a resolver rung (→ adc_preferred_tce_unsafe / tce_unsafe_normal_liability, priority 9/10; mirrors the
    # transcript-window rungs at 7/8 at the finer exon grain) and is NO LONGER signal-only — pinned by
    # test_exon_window_essential_liability_drops_tce_preserves_adc below.
    # enrichment — CD/IO-antigen backbone clinical-precedent (supportive-only):
    "cd-established-io-backbone-supportive",         # established_io_backbone → supportive (important)
    "cd-antigen-backbone-supportive",                # cd_antigen → supportive (secondary)
]


def test_newly_wired_cards_are_in_the_skill_card_set():
    """Regression: the two orphan-fix cards must stay composed (their rules were inert
    on live data until the skill listed them)."""
    assert "protein-surface-evidence" in smf.CARDS
    assert "shed-ectodomain-liability" in smf.CARDS
    # the single-cell homogeneity card carries the tce_homogeneity_class facet
    assert "tumor-scrna-celltype-expression" in smf.CARDS
    # window arc — the therapeutic-window card
    assert "modality-therapeutic-window" in smf.CARDS
    # enrichment — the peptide-centric pMHC card
    assert "pmhc-presentation" in smf.CARDS
    # enrichment — the per-exon window card
    assert "modality-exon-window" in smf.CARDS
    # enrichment — the CD/IO-antigen backbone card
    assert "cd-antigen-backbone" in smf.CARDS


def test_additive_surface_signals_do_not_move_the_verdict():
    """Byte-stability: adding a CSPA / shed signal to ANY fit_class-driven verdict must
    leave the verdict + driving_rule_id unchanged. The surface_modality resolver keys ONLY
    on the fit_class rungs; these additive rules feed no rung. If a future edit routes one
    of them into the resolver, this test fails LOUDLY (a deliberate speed-bump, not a bug)."""
    fit_class_rules = [
        "adc-preferred-supportive",
        "tce-preferred-supportive",
        "both-viable-supportive",
        "neither-viable-killer",
        "isoform-dependent-modality-suppression",
        "modality-ambiguous-insufficient",
    ]
    for base in fit_class_rules:
        baseline = smf._verdict([{"rule_id": base}])
        for extra in _NEWLY_REACHABLE_RULES:
            fired = [{"rule_id": base}, {"rule_id": extra}]
            assert smf._verdict(fired) == baseline, (
                f"additive rule {extra} moved the verdict off {baseline} for base {base} "
                f"— it must be signal-only (no resolver rung)")


def test_additive_signals_alone_still_insufficient():
    """A CSPA/shed signal with NO fit_class rung fired resolves to the bare insufficient
    default — these cards ENRICH a verdict, they never CREATE one."""
    for extra in _NEWLY_REACHABLE_RULES:
        assert smf._verdict([{"rule_id": extra}]) == ("insufficient", None)


# ---------------------------------------------------------------------------
# IEDB pMHC-epitope PROMOTION (2026-08-25): pmhc-epitope-evidence-iedb → VERDICT-BEARING.
# The representational gap: an intracellular oncoprotein (WT1/PRAME/NY-ESO-1/MAGE-A4) is correctly
# surface-neither_viable YET pMHC-TCE-viable. The two IEDB rules feed a `when_all_fired` rung that
# fires ONLY with neither-viable-killer → pmhc_tce_supported (a bite_tce-scoped POSITIVE), surfacing
# the peptide-MHC route the folded-surface ladder cannot see, WITHOUT flipping a surface-viable call.
# ---------------------------------------------------------------------------

_PMHC_RULES = ("pmhc-iedb-tcell-validated-tce-supportive", "pmhc-iedb-presented-tce-supportive")


def test_pmhc_promotes_neither_viable_to_pmhc_tce_supported():
    # THE GAP FIX: surface-dead intracellular oncoprotein + experimentally-validated pMHC epitopes →
    # pmhc_tce_supported (the pMHC-TCE route), outranking the bare neither_viable rung.
    assert _vv("neither-viable-killer", "pmhc-iedb-tcell-validated-tce-supportive") == (
        "pmhc_tce_supported", "pmhc-iedb-tcell-validated-tce-supportive")
    # the presented-but-not-T-cell-confirmed class promotes identically (driving_rule names the class).
    assert _vv("neither-viable-killer", "pmhc-iedb-presented-tce-supportive") == (
        "pmhc_tce_supported", "pmhc-iedb-presented-tce-supportive")


def test_bare_neither_viable_without_iedb_is_byte_stable():
    # No IEDB epitope → the honest surface negative stands unchanged (assay asymmetry: absence abstains).
    assert _vv("neither-viable-killer") == ("neither_viable", "neither-viable-killer")


def test_pmhc_never_flips_a_surface_viable_call():
    # THE GUARDRAIL: a surface-VIABLE antigen (ERBB2-class both_viable, or adc/tce_preferred) with IEDB
    # epitopes keeps its surface verdict — the pMHC rule rides as an ADDITIVE bite_tce signal, never a flip
    # (the pmhc rung requires neither-viable-killer, which is mutually exclusive with a fit-positive rung).
    for base in ("both-viable-supportive", "adc-preferred-supportive", "tce-preferred-supportive"):
        baseline = smf._verdict([{"rule_id": base}])
        for pmhc in _PMHC_RULES:
            assert _vv(base, pmhc) == baseline, (
                f"pMHC rule {pmhc} wrongly flipped a surface-viable {baseline} for base {base}")


def test_pmhc_rule_alone_is_insufficient():
    # An IEDB epitope with NO fit_class rung fired creates no verdict (needs the neither_viable co-condition).
    for pmhc in _PMHC_RULES:
        assert smf._verdict([{"rule_id": pmhc}]) == ("insufficient", None)


def test_tcell_validated_outranks_presented_when_both_present():
    # Deterministic tie-break (impossible in practice — the class is single-valued — but priority-pinned):
    # tcell_validated (priority 17) wins over presented (18).
    assert _vv("neither-viable-killer", "pmhc-iedb-presented-tce-supportive",
               "pmhc-iedb-tcell-validated-tce-supportive")[1] == "pmhc-iedb-tcell-validated-tce-supportive"
