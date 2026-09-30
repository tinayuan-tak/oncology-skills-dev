"""Teeth for the #2221 adjudication of the "highly expressed" absolute anchor (5.0 vs 5.6724).

WHAT WAS ADJUDICATED, so a reader does not have to reconstruct it from the asserts:

The absolute "highly expressed" bar on log2(TPM+1) exists at two values, and — unlike #2220, which
was closed as a non-divergence because its two numbers cut DIFFERENT quantities — these two cut the
SAME quantity on both arms: the fraction of samples at or above the bar.

    cell-line arm   5.0     depmap_expression_distribution/cli.py compute_summary_stats default,
                            depmap_expression_distribution/read.py `_HIGHLY_EXPRESSED`,
                            expression_properties/resolve.py `_HIGHLY_EXPRESSED_LOG2TPM`
    tumour arm      5.6724  tcga_gtex_expression_distribution/stats.py `HIGH_LOG2TPM` (= log2(51))

Outcome: **NO CONSTANT MOVED.** These tests do not assert that the anchor is right; they assert that
the evidence still DESCRIBES the tree, so the adjudication cannot silently rot:

  * the fixture's window still strictly contains both bars (else the matrix is vacuous);
  * the live constants are still the two values the matrix measured (else re-run `regenerate.py`);
  * the property catalog still records both at their live values and cites this matrix;
  * the flip populations, re-derived from the stored RAW per-sample values, are still the measured
    8 / 8 — so a change to either arm's classifier shows up here as a named diff, not a silence.

Nothing here asserts anything about any verdict, in either direction (SK#2091). The subject is the
measurement and its provenance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
MATRIX_PATH = HERE / "matrix.json"
REPO_ROOT = HERE.parents[3]
CATALOG = REPO_ROOT / "contracts" / "vocabularies" / "property_catalog"

# The two candidate anchors, written out so a reader sees the subject of the whole module.
BAR_LOG_ROUND = 5.0  # round in LOG space, TPM ~31
BAR_LINEAR_ROUND = 5.6724  # round in LINEAR space, log2(51), TPM ~50
# The two bars that are NOT under test; the fixture stores integer counts at each.
DETECTABLE = 1.0
MODERATE = 3.4594
# The card-vs-method rounding sliver from tumor-rna-distribution.card.yaml:323-327 (the card declares
# a rounded 5.67 while the method uses 5.6724, so a value in this half-open interval DISPLAYS as at or
# above the declared cutoff while the code puts it below).
SLIVER = (5.67, BAR_LINEAR_ROUND)


def _load(path: Path):
    """Read a counterpart file, FAILING LOUD if it is unreadable.

    A cross-file clause that treats an unreadable counterpart as "nothing to check" passes quietly
    for the rest of time; every cross-file assert in this module comes through here.
    """
    if not path.exists():
        raise AssertionError(f"counterpart missing: {path} — this clause cannot pass vacuously")
    text = path.read_text()
    if not text.strip():
        raise AssertionError(f"counterpart empty: {path}")
    return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)


MATRIX = _load(MATRIX_PATH)
TUMOR_ROWS = MATRIX["tumor"]
CELLLINE_ROWS = MATRIX["cellline"]
ALL_ROWS = TUMOR_ROWS + CELLLINE_ROWS


# ── the fixture's own integrity ────────────────────────────────────────────────────────────────


def test_the_window_strictly_contains_both_candidate_bars_with_margin():
    """THE ANTI-VACUITY GUARD. `frac_ge(b)` is recoverable from the fixture only for a bar INSIDE the
    stored window. If either anchor moves out of the window, every flip clause below silently starts
    measuring a bar the fixture cannot see. That must be a RED with an explanation, not a pass.
    """
    assert len(ALL_ROWS) >= 117, f"matrix has only {len(ALL_ROWS)} rows — too thin to adjudicate"
    from methods.expression_properties import resolve as R
    from methods.tcga_gtex_expression_distribution import stats as S

    live = (R._HIGHLY_EXPRESSED_LOG2TPM, S.HIGH_LOG2TPM)
    for row in ALL_ROWS:
        lo, hi = row["win"]
        for bar in live:
            assert lo + 0.4 <= bar <= hi - 0.4, (
                f"{row['target']}: bar {bar} is not strictly inside the stored window [{lo}, {hi}) "
                f"with margin — re-run regenerate.py with a window that contains it"
            )


def test_every_row_partitions_into_n_and_the_untested_bar_counts_are_consistent():
    """The compression is only lossless if the three pieces sum to n. A row that does not partition is
    a corrupt capture, and every fraction derived from it would be quietly wrong.
    """
    assert len(ALL_ROWS) >= 117
    for row in ALL_ROWS:
        inside = len(row["win_values"])
        assert row["n_lt_win"] + inside + row["n_ge_win"] == row["n"], row["target"]
        # everything in or above the window is >= MODERATE, so the moderate count cannot be smaller
        assert row["n_ge_moderate"] >= inside + row["n_ge_win"], row["target"]
        # everything below the detection floor is below the window
        assert row["n_lt_detectable"] <= row["n_lt_win"], row["target"]
        a, b, c, _ = _bands(row)
        assert a >= 0 and b >= 0 and c >= 0, f"{row['target']}: negative band count {(a, b, c)}"
        lo, hi = row["win"]
        assert all(lo <= v < hi for v in row["win_values"]), row["target"]
        assert row["win_values"] == sorted(row["win_values"]), row["target"]


def test_the_excluded_units_are_named_rather_than_dropped():
    """An unexplained shrink in the row count is indistinguishable from a coverage loss, so the panel's
    misses are recorded. Deliberately GREEN when the list is empty AND when it is not — what must not
    happen is a unit vanishing with no row and no exclusion.
    """
    panel = _load(REPO_ROOT / MATRIX["_meta"]["panel"])
    wanted = {(p["target"], p["code"]) for p in panel["pairs"]}
    wanted |= {(e["target"], e["code"]) for e in (panel["_meta"].get("excluded") or [])}
    accounted = {(r["target"], r["indication"]) for r in TUMOR_ROWS}
    accounted |= {(e["target"], e["indication"]) for e in MATRIX["_meta"]["excluded"] if e["arm"] == "tumor"}
    assert wanted - accounted == set(), f"tumour panel units with neither a row nor an exclusion: {wanted - accounted}"


# ── re-derivation: the flip matrix proper ──────────────────────────────────────────────────────


def _bands(row) -> tuple[int, int, int, int]:
    """(below detectable, [detectable, moderate), [moderate, win_lo), >= win_hi) — all measured counts."""
    a = row["n_lt_detectable"]
    inside, above = len(row["win_values"]), row["n_ge_win"]
    c = row["n_ge_moderate"] - inside - above
    b = row["n_lt_win"] - a - c
    return a, b, c, above


def _band_equivalent_vector(row) -> list[float]:
    """A vector with the SAME count in every band the thresholds can see, built from the measured
    values inside the window plus one representative per band outside it.

    EXACT for anything that depends only on band membership at `DETECTABLE`, `MODERATE`, the window
    edges, or any bar inside the window: `expression_fractions`, `distribution_pattern`,
    `_classify_tumor_expression`, `_classify_expression`.

    NOT exact for anything that depends on the values themselves — median, CoV, percentiles. Those
    are stored as measured statistics on the row and are read from there, never from this vector.
    """
    a, b, c, above = _bands(row)
    lo, hi = row["win"]
    return (
        [0.0] * a
        + [(DETECTABLE + MODERATE) / 2] * b
        + [(MODERATE + lo) / 2] * c
        + list(row["win_values"])
        + [hi + 2.0] * above
    )


def test_the_band_equivalent_vector_reproduces_every_stored_count():
    """The reconstruction above is the only bridge between the compressed fixture and the real
    functions. If it is wrong, every flip clause is wrong in the same direction and would still agree
    with itself — so it is pinned against the stored counts directly.
    """
    assert len(ALL_ROWS) >= 117
    for row in ALL_ROWS:
        v = _band_equivalent_vector(row)
        assert len(v) == row["n"], row["target"]
        assert sum(1 for x in v if x < DETECTABLE) == row["n_lt_detectable"], row["target"]
        assert sum(1 for x in v if x >= MODERATE) == row["n_ge_moderate"], row["target"]
        assert sum(1 for x in v if x >= row["win"][1]) == row["n_ge_win"], row["target"]
        for bar in (BAR_LOG_ROUND, BAR_LINEAR_ROUND):
            expected = row["n_ge_win"] + sum(1 for x in row["win_values"] if x >= bar)
            assert sum(1 for x in v if x >= bar) == expected, (row["target"], bar)


def test_the_reconstruction_agrees_with_the_independently_captured_panel_fixture():
    """THE INDEPENDENT CHECK, and the strongest clause here.

    `subset_high_live_flip_matrix.json` was captured in a different session by a different regenerator
    that stored `cls` / `pat` / `high` / `det` from the REAL loader on the REAL per-sample vector. This
    fixture stores band counts plus the windowed values. Two independent captures, one reconstruction:
    at the live tumour bar every unit must agree on all three derived quantities, exactly.

    This is also the only clause that can see a change affecting BOTH arms equally. A flip matrix is a
    DIFFERENTIAL instrument — it is structurally blind to a shape-heuristic regression that moves arm A
    and arm B together (measured: mutating `distribution_pattern`'s bimodal off-fraction from 0.20 to
    0.30 leaves every flip clause green). This clause is what makes that mutant red.
    """
    from methods.tcga_gtex_expression_distribution import stats as S

    panel = {(p["target"], p["code"]): p for p in _load(REPO_ROOT / MATRIX["_meta"]["panel"])["pairs"]}
    checked_pat = checked_cls = checked_high = 0
    for row in TUMOR_ROWS:
        ref = panel.get((row["target"], row["indication"]))
        assert ref is not None, f"{row['target']}/{row['indication']} is not in the reference panel"
        got = _tumor_arm(row, S.HIGH_LOG2TPM)
        assert got["pattern"] == ref["pat"], (row["target"], got["pattern"], ref["pat"])
        checked_pat += 1
        assert got["cls"] == ref["cls"], (row["target"], got["cls"], ref["cls"])
        checked_cls += 1
        if ref["high"] is not None:  # the reference stored `high` only where its arms differed
            assert abs(got["high"] - ref["high"]) < 1e-9, (row["target"], got["high"], ref["high"])
            checked_high += 1
    assert checked_pat >= 59 and checked_cls >= 59, f"only {checked_pat}/{checked_cls} units cross-checked"
    assert checked_high >= 25, f"only {checked_high} units cross-checked on high_fraction itself"


def _tumor_arm(row, bar: float) -> dict:
    from methods.tcga_gtex_expression_distribution import stats as S
    from methods.tcga_gtex_expression_distribution.read import _classify_tumor_expression

    v = _band_equivalent_vector(row)
    f = S.expression_fractions(v, detectable=DETECTABLE, moderate=MODERATE, high=bar)
    pattern = S.distribution_pattern(v, detectable=DETECTABLE, high=bar)
    return {
        "high": f["high_fraction"],
        "pattern": pattern,
        "cls": _classify_tumor_expression(
            f["detectable_fraction"], f["high_fraction"], pattern, f["moderate_fraction"]
        ),
    }


def _cellline_arm(row, bar: float) -> dict:
    """The cell-line arm at `bar`.

    `expression_class` also depends on `n_lineage_restricted`, which this fixture does not measure —
    so rather than impute one, the class is evaluated at THREE values and only accepted when all three
    agree. A unit whose class depends on the unmeasured input yields `None` and is excluded from the
    class-flip population instead of being decided by a fabricated input.
    """
    from methods.depmap_expression_distribution import cli as DC
    from methods.expression_properties import resolve as R

    v = _band_equivalent_vector(row)
    n = len(v)
    fe = sum(1 for x in v if x >= DETECTABLE) / n
    fh = sum(1 for x in v if x >= bar) / n
    pattern = DC._distribution_pattern(v, DETECTABLE, bar)
    classes = {DC._classify_expression(fe, fh, nlr) for nlr in (0, 1, 5)}
    summary = {
        "fraction_expressed": fe,
        "fraction_highly_expressed": fh,
        "distribution_pattern": pattern,
        "median_log2tpm_panel": row["median"],
        "coefficient_of_variation": row["cov"],
    }
    # Arm B for the median leg means the module constant itself moves; that is what the counterfactual
    # IS. Restored in `finally` so one arm can never leak into the next unit.
    saved = R._HIGHLY_EXPRESSED_LOG2TPM
    R._HIGHLY_EXPRESSED_LOG2TPM = bar
    try:
        props = R.resolve_expression_properties(summary)
    finally:
        R._HIGHLY_EXPRESSED_LOG2TPM = saved
    return {
        "fh": fh,
        "pattern": pattern,
        "cls": classes.pop() if len(classes) == 1 else None,
        "magnitude": props["magnitude"],
        "prevalence": props["prevalence"],
        "heterogeneity": props["heterogeneity"],
    }


# The measured flip populations. Named, not counted — a count would let one mover leave while another
# arrives and still report the same number.
TUMOR_MOVERS = {
    ("EPAS1", "COADREAD"),
    ("PARP1", "OV"),
    ("RBM39", "COADREAD"),
    ("SKP2", "SCLC"),
    ("CLDN6", "OV"),
    ("DLK1", "LIHC"),
    ("ERBB2", "STAD"),
    ("CD276", "PAAD"),
}
CELLLINE_MOVERS = {"CHEK1", "EPAS1", "ERBB2", "KIF11", "MET", "SKP2", "SMARCA2", "WEE1"}


def test_tumour_arm_flip_population_is_the_measured_eight():
    """Arm A = the live 5.6724; arm B = the counterfactual 5.0. Lowering the bar can only ADD samples
    to `high_fraction`, so every tumour mover is a PROMOTION — the direction is a property of the
    monotone bar, not of the panel.
    """
    assert len(TUMOR_ROWS) >= 59, f"only {len(TUMOR_ROWS)} tumour units"
    moved, still = set(), 0
    for row in TUMOR_ROWS:
        a, b = _tumor_arm(row, BAR_LINEAR_ROUND), _tumor_arm(row, BAR_LOG_ROUND)
        if (a["cls"], a["pattern"]) != (b["cls"], b["pattern"]):
            moved.add((row["target"], row["indication"]))
        else:
            still += 1
        assert b["high"] >= a["high"], f"{row['target']}: lowering the bar lowered high_fraction"
    assert moved == TUMOR_MOVERS, f"tumour flip population moved: +{moved - TUMOR_MOVERS} -{TUMOR_MOVERS - moved}"
    assert still == len(TUMOR_ROWS) - len(TUMOR_MOVERS)


def test_cellline_arm_flip_population_is_the_measured_eight():
    """Arm A = the live 5.0; arm B = the counterfactual 5.6724. Raising the bar can only REMOVE samples
    from `fraction_highly_expressed`, so every cell-line mover is a DEMOTION on the fraction.
    """
    assert len(CELLLINE_ROWS) >= 58, f"only {len(CELLLINE_ROWS)} cell-line units"
    keys = ("cls", "pattern", "magnitude", "prevalence", "heterogeneity")
    moved = set()
    for row in CELLLINE_ROWS:
        a, b = _cellline_arm(row, BAR_LOG_ROUND), _cellline_arm(row, BAR_LINEAR_ROUND)
        if any(a[k] != b[k] for k in keys):
            moved.add(row["target"])
        assert b["fh"] <= a["fh"], f"{row['target']}: raising the bar raised fraction_highly_expressed"
    assert moved == CELLLINE_MOVERS, (
        f"cell-line flip population moved: +{moved - CELLLINE_MOVERS} -{CELLLINE_MOVERS - moved}"
    )


def test_seven_of_the_eight_tumour_movers_are_exactly_the_units_whose_median_sits_between_the_anchors():
    """The structural result the adjudication rests on: the tumour flip population is not scattered —
    it is (bar one) the set of units whose PANEL MEDIAN lies in the gap between the two anchors. Those
    units are "highly expressed" under one rounding convention and not under the other at the median
    grain as well as the fraction grain, which is why the divergence is not cosmetic.

    The eighth mover, DLK1/LIHC, is a different mechanism and is named so it cannot hide in a count:
    its median is at the floor and it crosses the `subset_high` 0.1 fraction bar on a long_tail shape.
    """
    in_gap = {(r["target"], r["indication"]) for r in TUMOR_ROWS if BAR_LOG_ROUND <= r["median"] < BAR_LINEAR_ROUND}
    assert len(in_gap) == 7, f"expected 7 tumour medians in the anchor gap, got {len(in_gap)}: {in_gap}"
    assert in_gap == TUMOR_MOVERS - {("DLK1", "LIHC")}, f"gap set and mover set diverged: {in_gap ^ TUMOR_MOVERS}"
    dlk1 = next(r for r in TUMOR_ROWS if (r["target"], r["indication"]) == ("DLK1", "LIHC"))
    assert dlk1["median"] < DETECTABLE, "DLK1/LIHC is the floor-median shape mover; its median moved"


# ── why the anchor is not the right single knob ────────────────────────────────────────────────


def test_the_fraction_bar_on_the_same_quantity_diverges_three_ways():
    """Pinned BEHAVIOURALLY (drive the functions), not by reading a literal.

    `fraction_highly_expressed` / `high_fraction` are the same quantity, and the bar applied to that
    quantity to mint `broadly_high` / `prevalence=broad` is 0.30 in one place and 0.50 in two others.
    Harmonising the ANCHOR alone therefore cannot make the two `broadly_high` words comparable — which
    is the measured reason #2221 lands as evidence rather than as a threshold move. If a peer
    harmonises any of these three, this clause reds and the adjudication must be re-read.
    """
    from methods.depmap_expression_distribution import cli as DC
    from methods.expression_properties import resolve as R
    from methods.tcga_gtex_expression_distribution.read import _classify_tumor_expression

    # cell-line CARD: 0.30 on frac_highly (inside the frac_expressed >= 0.70 branch)
    assert DC._classify_expression(1.0, 0.30, 0) == "broadly_high"
    assert DC._classify_expression(1.0, 0.299, 0) == "broadly_moderate"
    # tumour CARD: 0.50 on high_fraction
    assert _classify_tumor_expression(1.0, 0.50, "continuous", 1.0) == "broadly_high"
    assert _classify_tumor_expression(1.0, 0.499, "continuous", 1.0) != "broadly_high"
    # cell-line PROPERTY resolver: 0.50 on the same cell-line quantity the card cuts at 0.30.
    # MEASURE THE CONJUNCT, not the rung: `_prevalence`'s 0.50 leg is only REACHABLE where
    # fraction_expressed < 0.70, because the later `_BROAD_EXPRESSED_FRACTION` leg returns `broad`
    # regardless. Probing at fe=0.99 therefore says nothing about the 0.50 bar at all — it was the
    # first draft of this clause and it passed for the wrong reason.
    band = {"fraction_expressed": 0.60, "fraction_highly_expressed": 0.50, "distribution_pattern": "continuous"}
    assert R._prevalence(band) == "broad"
    assert R._prevalence({**band, "fraction_highly_expressed": 0.499}) == "subset"
    assert R._prevalence({**band, "fraction_expressed": 0.99, "fraction_highly_expressed": 0.499}) == "broad", (
        "the 0.50 leg is shadowed above fraction_expressed 0.70 — if this stops holding, the clause "
        "above is probing a different rung than it claims"
    )


def test_the_card_rounding_sliver_is_unpopulated_at_median_grain_on_this_panel():
    """The issue's second question: does `tumor-rna-distribution.card.yaml`'s rounding note (the card
    declares 5.67, the method uses 5.6724) hide a real boundary flip?

    Measured answer on this panel: at the grain the note is about — a MEDIAN displaying as at or above
    the declared cutoff while the code puts it below — the sliver is EMPTY, and the nearest median is
    an order of magnitude further from 5.6724 than the sliver is wide. The note describes a real
    logical gap that no measured unit occupies.

    This is an ABSENCE assertion, so it names its denominator: a shrinking panel must red here rather
    than make the absence cheap.
    """
    medians = [r["median"] for r in ALL_ROWS]
    assert len(medians) >= 117, f"only {len(medians)} medians — the absence below would be cheap"
    occupied = [(r["target"], r["indication"], r["median"]) for r in ALL_ROWS if SLIVER[0] <= r["median"] < SLIVER[1]]
    assert occupied == [], f"a median now occupies the card's rounding sliver {SLIVER}: {occupied}"
    nearest = min(abs(m - BAR_LINEAR_ROUND) for m in medians)
    assert nearest > (SLIVER[1] - SLIVER[0]), (
        f"nearest median is {nearest:.5f} from 5.6724, inside one sliver width — the note's gap is "
        f"no longer unpopulated and #2221 must be re-read"
    )


def test_the_sliver_is_populated_at_per_sample_grain_so_the_note_is_not_vacuous():
    """The mirror of the clause above, and the reason it is not an argument for deleting the note: at
    the PER-SAMPLE grain the sliver is occupied, so a fraction computed against the card's rounded 5.67
    instead of the method's 5.6724 would differ for those units. The note is about the right hazard; it
    is only the median grain that no unit occupies.
    """
    hits = [(r["target"], r["indication"], v) for r in ALL_ROWS for v in r["win_values"] if SLIVER[0] <= v < SLIVER[1]]
    assert len(hits) >= 1, "the per-sample sliver is now empty too — re-read the card note's premise"


# ── the divergence is still the one this matrix measured ───────────────────────────────────────


def test_both_anchors_are_still_the_values_this_matrix_adjudicated():
    """If either constant moves, every number in the matrix and in the catalog rationale describes a
    tree that no longer exists. That must be a RED that says so, not a stale document.
    """
    import inspect

    from methods.depmap_expression_distribution import cli as DC
    from methods.depmap_expression_distribution import read as DR
    from methods.expression_properties import resolve as R
    from methods.tcga_gtex_expression_distribution import stats as S

    assert S.HIGH_LOG2TPM == BAR_LINEAR_ROUND
    assert R._HIGHLY_EXPRESSED_LOG2TPM == BAR_LOG_ROUND
    assert DR._HIGHLY_EXPRESSED == BAR_LOG_ROUND
    default = inspect.signature(DC.compute_summary_stats).parameters["highly_expressed_threshold"].default
    assert default == BAR_LOG_ROUND
    assert S.HIGH_LOG2TPM != R._HIGHLY_EXPRESSED_LOG2TPM, (
        "the two anchors now agree — #2221's flip matrix measured a divergence that no longer exists; "
        "re-run regenerate.py and re-read the catalog rationale before deleting anything"
    )
    # the bars NOT under test really are shared, which is what makes the high bar the odd one out
    assert S.DETECTABLE_LOG2TPM == R._EXPRESSED_LOG2TPM == DR._EXPRESSED == DETECTABLE
    assert S.MODERATE_LOG2TPM == MODERATE


@pytest.mark.parametrize(
    ("catalog_file", "entry_path", "determinant", "expected"),
    [
        ("expression.yaml", ("properties", "magnitude"), "_HIGHLY_EXPRESSED_LOG2TPM", BAR_LOG_ROUND),
        ("tumor_presence.yaml", ("properties", "patient_tumor_abundance"), "HIGH_LOG2TPM", BAR_LINEAR_ROUND),
    ],
)
def test_the_catalog_records_each_anchor_at_its_live_value_and_cites_this_matrix(
    catalog_file, entry_path, determinant, expected
):
    """Cross-file, both directions: the catalog's recorded `value` must equal the live constant, and its
    `calibration.flip_matrix` must resolve to a file that exists. A citation to a path that is not
    there is a false provenance claim, which is the failure mode this whole arc keeps finding.
    """
    doc = _load(CATALOG / catalog_file)
    node = doc
    for key in entry_path:
        assert key in node, f"{catalog_file}: no `{key}` under {entry_path}"
        node = node[key]
    dets = {d["name"]: d for d in node["determinants"]}
    assert determinant in dets, f"{catalog_file}: determinant `{determinant}` is gone — the adjudication lost its home"
    det = dets[determinant]
    assert det["value"] == expected, f"{catalog_file}::{determinant} records {det['value']}, code has {expected}"
    assert det["unit"] == "log2_tpm_plus_1"
    ref = det["calibration"]["flip_matrix"]
    assert ref, f"{catalog_file}::{determinant}: flip_matrix is empty — #2221 landed a matrix; cite it"
    assert (REPO_ROOT / ref.split(":", 1)[0]).exists(), (
        f"{catalog_file}::{determinant}: flip_matrix `{ref}` does not exist"
    )
    assert det["calibration"]["adjudication"] == "#2221"


# ── what this panel CANNOT see, measured rather than assumed ───────────────────────────────────


def _frac_off_and_high(row, bar: float) -> tuple[float, float]:
    a, _, _, above = _bands(row)
    n = row["n"]
    return a / n, (above + sum(1 for v in row["win_values"] if v >= bar)) / n


def test_the_conjuncts_this_panel_cannot_exercise_are_named_with_their_denominators():
    """INERT BY CORPUS is not SAFE BY CONTRACT, so the blind spots are recorded as numbers.

    Mutating `distribution_pattern`'s bimodal off-fraction conjunct (0.20) or its long_tail
    off-fraction conjunct (0.50) leaves every clause in this module GREEN. That is not a hole in the
    teeth — it is measured below: NO tumour unit on this panel sits in the band where either rung could
    change its answer, so the mutation cannot alter any tumour output. The cell-line arm does have 4
    units in the long_tail band, but it reaches shape through a DIFFERENT function
    (`depmap_expression_distribution/cli.py::_distribution_pattern`), so a `stats.py` mutation still
    cannot touch it.

    If the panel ever grows into one of those bands, the corresponding mutant stops being inert and
    these counts change — this clause reds, and whoever sees it should re-read the paragraph above
    rather than update the number.
    """
    tum_bimodal, tum_longtail, cell_longtail = 0, 0, 0
    for row in TUMOR_ROWS:
        fo, fh = _frac_off_and_high(row, BAR_LINEAR_ROUND)
        fm = 1.0 - fo - fh
        if row["n"] >= 8 and 0.20 <= fo < 0.30 and fh >= 0.20 and fm < max(fo, fh):
            tum_bimodal += 1
        if row["n"] >= 8 and 0.50 <= fo < 0.60 and 0.0 < fh < 0.20:
            tum_longtail += 1
    for row in CELLLINE_ROWS:
        fo, fh = _frac_off_and_high(row, BAR_LOG_ROUND)
        if row["n"] >= 8 and 0.50 <= fo < 0.60 and 0.0 < fh < 0.20:
            cell_longtail += 1
    assert len(TUMOR_ROWS) + len(CELLLINE_ROWS) >= 117
    assert tum_bimodal == 0, f"{tum_bimodal} tumour units now exercise the bimodal off-fraction rung"
    assert tum_longtail == 0, f"{tum_longtail} tumour units now exercise the tumour long_tail rung"
    assert cell_longtail == 4, (
        f"{cell_longtail} cell-line units exercise the long_tail rung (was 4) — the cell-line arm has "
        f"no independently-captured reference fixture, so shape changes there are only visible through "
        f"a between-arm difference"
    )


def test_the_moderate_count_has_no_one_sample_tooth_and_the_margin_is_measured():
    """The second measured blind spot, for the same reason and with the same remedy.

    `n_ge_moderate` IS load-bearing — `_classify_tumor_expression` cuts it at
    `BROADLY_DETECTED_MODERATE_FRACTION_MIN` inside the `detectable_fraction >= 0.7` branch — but
    perturbing it by one sample changes no output, because of the two facts asserted below: the unit
    with the closest moderate_fraction to the bar (MAGEA4/LUSC, 0.496, 2 samples away) never REACHES
    that leg, and among the units that do reach it the nearest is many samples clear of the bar.

    So a 1-off in this fixture's moderate count is inert by corpus, not covered by a tooth. A larger
    perturbation IS caught (by the cross-fixture agreement clause). If a re-capture lands a reaching
    unit near the bar, this clause reds and a per-sample tooth becomes necessary.
    """
    from methods.tcga_gtex_expression_distribution.read import BROADLY_DETECTED_MODERATE_FRACTION_MIN as BAR

    reaching = []
    for row in TUMOR_ROWS:
        fo, fh = _frac_off_and_high(row, BAR_LINEAR_ROUND)
        if (1.0 - fo) >= 0.7 and fh < 0.5:  # the leg is only reached below the broadly_high cut
            reaching.append(abs(row["n_ge_moderate"] / row["n"] - BAR) * row["n"])
    assert len(reaching) >= 31, f"only {len(reaching)} tumour units reach the moderate leg at all"
    assert min(reaching) > 5.0, (
        f"a reaching unit is now {min(reaching):.1f} samples from the moderate bar — a 1-off in "
        f"`n_ge_moderate` is no longer inert and needs its own tooth"
    )


# ── documented deliberate NON-failures: what must stay green ───────────────────────────────────


def test_a_unit_whose_two_arms_agree_stays_green():
    """The non-mover half matters as much as the movers: most of the panel must be identical between
    arms, and that agreement must not be mistaken for a broken derivation.
    """
    agree = [r for r in TUMOR_ROWS if (r["target"], r["indication"]) not in TUMOR_MOVERS]
    assert len(agree) >= 51
    for row in agree[:5]:
        a, b = _tumor_arm(row, BAR_LINEAR_ROUND), _tumor_arm(row, BAR_LOG_ROUND)
        assert a["cls"] == b["cls"]


def test_growing_the_panel_stays_green():
    """Every population clause above is a `>=` floor or a named set, so a re-capture that ADDS units
    does not red. Only a shrink, or a change to the named mover sets, does.
    """
    assert len(TUMOR_ROWS) >= 59 and len(CELLLINE_ROWS) >= 58
    assert MATRIX["_meta"]["measured"]["tumor_units"] == len(TUMOR_ROWS)
    assert MATRIX["_meta"]["measured"]["cellline_units"] == len(CELLLINE_ROWS)
