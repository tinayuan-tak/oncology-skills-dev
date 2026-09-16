"""risk_projection — the re-homed DETERMINISTIC 6-dim risk core (moved 2026-09-03 from
literature-risk-assessment/scripts/risk_rollup.py to _skills_common so target-profile can compute
target_report.risk_6dim from in-memory sub_results). Pins the CONTRACT (modality-conditioned
conjunction, reproducibility, engine-blind dims, card-fed clinical/commercial) — not the thresholds —
and the in-memory package assembler's byte-parity with the on-disk evidence-package cards.
"""

from __future__ import annotations

import sys
from pathlib import Path

COMMON = Path(__file__).resolve().parent.parent
if str(COMMON.parent) not in sys.path:
    sys.path.insert(0, str(COMMON.parent))  # skills/

from _skills_common.risk_projection import (  # noqa: E402
    _mod,
    assemble_risk_package,
    deterministic_bins,
)


def _pkg(sub_verdicts: dict, cards: list | None = None) -> dict:
    return {"synthesis": {"sub_verdicts": {k: {"verdict": v} for k, v in sub_verdicts.items()}}, "cards": cards or []}


# --------------------------------------------------------------- deterministic_bins (the pure core)


def test_safety_conjunction_fixes_false_low():
    """The validated FOLR1 fix: on-target-safety may read tolerant, but a critical-organ normal-tissue
    liability under a SURFACE modality escalates safety to HIGH (esc=2) — a 1:1 on-target-only map misses
    it. Conjunction, not a single lookup."""
    pkg = _pkg(
        {"safety": "tolerant_reduced_safety_risk"},
        [{"card_id": "normal-tissue-liability-gtex", "interpretation_call": "critical_organ_liability"}],
    )
    assert deterministic_bins(pkg, "adc")["safety"]["bin"] == "HIGH"
    # same signal, non-surface modality → esc=1 → MED (still raised above the tolerant base LOW)
    assert deterministic_bins(pkg, "small_molecule")["safety"]["bin"] == "MED"


def test_deterministic_bin_is_reproducible():
    pkg = _pkg({"safety": "highly_constrained_safety_concern", "dependency": "concordant_dependent"})
    assert deterministic_bins(pkg, "small_molecule") == deterministic_bins(pkg, "small_molecule")


def test_pan_essential_is_med_biological_not_high():
    """pan_essential_killer is a dependency but not tumor-selective — its tox routes to SAFETY, so
    biological is MED, not HIGH (only non_dependent is HIGH biological risk)."""
    pkg = _pkg({"dependency": "pan_essential_killer", "mechanism": "well_characterized"})
    assert deterministic_bins(pkg, "small_molecule")["biological"]["bin"] == "MED"
    pkg_nd = _pkg({"dependency": "non_dependent", "mechanism": "well_characterized"})
    assert deterministic_bins(pkg_nd, "small_molecule")["biological"]["bin"] == "HIGH"


def test_druggability_strong_tractability_is_low():
    for v in ("well_covered", "chemically_confirmed_genetic", "measured_potent_ligand", "chemically_active"):
        pkg = _pkg({"tractability_sm": v})
        assert deterministic_bins(pkg, "small_molecule")["druggability"]["bin"] == "LOW", v


def test_clinical_bin_from_precedent_card():
    hi = _pkg({}, [{"card_id": "clinical-precedent", "summary": {"notable_failures": True}}])
    assert deterministic_bins(hi, "small_molecule")["clinical"]["bin"] == "HIGH"
    lo = _pkg({}, [{"card_id": "clinical-precedent", "summary": {"highest_clinical_stage": "approved"}}])
    assert deterministic_bins(lo, "small_molecule")["clinical"]["bin"] == "LOW"


def test_commercial_bin_from_competitor_card():
    hi = _pkg({}, [{"card_id": "competitor-landscape", "summary": {"competitor_class": "approved_competitor"}}])
    assert deterministic_bins(hi, "small_molecule")["commercial"]["bin"] == "HIGH"
    lo = _pkg({}, [{"card_id": "competitor-landscape", "summary": {"competitor_class": "no_known_competitor"}}])
    assert deterministic_bins(lo, "small_molecule")["commercial"]["bin"] == "LOW"


def test_engine_blind_dims_present_when_unfed():
    dims = deterministic_bins(_pkg({}), "small_molecule")
    assert set(dims) == {"safety", "biological", "druggability", "clinical", "commercial", "translational"}
    # translational / clinical / commercial are engine-blind when their feeding card is absent
    for d in ("translational", "clinical", "commercial"):
        assert dims[d]["bin"] == "ENGINE-BLIND"


def test_translational_bin_from_readiness_cards():
    # deep model coverage + a deep genotype-matched model = readily preclinically validatable = LOW
    lo = _pkg(
        {},
        [
            {"card_id": "target-model-availability", "summary": {"model_availability_class": "deep_model_coverage"}},
            {"card_id": "target-genotype-matched-model", "summary": {"genotype_matched_class": "matched_deep"}},
        ],
    )
    assert deterministic_bins(lo, "small_molecule")["translational"]["bin"] == "LOW"
    # sparse coverage + no genotype-matched model = hard to validate = HIGH (worst-of the two legs)
    hi = _pkg(
        {},
        [
            {"card_id": "target-model-availability", "summary": {"model_availability_class": "sparse_model_coverage"}},
            {"card_id": "target-genotype-matched-model", "summary": {"genotype_matched_class": "none"}},
        ],
    )
    assert deterministic_bins(hi, "small_molecule")["translational"]["bin"] == "HIGH"
    # a PDXE in-vivo objective responder caps an otherwise-HIGH readiness risk at MED
    capped = _pkg(
        {},
        [
            {"card_id": "target-model-availability", "summary": {"model_availability_class": "sparse_model_coverage"}},
            {"card_id": "target-genotype-matched-model", "summary": {"genotype_matched_class": "none"}},
            {"card_id": "target-pdx-drug-response", "summary": {"pdx_drug_response_class": "pdx_objective_responders"}},
        ],
    )
    d = deterministic_bins(capped, "small_molecule")["translational"]
    assert d["bin"] == "MED" and d["mitigation"]


def test_raw_loeuf_surfaced_in_safety_chain():
    pkg = _pkg(
        {"safety": "highly_constrained_safety_concern"},
        [{"card_id": "gnomad-lof-constraint", "summary": {"loeuf_score": 0.12}}],
    )
    chain = deterministic_bins(pkg, "small_molecule")["safety"]["chain"]
    assert any("0.12" in str(detail) for _src, detail, _lvl in chain)


# --------------------------------------------------------------- assemble_risk_package (in-memory pkg)


def _sr(short, verdict, cards=None):
    return {short: {"verdict": (verdict, "r"), "cards": cards or []}}


def test_assemble_from_sub_results_feeds_cards_and_verdicts():
    """The in-memory assembler unions present cards (normalized like the on-disk package) + extracts the
    verdict string — so a clinical-precedent card carried on a sub-result reaches the clinical bin."""
    sub_results = {
        **_sr("safety", "highly_constrained_safety_concern"),
        **_sr(
            "differentiation",
            "landscape",
            [
                {
                    "card_id": "clinical-precedent",
                    "summary": {"highest_clinical_stage": "approved"},
                    "interpretation_call": "x",
                }
            ],
        ),
    }
    pkg = assemble_risk_package(sub_results)
    dims = deterministic_bins(pkg, _mod("small_molecule"))
    assert dims["safety"]["bin"] == "HIGH"  # verdict string threaded
    assert dims["clinical"]["bin"] == "LOW"  # present card threaded through _envelope_card_present


def test_assemble_skips_missing_cards():
    """A _missing card must be excluded from the package (matching _write_evidence_package's present-only
    union) — so a would-be competitor card that didn't resolve leaves commercial ENGINE-BLIND."""
    sub_results = _sr(
        "differentiation",
        "landscape",
        [{"card_id": "competitor-landscape", "summary": {"competitor_class": "approved_competitor"}, "_missing": True}],
    )
    pkg = assemble_risk_package(sub_results)
    assert pkg["cards"] == []  # skipped
    assert deterministic_bins(pkg, "small_molecule")["commercial"]["bin"] == "ENGINE-BLIND"


def test_assemble_bad_input_raises_for_caller_to_catch():
    """assemble_risk_package is pure; a non-dict caller error surfaces (build_risk_6dim wraps it)."""
    import pytest

    with pytest.raises(AttributeError):
        assemble_risk_package("not-a-dict")


# ------------------------------------------------- computed evidence coverage per dim (Step 2d)
# The four states are the contract. A binary measured/not flag over the 504-package corpus would report
# 31 blind spots of which 20 are SALIENCE_SPECS coverage gaps, so `undescribed` (an INSTRUMENT gap) must
# never be reported as an evidence gap; and `absent` (no card resolved) must not be collapsed into
# `unmeasured` (cards resolved, nothing measured) because they call for different actions.


def _cov_pkg(axis, cards_used, cards_missing=(), cards=()):
    """A package carrying ONE axis's card provenance on the skill_report spine + the given cards."""
    return {
        "synthesis": {
            "sub_verdicts": {},
            "skill_reports": {
                axis: {"provenance": {"cards_used": list(cards_used), "cards_missing": list(cards_missing)}}
            },
        },
        "cards": list(cards),
    }


def test_measurement_roles_partition_descriptor_roles():
    """MEASUREMENT_ROLES is held as literals so risk_projection stays stdlib-pure at import; this is the
    guard that keeps those literals honest. A role ADDED to field_descriptor lands in neither set and reds
    HERE — forcing an explicit "is this evidence?" decision instead of silently reading as no-evidence
    (which would fabricate an `undescribed` axis)."""
    from _skills_common import field_descriptor as fd
    from _skills_common.risk_projection import MEASUREMENT_ROLES, NON_MEASUREMENT_ROLES

    assert MEASUREMENT_ROLES | NON_MEASUREMENT_ROLES == set(fd.ROLES)
    assert not (MEASUREMENT_ROLES & NON_MEASUREMENT_ROLES)


def test_coverage_states_are_all_four_reachable():
    """Each state must be REACHABLE, not just declared — an unreachable state is an unfalsifiable branch.
    Uses gnomad_lof_constraint (a real spec: loeuf_score is its effect field) and a spec-less card."""
    from _skills_common.risk_projection import (
        STATE_ABSENT,
        STATE_MEASURED,
        STATE_UNDESCRIBED,
        STATE_UNMEASURED,
        evidence_coverage_by_axis,
    )

    measured = _cov_pkg(
        "safety",
        ["gnomad-lof-constraint"],
        cards=[
            {
                "card_id": "gnomad-lof-constraint",
                "measurement_type": "gnomad_lof_constraint",
                "summary": {"loeuf_score": 0.19},
            }
        ],
    )
    assert evidence_coverage_by_axis(measured)["safety"]["state"] == STATE_MEASURED

    # same card, effect field present but NULL -> descriptor-covered yet nothing measured
    unmeasured = _cov_pkg(
        "safety",
        ["gnomad-lof-constraint"],
        cards=[
            {
                "card_id": "gnomad-lof-constraint",
                "measurement_type": "gnomad_lof_constraint",
                "summary": {"loeuf_score": None},
            }
        ],
    )
    assert evidence_coverage_by_axis(unmeasured)["safety"]["state"] == STATE_UNMEASURED

    # a measurement_type with no salience spec: the card DID report, the descriptor just cannot read it
    undescribed = _cov_pkg(
        "safety",
        ["some-card"],
        cards=[{"card_id": "some-card", "measurement_type": "not_a_registered_type", "summary": {"x": 1.0}}],
    )
    assert evidence_coverage_by_axis(undescribed)["safety"]["state"] == STATE_UNDESCRIBED

    # declared cards, none resolved into the package -> genuinely never looked at
    absent = _cov_pkg("safety", ["gnomad-lof-constraint"], cards_missing=["shet-lof-intolerance"], cards=[])
    got = evidence_coverage_by_axis(absent)["safety"]
    assert got["state"] == STATE_ABSENT and got["n_cards_missing"] == 1


def test_zero_is_measured_not_a_gap():
    """0.0 is a MEASUREMENT. The shared `field_disposition.is_measured` rule owns this; the test pins that
    coverage did not re-invent falsiness (a `if not value` reading would call a LOEUF of 0.0 unmeasured —
    i.e. read the most LoF-intolerant possible gene as 'never looked at')."""
    from _skills_common.risk_projection import STATE_MEASURED, evidence_coverage_by_axis

    pkg = _cov_pkg(
        "safety",
        ["gnomad-lof-constraint"],
        cards=[
            {
                "card_id": "gnomad-lof-constraint",
                "measurement_type": "gnomad_lof_constraint",
                "summary": {"loeuf_score": 0.0},
            }
        ],
    )
    assert evidence_coverage_by_axis(pkg)["safety"]["state"] == STATE_MEASURED


def test_non_measurement_roles_do_not_count_as_evidence():
    """The role filter is the FAIL-OPEN direction: drop it and a card carrying only a `label` or `strata`
    field reads `measured`, i.e. the projection FABRICATES a measurement out of a lineage list. Uses a real
    spec pair — crispr_lof_dependency's `enriched_lineages` is role `strata`, `median_chronos` is `effect`."""
    from _skills_common import field_descriptor as fd
    from _skills_common.risk_projection import (
        MEASUREMENT_ROLES,
        STATE_MEASURED,
        STATE_UNDESCRIBED,
        evidence_coverage_by_axis,
    )

    # guard the fixture's own premise: these two fields must still carry the roles this test assumes
    ds = fd.descriptors_for("crispr_lof_dependency")
    assert ds["enriched_lineages"]["role"] not in MEASUREMENT_ROLES
    assert ds["median_chronos"]["role"] in MEASUREMENT_ROLES

    def _pkg_with(summary):
        return _cov_pkg(
            "dependency",
            ["crispr-lof-dependency"],
            cards=[
                {"card_id": "crispr-lof-dependency", "measurement_type": "crispr_lof_dependency", "summary": summary}
            ],
        )

    strata_only = {"enriched_lineages": ["LUAD", "PAAD"]}  # richly populated, but NOT a measurement
    assert evidence_coverage_by_axis(_pkg_with(strata_only))["dependency"]["state"] == STATE_UNDESCRIBED
    assert evidence_coverage_by_axis(_pkg_with(strata_only))["dependency"]["n_fields_described"] == 0
    # add one real measurement field and the SAME card becomes measured — the strata field is inert either way
    both = dict(strata_only, median_chronos=-0.61)
    got = evidence_coverage_by_axis(_pkg_with(both))["dependency"]
    assert got["state"] == STATE_MEASURED and got["n_fields_described"] == 1


def test_undescribed_is_not_reported_as_an_evidence_gap():
    """The load-bearing separation: a descriptor coverage gap must NOT appear in `unmeasured_axes` (which a
    reader acts on as "acquire this data"). 65% of the corpus's naive blind-spots are this case."""
    from _skills_common.risk_projection import evidence_coverage_by_dim

    pkg = _cov_pkg(
        "safety",
        ["some-card"],
        cards=[{"card_id": "some-card", "measurement_type": "not_a_registered_type", "summary": {"x": 1.0}}],
    )
    cov = evidence_coverage_by_dim(pkg)["safety"]
    assert cov["undescribed_axes"] == ["safety"]
    assert cov["unmeasured_axes"] == [] and cov["unresolved_axes"] == []


def test_card_fed_dim_is_not_reported_blind():
    """clinical / commercial declare an axis that is never a fan-out subskill — their bin comes from the
    clinical-precedent / competitor-landscape CARDS. `axes_reported` empty with `axes_declared` non-empty
    must read as card-fed, not as a blind dimension."""
    from _skills_common.report_render.ir import coverage_phrase
    from _skills_common.risk_projection import evidence_coverage_by_dim

    cov = evidence_coverage_by_dim(_cov_pkg("safety", []))["clinical"]
    assert cov["axes_declared"] == ["clinical"] and cov["axes_reported"] == []
    assert cov["unmeasured_axes"] == [] and cov["unresolved_axes"] == []
    assert "card-fed" in coverage_phrase(cov)


def test_coverage_counts_the_context_companions_the_dim_displays():
    """THE COUNTED-vs-DISPLAYED JOIN. `ir._dim_members` lists a dim's AXIS_TO_DIM members PLUS its
    `_CONTEXT_DIM` companions, so a coverage line that counted only the former UNDERSTATED the dim's own
    evidence — measured 2026-09-16 at 14291 resolved cards corpus-wide, e.g. `biological` reading "4/4 axes
    measured · 43 cards resolved" on a target where 6 axes reported and 56 cards resolved.

    Why this test exists at all: the only pre-existing `axes_declared` pins were on `safety` and `clinical`,
    neither of which has a context companion, so NOTHING in this suite could observe the undercount or a
    regression of the fix. A guard whose fixture cannot express the failure is not a guard.
    """
    from _skills_common.risk_projection import COVERAGE_ONLY_AXES, evidence_coverage_by_dim

    assert COVERAGE_ONLY_AXES.get("cis_coherence") == "biological", "fixture assumes this routing"
    card = {
        "card_id": "gnomad-lof-constraint",
        "measurement_type": "gnomad_lof_constraint",
        "summary": {"loeuf_score": 0.21},
    }
    pkg = {
        "synthesis": {
            "sub_verdicts": {},
            "skill_reports": {
                # one verdict-bearing member of `biological` + one coverage-only context companion
                "dependency": {"provenance": {"cards_used": ["gnomad-lof-constraint"], "cards_missing": []}},
                "cis_coherence": {"provenance": {"cards_used": ["gnomad-lof-constraint"], "cards_missing": ["x"]}},
            },
        },
        "cards": [card],
    }
    cov = evidence_coverage_by_dim(pkg)["biological"]
    assert "cis_coherence" in cov["axes_declared"], (
        "a _CONTEXT_DIM companion the report DISPLAYS under biological is missing from the dim's counted "
        "set — the coverage line would understate the dim's own evidence"
    )
    assert "cis_coherence" in cov["axes_reported"]
    # its cards must actually reach the totals, not merely appear in the declared list
    assert cov["n_cards_resolved"] == 2 and cov["n_cards_missing"] == 1
    # verdict-bearing members are still counted first, and no axis is counted twice
    assert cov["axes_declared"].index("dependency") < cov["axes_declared"].index("cis_coherence")
    assert len(cov["axes_declared"]) == len(set(cov["axes_declared"]))


def test_permanently_undescribed_companions_stay_out_of_the_coverage_count():
    """The inclusion rule's other half: `literature_context` is `commercial`'s ONLY context companion and is
    `undescribed` on 504/504 corpus runs, so counting it would replace that dim's honest "card-fed dim — no
    subskill axis reports into it" with "0/1 axes measured" — a MEASURED CLAIM OF BLINDNESS about a dim that
    is card-fed by design. This pins the guard that makes the naive "union the two maps" fix wrong.
    """
    from _skills_common.report_render.ir import _CONTEXT_DIM, coverage_phrase
    from _skills_common.risk_projection import COVERAGE_ONLY_AXES, evidence_coverage_by_dim

    assert _CONTEXT_DIM["literature_context"] == "commercial", "fixture assumes this routing"
    assert "literature_context" not in COVERAGE_ONLY_AXES

    pkg = _cov_pkg("literature_context", ["lit-card"], cards=[{"card_id": "lit-card", "summary": {"n": 1}}])
    cov = evidence_coverage_by_dim(pkg)["commercial"]
    assert cov["axes_reported"] == [], "literature_context must not be counted into commercial"
    assert "card-fed" in coverage_phrase(cov)
    assert "0/1 axes measured" not in coverage_phrase(cov)


def test_missing_cards_are_counted_even_when_the_axis_is_measured():
    """The number a bin cannot show: an axis can be `measured` off 1 card while 9 declared cards never
    resolved (seen live — ABL1-CML selectivity: 3 resolved, 9 missing, state `measured`). Corpus-wide 15.6%
    of declared cards do not resolve, so this count must ride along with the state, not replace it."""
    from _skills_common.risk_projection import STATE_MEASURED, evidence_coverage_by_dim

    pkg = _cov_pkg(
        "selectivity",
        ["gnomad-lof-constraint"],
        cards_missing=["a", "b", "c"],
        cards=[
            {
                "card_id": "gnomad-lof-constraint",
                "measurement_type": "gnomad_lof_constraint",
                "summary": {"loeuf_score": 0.19},
            }
        ],
    )
    cov = evidence_coverage_by_dim(pkg)["safety"]  # selectivity routes into SAFETY
    assert cov["axes"]["selectivity"]["state"] == STATE_MEASURED
    assert cov["n_cards_resolved"] == 1 and cov["n_cards_missing"] == 3
    assert "3 declared cards did not" in _phrase(cov)


def _phrase(cov):
    from _skills_common.report_render.ir import coverage_phrase

    return coverage_phrase(cov)


def test_coverage_is_additive_and_bins_are_untouched():
    """ADDITIVE contract: every pre-existing key of every dim is byte-identical to the same run with the
    coverage payload stripped — `evidence_coverage` is the ONLY new key on a dim."""
    pkg = _pkg(
        {"safety": "highly_constrained_safety_concern", "dependency": "non_dependent"},
        [{"card_id": "gnomad-lof-constraint", "summary": {"loeuf_score": 0.12}}],
    )
    dims = deterministic_bins(pkg, "small_molecule")
    for dim, d in dims.items():
        assert "evidence_coverage" in d, dim
        assert set(d) - {"evidence_coverage"} <= {
            "pillar",
            "bin",
            "chain",
            "mitigation",
            "blind_spots",
        }, dim
        assert d.get("blind_spots") is not None or dim in ("clinical", "commercial", "translational")


def test_coverage_present_but_empty_without_a_skill_report_spine():
    """A package with no skill_reports (a bare unit call / an older artifact) must still get the key, with
    NO axes reported — silence, not a fabricated blind-spot."""
    dims = deterministic_bins(_pkg({"safety": "tolerant_reduced_safety_risk"}), "small_molecule")
    cov = dims["safety"]["evidence_coverage"]
    assert cov["axes_reported"] == [] and cov["unmeasured_axes"] == []


def test_assemble_carries_axis_provenance_for_the_in_memory_path():
    """The in-memory path is target-profile's LIVE path. Without the skill_report provenance copied into
    the assembled package the coverage join is inert there while working on disk — green in the lit-risk
    CLI, empty in every real run. Pins that the copy happens."""
    sub_results = {
        "safety": {
            "verdict": ("highly_constrained_safety_concern", "r"),
            "cards": [
                {
                    "card_id": "gnomad-lof-constraint",
                    "summary": {"loeuf_score": 0.19},
                    "interpretation_call": "highly_constrained",
                }
            ],
            "synthesis_facet": {
                "skill_report": {
                    "provenance": {"cards_used": ["gnomad-lof-constraint"], "cards_missing": ["shet-lof-intolerance"]}
                }
            },
        }
    }
    from _skills_common.measurement_types import card_measurement_type

    pkg = assemble_risk_package(sub_results)
    assert pkg["synthesis"]["skill_reports"]["safety"]["provenance"]["cards_used"] == ["gnomad-lof-constraint"]
    cov = deterministic_bins(pkg, "small_molecule")["safety"]["evidence_coverage"]
    assert cov["axes"]["safety"]["n_cards_missing"] == 1  # the count no bin can express

    # `_envelope_card_present` REBUILDS the card against a schema with unevaluatedProperties:false and so
    # does NOT carry `measurement_type` (only the on-disk envelope writer stamps it) — measured above, and
    # asserted here so a future schema that DOES carry it reds and tells the reader the fallback is moot.
    assert "measurement_type" not in pkg["cards"][0]
    # ...therefore the descriptor join can only key off the measurement_types registry back-ref. Expectation
    # is DERIVED from that registry rather than hardcoded (it is a sibling-checkout lookup, absent in a bare
    # environment) so this stays falsifiable BOTH ways: drop the fallback and a resolvable back-ref reds.
    expected = "measured" if card_measurement_type("gnomad-lof-constraint") else "undescribed"
    assert cov["axes"]["safety"]["state"] == expected
