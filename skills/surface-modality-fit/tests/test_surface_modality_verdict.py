"""surface-modality-fit _verdict coverage (C2 fix + G test-coverage, 2026-07-20).

surface-modality-fit shipped with NO tests (one of 3 test-less wired skills) AND its
composed adc-tce-modality-fit card can emit fit_class `modality_ambiguous`, which had
no rule + no verdict branch → silent fall-through to insufficient (C2). These tests
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
    """C2 regression: modality_ambiguous must resolve to an EXPLICIT verdict with a
    driving rule_id — NOT the silent (insufficient, None) fall-through it was before."""
    v, drv = _v("modality-ambiguous-insufficient")
    assert v == "modality_ambiguous"
    assert drv == "modality-ambiguous-insufficient", "must carry provenance, not a bare None"


def test_nothing_fired_is_bare_insufficient():
    # genuinely-nothing-fired is distinct from modality_ambiguous (which names WHY)
    assert smf._verdict([]) == ("insufficient", None)


def test_fit_class_vocabulary_is_exhaustively_handled():
    """EXHAUSTIVENESS guard: every fit_class value the card can emit must map to a
    verdict branch (this is the manual precursor to the gap-#5 exhaustiveness
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
# biologics-augment Phase 1.1 (2026-08-06): protein-surface-evidence (CSPA) +
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
    "shed-ectodomain-clinical-opposing",      # clinically_shed serum-marker antigen sink
    "shed-ectodomain-secretome-proxy-opposing",
    # biologics-augment Phase 3.2 — within-tumor antigen-homogeneity (single-cell Census):
    "sc-homogeneity-uniform-tce-supportive",  # homogeneous → TCE supportive
    "sc-homogeneity-heterogeneous-tce-opposing",  # heterogeneous → TCE opposing (escape reservoir)
]


def test_newly_wired_cards_are_in_the_skill_card_set():
    """Regression: the two orphan-fix cards must stay composed (their rules were inert
    on live data until the skill listed them)."""
    assert "protein-surface-evidence" in smf.CARDS
    assert "shed-ectodomain-liability" in smf.CARDS
    # Phase 3.2 — the single-cell homogeneity card carries the tce_homogeneity_class facet
    assert "tumor-scrna-celltype-expression" in smf.CARDS


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
