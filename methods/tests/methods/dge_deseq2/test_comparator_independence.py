"""Comparator INDEPENDENCE in the axis-A selectivity classifier (FIX 4, 2026-09-12).

The tumour-vs-normal sensitivity design brackets a gene between TWO independent comparator families:
the TCGA-adjacent within-patient margin (cell A) and the GTEx population normal (cell C). Cell B —
the ComBat-seq re-run of cell A on the SAME tumour-vs-adjacent samples — was a robustness re-run,
not a third comparator, and was removed entirely in analysis-methods#727. The classifier now reads
cells A and C only; a legacy materialized product that still carries log2fc_cell_b/q_value_cell_b
columns (this PR did NOT rebuild the products) has them ignored — they can neither manufacture a
support vote nor stand in for the adjacent arm.

Historically the shipped classifier counted CELLS, so cells A+B (one comparison, two votes) could
clear the `modest` tier with no GTEx concurrence, and a non-significant ComBat B could dilute a
genuine A+C agreement. FIX 4 replaced the per-CELL count with a per-FAMILY count, and #727 then
removed cell B outright, so both directions of that error are now structurally impossible: the
adjacent family is cell A alone.

Seven indications ship with no adjacent arm at all, so `strong` was minted on cell C alone — the
arm cell D was retired for confounding (32,784 rows). The nomination gate weights
`strong_tumor_selective` DOMINANT (vocabularies/nomination_verdict_gate.yaml) and the
surface-/intracellular-intrinsic rule sets fire on the strong band only, so these are verdict
movers, not cosmetics.

This file pins three things the classifier's own docstring cannot enforce:
  1. the FAMILY denominator, and that a stray legacy cell-B column never re-manufactures a vote;
  2. the EVIDENCE-BASE requirement for `strong`, and the deliberate asymmetry it leaves;
  3. the invariant that no field-effect or strong class ever rests on an adjacent arm that was never
     measured. No SHIPPED row does (0 of 890,801 for field-effect; 32,784 did for strong before FIX
     4b) — but "no current data reaches it" is not "it cannot fire", and the sweep below FOUND a
     reachable path through the discordant rescue that the plan had written off as vacuous, which is
     now guarded in the classifier as FIX 4c. The non-discordant rescue stays unguarded because the
     same sweep proves nothing can take it, and a branch no input can reach is a guard that protects
     nothing (feedback_vacuous_pass_unreachable_fail_branch). This test is what goes red if a future
     product shape opens either path.

Plus a VOCABULARY-COVERAGE test: every value of `selectivity_evidence_independence` is reachable AND
no value outside the documented set is ever emitted. That is the guard whose absence let the `"ns"`
literal die unnoticed in surfaceome_cohort_ranking — a class ladder is only as good as the proof
that each rung can be reached.
"""

from __future__ import annotations

import itertools

from onc_methods.dge_deseq2 import read as dge

classify = dge._classify_selectivity_from_sensitivity

# The documented vocabulary of `selectivity_evidence_independence`. Kept in ONE place so a value
# added to the reader without being added here fails test_evidence_independence_vocabulary_is_closed.
INDEPENDENCE_VOCAB = {
    "two_independent_comparators",
    "adjacent_only",
    "population_normal_only",
    "none",
}

FIELD_EFFECT_CLASSES = {"field_effect_tumor_selective"}
STRONG = "strong_tumor_selective"


def _row(**kw):
    """A post-#727 sensitivity row: cells A (TCGA-adjacent) and C (GTEx) only — no cell B."""
    base = dict(
        cells_ran=2,
        cells_supporting=2,
        dominant_direction="up",
        discordant=False,
        sig_all_cells=False,
        max_abs_log2fc=None,
        log2fc_cell_a=None,
        q_value_cell_a=None,
        log2fc_cell_c=None,
        q_value_cell_c=None,
    )
    base.update(kw)
    return base


# ── 1. the family denominator, and that legacy cell B never re-manufactures a vote ───


def test_a_up_with_gtex_measured_and_dissenting_is_one_family_of_two():
    """Cell A sig-up with cell C MEASURED and NOT agreeing is 1 supporting family of 2 that ran —
    not support. (Under the retired per-cell count, cells A+B agreeing with each other reached
    `modest` here; the family denominator makes a single adjacent comparator one vote.)"""
    r = _row(
        log2fc_cell_a=2.4,
        q_value_cell_a=1e-9,
        log2fc_cell_c=0.05,
        q_value_cell_c=0.91,
        max_abs_log2fc=2.4,
    )
    assert dge._independent_support(r, "up") == (1, 2)
    assert classify(r) == "not_informative"


def test_legacy_cell_b_column_never_manufactures_a_support_vote():
    """REGRESSION (#727): the reader reads MATERIALIZED products, which this PR did not rebuild, so a
    row can still carry a (corrupted) log2fc_cell_b. It must be ignored — the adjacent family is cell
    A alone. Here cell A ran flat and cell C ran flat, so no family supports `up`; a stray sig-up
    cell B must not add one. If cell B ever re-enters _ADJACENT_CELLS this flips to (1, 2)."""
    r = _row(
        log2fc_cell_a=0.05,
        q_value_cell_a=0.80,  # adjacent ran, flat
        log2fc_cell_c=0.10,
        q_value_cell_c=0.77,  # gtex ran, flat
        max_abs_log2fc=3.0,
    )
    r["log2fc_cell_b"] = 3.0  # leftover from an old ComBat product — must not be read
    r["q_value_cell_b"] = 1e-9
    assert dge._independent_support(r, "up") == (0, 2)
    assert classify(r) == "not_informative"
    assert dge._selectivity_evidence_independence(r) == "two_independent_comparators"


def test_cells_supporting_and_cells_ran_no_longer_drive_the_class():
    """The product's own counts are provenance. Vary them wildly over one fixed evidence base;
    the class must not move. (They were the denominator until FIX 4 — this pins that they are not.)"""
    evidence = dict(
        log2fc_cell_a=2.0,
        q_value_cell_a=1e-9,
        log2fc_cell_c=2.2,
        q_value_cell_c=1e-9,
        max_abs_log2fc=2.2,
    )
    seen = {
        classify(_row(cells_ran=ran, cells_supporting=sup, **evidence))
        for ran, sup in itertools.product([None, 0, 1, 2, 3, 4], [None, 0, 1, 2, 3, 4])
    }
    assert seen == {STRONG}, f"cells_ran/cells_supporting still move the class: {seen}"


# ── 2. the evidence base required for `strong`, and the asymmetry it leaves ───


def test_strong_requires_the_adjacent_arm_to_have_been_measured():
    """FOLR1/OV, CLDN6/OV, DLL3/SCLC shape: GTEx-only, huge effect, no adjacent normals anywhere in
    the product. Demoted to `modest` — still axis-A selective, no longer the DOMINANT band."""
    r = _row(
        cells_ran=1,
        cells_supporting=1,
        log2fc_cell_c=9.95,
        q_value_cell_c=1e-120,
        max_abs_log2fc=9.95,
    )
    assert dge._family_ran(r, dge._ADJACENT_CELLS) is False
    assert classify(r) == "modest_tumor_selective"


def test_strong_blocked_by_a_PER_ROW_absent_adjacent_estimate_not_just_a_missing_product():
    """CTAG1B/LUAD shape — the case the plan did not anticipate. LUAD HAS an adjacent arm, but this
    gene has no cell-A estimate (DESeq2 filtered it there), so the absence is per-ROW. `strong`
    must be blocked the same way: the product's capability is not this gene's evidence."""
    r = _row(
        cells_ran=1,
        cells_supporting=1,
        log2fc_cell_a=None,
        q_value_cell_a=None,
        log2fc_cell_c=5.79,
        q_value_cell_c=1e-40,
        max_abs_log2fc=5.79,
    )
    assert classify(r) == "modest_tumor_selective"


def test_strong_blocked_when_the_adjacent_arm_ran_but_did_not_concur():
    """Measured-and-flat is not the same as measured-and-agreeing. An adjacent arm that ran and
    reached no significance cannot underwrite the strong band either."""
    r = _row(
        log2fc_cell_a=0.02,
        q_value_cell_a=0.64,  # ran, flat
        log2fc_cell_c=3.4,
        q_value_cell_c=1e-30,
        max_abs_log2fc=3.4,
    )
    assert dge._family_ran(r, dge._ADJACENT_CELLS) is True
    assert classify(r) != STRONG


def test_strong_on_the_adjacent_arm_ALONE_is_allowed_but_is_labelled():
    """The DELIBERATE asymmetry: `strong` requires the adjacent family, not a second family.

    HNSC's sensitivity product has no cell C at all, so 2,304 of the 4,785 adjacent-only `strong`
    calls are HNSC. That is defensible — within-patient adjacent normal is the trustworthy arm, and
    requiring GTEx concurrence would delete the indication — but it must not be INVISIBLE. A
    consumer that wants two-comparator corroboration reads selectivity_evidence_independence.
    """
    r = _row(
        cells_ran=1,
        cells_supporting=1,
        log2fc_cell_a=2.8,
        q_value_cell_a=1e-20,
        max_abs_log2fc=2.8,
    )
    assert classify(r) == STRONG
    assert dge._selectivity_evidence_independence(r) == "adjacent_only"
    assert dge._independence_fields(r)["comparator_families_ran"] == 1


# ── 3. the invariant that replaces the guard we deliberately did NOT write ────


def test_no_field_effect_class_ever_rests_on_an_unmeasured_adjacent_arm():
    """`field_effect_tumor_selective` means "adjacent normal is ALREADY over-expressing" — a claim
    about the adjacent tissue. It is unmakeable when the adjacent tissue was never measured.

    No shipped row does this (0 of 890,801), but this sweep FOUND that the discordant rescue could:
    `discordant=True` + adjacent absent + cell C sig-up >= 1.5 read absent-as-flat and returned
    field_effect. That is why FIX 4c exists in the classifier. Keep sweeping — the point is that the
    guard has a failing input, so it is a guard and not decoration.
    """
    offenders = []
    for discordant, c_lfc, c_q, direction in itertools.product(
        [True, False],
        [-9.0, -2.0, -1.5, -0.4, 0.0, 0.4, 1.4, 1.5, 2.0, 9.0],
        [1e-300, 1e-30, 0.001, 0.049, 0.05, 0.5, 0.99],
        ["up", "down", "none", None],
    ):
        r = _row(
            discordant=discordant,
            dominant_direction=direction,
            log2fc_cell_a=None,
            q_value_cell_a=None,
            log2fc_cell_c=c_lfc,
            q_value_cell_c=c_q,
            max_abs_log2fc=abs(c_lfc),
        )
        if classify(r) in FIELD_EFFECT_CLASSES:
            offenders.append((discordant, c_lfc, c_q, direction))
    assert not offenders, (
        "field_effect asserted with NO adjacent estimate — the class claims the adjacent normal "
        f"over-expresses, which cannot be read off an arm that never ran: {offenders[:5]}"
    )


def test_no_strong_class_ever_rests_on_an_unmeasured_adjacent_arm():
    """Same sweep for the DOMINANT band — this one WAS reachable before FIX 4b (32,784 rows)."""
    offenders = []
    for discordant, c_lfc, c_q, direction in itertools.product(
        [True, False],
        [-9.0, -1.5, 0.0, 0.6, 1.5, 9.0],
        [1e-300, 0.001, 0.05, 0.9],
        ["up", "down", "none", None],
    ):
        r = _row(
            discordant=discordant,
            dominant_direction=direction,
            log2fc_cell_c=c_lfc,
            q_value_cell_c=c_q,
            max_abs_log2fc=abs(c_lfc),
        )
        if classify(r) == STRONG:
            offenders.append((discordant, c_lfc, c_q, direction))
    assert not offenders, f"strong_tumor_selective minted on the GTEx arm alone: {offenders[:5]}"


# ── vocabulary coverage: every rung reachable, nothing off-ladder ─────────────


def test_evidence_independence_vocabulary_is_closed():
    """No input may produce a value outside the documented vocabulary — the check that would have
    caught a dead literal (the surfaceome `"ns"` lesson). Cell B is not read, so only A and C move
    the value; a stray B is swept in too to prove it stays inert."""
    emitted = set()
    lfc_opts = [None, float("nan"), 0.0, 2.0]
    for a, c, b in itertools.product(lfc_opts, lfc_opts, lfc_opts):
        r = _row(log2fc_cell_a=a, log2fc_cell_c=c)
        r["log2fc_cell_b"] = b  # legacy column; must not affect the value
        emitted.add(dge._selectivity_evidence_independence(r))
    emitted.add(dge._selectivity_evidence_independence({}))
    emitted.add(dge._selectivity_evidence_independence(None))
    assert emitted <= INDEPENDENCE_VOCAB, f"off-vocabulary value emitted: {emitted - INDEPENDENCE_VOCAB}"


def test_every_evidence_independence_value_is_reachable():
    """And the other direction: each rung must be REACHABLE from a real row shape, named by the
    shipped product that produces it. A rung nothing can reach is a rung that does not exist."""
    reached = {
        # COADREAD etc. — adjacent arm + GTEx arm both shipped
        "two_independent_comparators": _row(log2fc_cell_a=1.0, log2fc_cell_c=1.2),
        # HNSC — adjacent arm only, no cell C in the product
        "adjacent_only": _row(log2fc_cell_a=1.0),
        # ACC/LGG/OV/SCLC/SKCM/TGCT/UCS — no adjacent normals exist
        "population_normal_only": _row(log2fc_cell_c=1.2),
        # gene absent from every arm
        "none": _row(),
    }
    assert set(reached) == INDEPENDENCE_VOCAB, "vocabulary and coverage table have diverged"
    for expected, row in reached.items():
        assert dge._selectivity_evidence_independence(row) == expected


def test_sclc_style_materialized_but_all_null_adjacent_column_reads_as_not_measured():
    """SCLC ships a log2fc_A COLUMN with zero non-null values (and, on legacy products, an all-null
    log2fc_B too). A schema check would call that "the adjacent arm ran"; only a VALUE check gets it
    right. The stray all-null B column, if present, is ignored regardless."""
    r = _row(log2fc_cell_a=None, q_value_cell_a=None, log2fc_cell_c=5.02)
    r["log2fc_cell_b"] = None  # legacy all-null column on the materialized product
    assert dge._family_ran(r, dge._ADJACENT_CELLS) is False
    assert dge._selectivity_evidence_independence(r) == "population_normal_only"


def test_nan_is_treated_as_absent_not_as_an_estimate():
    """parquet nulls arrive as NaN through pandas and as None through pyarrow's as_py(). Both must
    read as "not measured" — a NaN counted as an estimate would restore the C-only strong path."""
    r = _row(log2fc_cell_a=float("nan"), log2fc_cell_c=3.0, q_value_cell_c=1e-9)
    assert dge._family_ran(r, dge._ADJACENT_CELLS) is False
    assert dge._selectivity_evidence_independence(r) == "population_normal_only"


# ── the emitted fields ───────────────────────────────────────────────────────


def test_independence_fields_are_self_consistent_with_the_class():
    """adjacent_arm_measured=False must never co-occur with the strong or field-effect bands, and
    comparator_families_supporting must never exceed comparator_families_ran."""
    for r in (
        _row(log2fc_cell_c=9.9, q_value_cell_c=1e-99, max_abs_log2fc=9.9),
        _row(log2fc_cell_a=2.0, q_value_cell_a=1e-9, log2fc_cell_c=2.0, q_value_cell_c=1e-9, max_abs_log2fc=2.0),
        _row(log2fc_cell_a=2.0, q_value_cell_a=1e-9, max_abs_log2fc=2.0),
        _row(),
    ):
        f = dge._independence_fields(r)
        assert f["comparator_families_supporting"] <= f["comparator_families_ran"]
        assert f["selectivity_evidence_independence"] in INDEPENDENCE_VOCAB
        if not f["adjacent_arm_measured"]:
            assert classify(r) not in FIELD_EFFECT_CLASSES | {STRONG}


def test_independence_fields_tolerate_an_empty_row():
    f = dge._independence_fields(None)
    assert f == {
        "comparator_families_ran": 0,
        "comparator_families_supporting": 0,
        "adjacent_arm_measured": False,
        "selectivity_evidence_independence": "none",
    }
