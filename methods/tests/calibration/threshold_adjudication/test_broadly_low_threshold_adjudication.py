"""#2222 — adjudication teeth for the `broadly_low` cut (epic #2210 wave 3d).

WHAT WAS ADJUDICATED, and the outcome: **documented-intentional, no threshold moved.** The prose
lives in `broadly_low_flip_matrix.json::adjudication`; this module is what makes it a claim that can
FAIL rather than a comment that rots. Three things are pinned here:

1. **Each site's cut, and the QUANTITY IT CUTS.** Pinned BEHAVIOURALLY — by driving the real
   classifier across the boundary — never by line number and never by re-reading a literal. A cut
   asserted by reading back the literal it was written from can never fail; a cut asserted by
   `classifier(bar - eps) != classifier(bar)` fails the moment the constant, the comparison operator
   or the rung ORDER moves. Both #2220's closing record and this issue's own table carry line numbers
   that have already drifted, and #2220's record transcribed `<` as `<=`.

2. **The two `0.10`s are ONE bar** (`lineage_restricted_min_fraction` and
   `_PRESENCE_FLOOR_FRACTION`) — pinned to EQUALITY, so a peer moving one alone REDS rather than
   silently splitting a deliberate convergence. The title's `0.30` is a `broadly_high` bar of
   OPPOSITE polarity and is pinned as such.

3. **The two-arm counterfactual**, re-derived. Arm A is the PRODUCTION call; arm B is the same
   ladder with exactly one rung re-based on a sibling's bar. The counterfactual ladder is required
   to reproduce the production classifier bit-for-bit in its status-quo configuration — without that
   parity clause an arm-B number is unfalsifiable.

Per SK#2091 nothing here asserts anything about any verdict in either direction. Every clause is a
statement about a datum: what quantity a cut is applied to, and what a stated alternative would cost
on measured data.

OFFLINE — committed fixtures only, no S3, no credentials. Runs in CI.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
MATRIX_PATH = HERE / "broadly_low_flip_matrix.json"
REC = HERE.parent / "recomputation"
_METHODS_ROOT = HERE.parents[2]

# ONE import path for both the generator and this module — the counterfactual ladders must be THE
# ONES THE FIXTURE WAS GENERATED WITH and must see THE SAME code objects as the production
# classifiers, or the parity clause below proves nothing about arm B. The generator owns the
# `onc_methods.*` binding shim (see its `_worktree_methods_first` docstring: a `/tmp` worktree otherwise
# resolves these modules to the PRIMARY CHECKOUT via the editable install, and every mutation
# survives). Loaded by path because this file is a script, not an importable package module.
_spec = importlib.util.spec_from_file_location("adj2222_regen", HERE / "regenerate_broadly_low_flip_matrix.py")
REGEN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(REGEN)

DEP_READ = REGEN.DEP_READ
DEP_CLI = REGEN.DEP_CLI
TUM_READ = REGEN.TUM_READ
TUM_STATS = REGEN.TUM_STATS
RESOLVE = REGEN.RESOLVE

MATRIX = json.loads(MATRIX_PATH.read_text())

# --- anti-vacuity floors. Each names its subject inside the assert with len() so the static
# floor-reader in skills/tests can see it, and each is `>=` where the panel may legitimately grow.
MIN_STRATA = 200
MIN_STRATIFIED_TARGETS = 8
MIN_LINEAGES = 15
MIN_PAN_CANCER_TARGETS = 8
MIN_TUMOUR_ANCHORS = 8
MIN_TUMOUR_PANEL_PAIRS = 40
MIN_SITES = 6
EPS = 1e-9


def _stratified_rows():
    return MATRIX["grain_stratified"]["rows"]


def _site(site_id: str) -> dict:
    hits = [s for s in MATRIX["sites"] if s["site_id"] == site_id]
    assert len(hits) == 1, f"expected exactly one `{site_id}` entry in sites, found {len(hits)}"
    return hits[0]


def _load_vector(name: str):
    """Reconstruct (tpm_by_model, lineage-per-model) from the committed parquet, exactly as
    ../recomputation/test_expression_distribution_recomputation.py does."""
    t = pq.read_table(REC / "expression_vectors" / name, columns=["model_id", "log2tpm", "lineage"])
    mids = t.column("model_id").to_pylist()
    log2 = t.column("log2tpm").to_pylist()
    lins = t.column("lineage").to_pylist()
    meta = {m: {"OncotreeLineage": (float("nan") if lin is None else lin)} for m, lin in zip(mids, lins)}
    return dict(zip(mids, log2)), meta, lins, mids


def _drive_stratified(tpm, lins, mids, target):
    """Drive the REAL `read_stratified_expression` over every lineage stratum clearing the n-floor,
    with its only I/O (`_cached_tpm`) bound to the committed vector. Restores the original binding."""
    original = DEP_READ._cached_tpm
    out = {}
    try:
        DEP_READ._cached_tpm = lambda _t, _p=None, _tpm=tpm: (_tpm, False)  # noqa: E731
        by: dict[str, set] = {}
        for lin, m in zip(lins, mids):
            if lin is not None:
                by.setdefault(lin, set()).add(m)
        for lin, members in sorted(by.items()):
            if len(members) < DEP_READ.SUBGROUP_N_FLOOR:
                continue
            out[lin] = DEP_READ.read_stratified_expression(
                target, lin, _sample_id_filter=members, _stratum_evaluated=True, release_pin="26q1"
            )
    finally:
        DEP_READ._cached_tpm = original
    return out


PAN_TARGETS = [pytest.param(r["target"], id=r["target"]) for r in MATRIX["grain_pan_cancer"]["rows"]]


# ---------------------------------------------------------------------------------------------
# 0. Provenance — is this suite even looking at THIS tree?
# ---------------------------------------------------------------------------------------------
def test_the_code_under_test_is_the_code_in_this_tree():
    """FIRST clause, because every other clause in this file is worthless without it.

    `oncology-analysis-methods` is installed EDITABLE against the PRIMARY CHECKOUT, and
    `methods/conftest.py` imports `onc_methods._common.live_data_skip` during COLLECTION — binding the
    `onc_methods` package (with `__path__` on the primary checkout) into `sys.modules` before any test
    module runs. A later `sys.path.insert` cannot dislodge it. Result: run this suite from a `/tmp`
    worktree and it exercises TRUNK while reporting green for the branch.

    MEASURED 2026-09-30, this file, before the shim: six independent mutations of the six constants
    this module pins (site 1's 0.3, its `<`, site 2's 1.0, site 3's 0.10, site 4's 0.10, the 0.30)
    ALL SURVIVED at 42/42 passed. Not one clause noticed. This assert is what makes the difference
    detectable; do not delete it because it "obviously holds".
    """
    loaded = REGEN._loaded_from()
    assert set(loaded) == set(REGEN.MODULE_NAMES), "the generator's module set drifted from its map"
    strays = {a: f for a, f in loaded.items() if not Path(f).resolve().is_relative_to(_METHODS_ROOT)}
    assert not strays, (
        "these modules resolved OUTSIDE this tree, so the suite is testing another checkout and "
        f"every threshold clause below is vacuous: {strays}"
    )
    # The generator and this module must share code OBJECTS, not merely equal file paths — otherwise
    # the arm-B parity clause compares one tree's ladder against another tree's classifier.
    assert REGEN.DEP_READ is DEP_READ and REGEN.DEP_CLI is DEP_CLI and REGEN.TUM_READ is TUM_READ


# ---------------------------------------------------------------------------------------------
# 1. Anti-vacuity — a zeroed or shrunken matrix must never read as green.
# ---------------------------------------------------------------------------------------------
def test_matrix_is_not_vacuous():
    strata = _stratified_rows()
    assert len(strata) >= MIN_STRATA, f"stratified grain has {len(strata)} strata, floor is {MIN_STRATA}"
    assert len({r["target"] for r in strata}) >= MIN_STRATIFIED_TARGETS
    assert len({r["stratum"] for r in strata}) >= MIN_LINEAGES
    assert len(MATRIX["grain_pan_cancer"]["rows"]) >= MIN_PAN_CANCER_TARGETS
    assert len(MATRIX["grain_tumour"]["anchors"]) >= MIN_TUMOUR_ANCHORS
    assert len(MATRIX["grain_tumour"]["panel"]) >= MIN_TUMOUR_PANEL_PAIRS
    assert len(MATRIX["sites"]) >= MIN_SITES
    # A panel that has collapsed into ONE class cannot discriminate between the arms, which is the
    # failure mode a bare row count cannot see.
    assert len({r["A"] for r in strata}) >= 3, f"arm A spans only {sorted({r['A'] for r in strata})}"
    assert sum(1 for r in strata if r["A"] == "broadly_low") > 0, "no broadly_low row — nothing to adjudicate"


def test_every_excluded_row_is_named_with_a_reason():
    """Protocol rule 2: a row whose stored inputs cannot decide its arm is EXCLUDED BY NAME. An
    unexplained shrink in a row count is indistinguishable from a coverage loss."""
    excluded = MATRIX["grain_tumour"]["excluded"]
    assert MATRIX["grain_tumour"]["measured"]["panel_pairs_excluded"] == len(excluded)
    for row in excluded:
        assert row.get("reason"), f"excluded row {row} carries no reason"
        assert row.get("target") and row.get("code")


# ---------------------------------------------------------------------------------------------
# 2. Each cut pinned BEHAVIOURALLY, together with the quantity it cuts.
# ---------------------------------------------------------------------------------------------
def test_site1_cut_is_0_3_on_the_tumour_detectable_fraction_with_a_STRICT_comparison():
    bar = _site("site1_tumour_detectable_fraction")["constant"]
    assert bar == 0.3
    # Below the bar -> broadly_low; AT the bar -> NOT broadly_low. The strictness is the half #2220's
    # closing record got wrong (it recorded `<=`), and it decides the call at exactly det == 0.3.
    assert TUM_READ._classify_tumor_expression(bar - EPS, 0.0, "continuous") == "broadly_low"
    assert TUM_READ._classify_tumor_expression(bar, 0.0, "continuous") == "broadly_moderate"
    # The quantity is the DETECTABLE fraction, whose floor is TPM~1 — not the high fraction.
    assert TUM_STATS.DETECTABLE_LOG2TPM == 1.0
    assert _site("site1_tumour_detectable_fraction")["detection_floor_log2tpm"] == TUM_STATS.DETECTABLE_LOG2TPM
    # broadly_low is a GUARDED branch, not the fall-through: the shape rung pre-empts it, so a pair
    # BELOW the bar is not necessarily broadly_low. This is why "broadly_low is the fall-through, so
    # the conservative value belongs on it" is true of site 2 and NOT of site 1.
    assert TUM_READ._classify_tumor_expression(0.25, 0.15, "long_tail") == "subset_high"
    assert TUM_READ._classify_tumor_expression(0.9, 0.0, "continuous") != "broadly_low"


def test_site2_cut_is_the__EXPRESSED_MEDIAN_and_broadly_low_is_its_true_fall_through():
    bar = DEP_READ._EXPRESSED
    assert bar == _site("site2_cellline_stratum_median")["constant"] == 1.0
    assert DEP_READ._expression_class(bar - EPS) == "broadly_low"
    assert DEP_READ._expression_class(bar) == "broadly_detected"
    assert DEP_READ._expression_class(DEP_READ._HIGHLY_EXPRESSED) == "broadly_high"
    assert DEP_READ._expression_class(None) == "insufficient"
    # The quantity is a LEVEL: the classifier takes ONE argument and it is a median. A fraction
    # cannot be handed to it, which is the unit mismatch stated as a signature.
    params = list(inspect.signature(DEP_READ._expression_class).parameters)
    assert params == ["median"], f"site 2's classifier signature moved: {params}"
    # broadly_low IS the fall-through here — nothing follows it. Anything below the middle rung, at
    # any level, lands on the least-evidenced token.
    assert {DEP_READ._expression_class(v) for v in (0.0, 0.001, 0.5, 0.999)} == {"broadly_low"}


def test_site3_cut_is_the_LOWER_EDGE_of_the_lineage_restricted_band_not_a_free_knob():
    sig = inspect.signature(DEP_CLI._classify_expression).parameters
    bar = sig["lineage_restricted_min_fraction"].default
    assert bar == _site("site3_cellline_pancancer_fraction")["constant"] == 0.10

    def call(fe, fh=0.0, n_lin=1):
        return DEP_CLI._classify_expression(fe, fh, n_lin, 0.70, 0.30, bar, 0.70)

    assert call(bar - EPS) == "broadly_low"
    # AT the bar the row does not become broadly_moderate-by-fall-through: it enters the
    # lineage_restricted band. Raising this number therefore does NOT enlarge broadly_low at the
    # expense of a middling token — it EATS lineage_restricted from below. That is the whole reason
    # harmonising it up to site 1's 0.3 is refuted.
    assert call(bar) == "lineage_restricted"
    assert call(bar, n_lin=0) == "broadly_moderate"  # the M1 enrichment guard, not this bar
    counterfactual = DEP_CLI._classify_expression(0.2625, 0.0, 1, 0.70, 0.30, 0.30, 0.70)
    assert counterfactual == "broadly_low", (
        "at a harmonised 0.30 floor a pan-cancer fraction of 0.2625 (CEACAM5, measured) leaves "
        f"lineage_restricted for broadly_low; got {counterfactual}"
    )
    assert DEP_CLI._classify_expression(0.2625, 0.0, 1, 0.70, 0.30, bar, 0.70) == "lineage_restricted"


def test_site4_is_a_presence_floor_in_a_DIFFERENT_vocabulary_not_a_broadly_low_cut():
    bar = RESOLVE._PRESENCE_FLOOR_FRACTION
    assert bar == _site("site4_expression_property_presence_floor")["constant"] == 0.10
    below = {"fraction_expressed": bar - EPS, "median_log2tpm_panel": 0.0}
    at = {"fraction_expressed": bar, "median_log2tpm_panel": 0.0}
    assert RESOLVE._presence(below) == "absent"
    assert RESOLVE._presence(at) == "weak"
    # The token it produces is not in the expression_class vocabulary at all, so it is not a twin of
    # broadly_low and cannot be "harmonised" with one.
    assert "broadly_low" not in RESOLVE.VALID_VALUES["presence"]
    assert RESOLVE._presence(below) in RESOLVE.VALID_VALUES["presence"]
    # Conjunctive: the fraction alone does not carry it — an expressing median blocks `absent`.
    assert RESOLVE._presence({"fraction_expressed": bar - EPS, "median_log2tpm_panel": 5.0}) != "absent"


def test_the_two_0_10_bars_are_ONE_bar_and_must_move_together():
    """site 3's `lineage_restricted_min_fraction` and site 4's `_PRESENCE_FLOOR_FRACTION` are a
    deliberate CONVERGENCE, not a coincidence: resolve.py's header says it mirrors the cli knobs.
    Pinned to EQUALITY so splitting them REDS instead of silently creating a real divergence."""
    cli_bar = inspect.signature(DEP_CLI._classify_expression).parameters["lineage_restricted_min_fraction"].default
    assert cli_bar == RESOLVE._PRESENCE_FLOOR_FRACTION, (
        f"the cell-line breadth floor split: expression_class uses {cli_bar}, "
        f"expression_property presence uses {RESOLVE._PRESENCE_FLOOR_FRACTION}. These are one bar on one "
        "quantity over one panel; if the split is intended, say so in the property catalog first."
    )
    # And they agree on the measured panel, not just as literals.
    rows = MATRIX["grain_pan_cancer"]["rows"]
    agree = [r for r in rows if (r["site3_expression_class"] == "broadly_low") == (r["site4_presence"] == "absent")]
    assert len(agree) == len(rows), "site3 broadly_low and site4 presence=absent disagree on " + str(
        [r["target"] for r in rows if r not in agree]
    )
    assert MATRIX["grain_pan_cancer"]["measured"]["site3_low_iff_site4_absent"] == len(rows)


def test_the_0_30_in_the_issue_title_is_a_broadly_HIGH_bar_of_opposite_polarity():
    """The issue title reads `0.3 vs 0.10 vs 0.30`. Exhaustively, the only `0.30` in the scoped
    classifier code is `broadly_high_fraction` — three lines above the `0.10` in the SAME defaults
    block — and `_PRESENCE_SUPPORTED_MEDIAN_FRACTION`, which RESCUES upward. Neither cuts
    broadly_low. Proven by construction, not asserted in a comment."""
    sig = inspect.signature(DEP_CLI._classify_expression).parameters
    high_bar = sig["broadly_high_fraction"].default
    assert high_bar == _site("not_a_broadly_low_cut__broadly_high_fraction")["constant"] == 0.30
    # It gates the promotion to broadly_high on the HIGHLY-expressed fraction, above a broad panel.
    assert DEP_CLI._classify_expression(0.8, high_bar, 1, 0.70, high_bar, 0.10, 0.70) == "broadly_high"
    assert DEP_CLI._classify_expression(0.8, high_bar - EPS, 1, 0.70, high_bar, 0.10, 0.70) == "broadly_moderate"
    # Moving it cannot produce or remove a single broadly_low row, at any breadth.
    for fe in (0.0, 0.05, 0.10, 0.3, 0.5, 0.69, 0.7, 1.0):
        for cf in (0.30, 0.90):
            a = DEP_CLI._classify_expression(fe, 0.2, 1, 0.70, 0.30, 0.10, 0.70) == "broadly_low"
            b = DEP_CLI._classify_expression(fe, 0.2, 1, 0.70, cf, 0.10, 0.70) == "broadly_low"
            assert a == b, f"broadly_high_fraction={cf} changed a broadly_low call at fe={fe}"
    sup = RESOLVE._PRESENCE_SUPPORTED_MEDIAN_FRACTION
    assert sup == 0.30
    assert RESOLVE._presence({"fraction_expressed": sup, "median_log2tpm_panel": 5.0}) == "supported"
    assert RESOLVE._presence({"fraction_expressed": sup - EPS, "median_log2tpm_panel": 5.0}) == "weak"


# ---------------------------------------------------------------------------------------------
# 3. The counterfactual is only worth something if its ladder reproduces production.
# ---------------------------------------------------------------------------------------------
def test_counterfactual_ladders_reproduce_production_in_their_status_quo_configuration():
    """Arm B is generated by a COPY of each ladder with one rung parameterised. If the copy has
    drifted from production anywhere else, every arm-B number is noise. Checked on the measured rows
    AND on a synthetic boundary sweep, so the clause does not depend on the panel covering a rung."""
    for median in (None, -1.0, 0.0, 0.5, 1.0 - EPS, 1.0, 2.0, 5.0 - EPS, 5.0, 9.0):
        for fe in (None, 0.0, 0.05, 0.5, 1.0):
            assert REGEN.stratified_ladder(median, fe, ("median", None)) == DEP_READ._expression_class(median), (
                f"stratified counterfactual ladder diverged from production at median={median}"
            )
    for row in _stratified_rows():
        assert REGEN.stratified_ladder(row["median_log2tpm"], row["fraction_expressed"], ("median", None)) == row["A"]

    low_bar = _site("site1_tumour_detectable_fraction")["constant"]
    for det in (None, 0.0, 0.05, 0.29, 0.3, 0.5, 0.69, 0.7, 0.9, 1.0):
        for high in (None, 0.0, 0.05, 0.1, 0.49, 0.5, 0.9):
            for pat in ("continuous", "bimodal", "long_tail", None):
                for mod in (None, 0.0, 0.5, 0.9):
                    assert REGEN.tumour_ladder(det, high, pat, mod, low_bar=low_bar) == (
                        TUM_READ._classify_tumor_expression(det, high, pat, mod)
                    ), f"tumour counterfactual ladder diverged at det={det} high={high} pat={pat} mod={mod}"


# ---------------------------------------------------------------------------------------------
# 4. Arm A re-derives from the IRREPRODUCIBLE raw input through the production reader.
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("target", PAN_TARGETS)
def test_stratified_arm_a_rederives_from_the_committed_vector(target: str):
    rows = [r for r in _stratified_rows() if r["target"] == target]
    assert len(rows) > 0, f"no stratified rows for {target} — matrix and vector set disagree"
    vector_name = rows[0]["vector_fixture"].rsplit("/", 1)[-1]
    tpm, _meta, lins, mids = _load_vector(vector_name)
    recs = _drive_stratified(tpm, lins, mids, target)
    assert set(recs) == {r["stratum"] for r in rows}, (
        f"{target}: strata clearing the n-floor drifted — reader {sorted(set(recs))} vs matrix "
        f"{sorted(r['stratum'] for r in rows)}"
    )
    for row in rows:
        rec = recs[row["stratum"]]
        assert rec["subgroup_n"] == row["subgroup_n"]
        assert rec["median_log2tpm"] == row["median_log2tpm"]
        assert rec["fraction_expressed"] == row["fraction_expressed"]
        assert rec["evidence_state"] == row["evidence_state"]
        assert rec["expression_class"] == row["A"], (
            f"{target}/{row['stratum']}: arm A re-derived {rec['expression_class']} != matrix {row['A']}"
        )


@pytest.mark.parametrize("target", PAN_TARGETS)
def test_pan_cancer_row_rederives_through_compute_summary_stats(target: str):
    row = next(r for r in MATRIX["grain_pan_cancer"]["rows"] if r["target"] == target)
    tpm, meta, _l, _m = _load_vector(row["vector_fixture"].rsplit("/", 1)[-1])
    assert len(tpm) == row["n_cell_lines"], "panel size drifted from the matrix — fixture truncated?"
    s = DEP_CLI.compute_summary_stats(tpm, meta)
    assert s["median_log2tpm_panel"] == row["median_log2tpm_panel"]
    assert s["fraction_expressed"] == row["fraction_expressed"]
    assert s["expression_class"] == row["site3_expression_class"]
    assert DEP_READ._expression_class(s["median_log2tpm_panel"]) == row["site2_median_ladder_class"]
    assert RESOLVE._presence(s) == row["site4_presence"]


def test_teeth_silencing_a_stratum_moves_its_rederived_class():
    """If the clauses above compared the matrix to a copy of its own output they would be green with
    the reader broken. Perturb the raw input and the re-derived value must move."""
    rows = _stratified_rows()
    row = max((r for r in rows if r["A"] != "broadly_low"), key=lambda r: r["fraction_expressed"])
    tpm, _meta, lins, mids = _load_vector(row["vector_fixture"].rsplit("/", 1)[-1])
    mutated = {m: 0.0 for m in tpm}
    recs = _drive_stratified(mutated, lins, mids, row["target"])
    rec = recs[row["stratum"]]
    assert rec["fraction_expressed"] == 0.0 != row["fraction_expressed"]
    assert rec["expression_class"] == "broadly_low" != row["A"]


# ---------------------------------------------------------------------------------------------
# 5. The unit mismatch, measured — and its exact fraction equivalent.
# ---------------------------------------------------------------------------------------------
def test_a_median_below_the_detection_floor_implies_a_fraction_of_at_most_one_half():
    """This is what makes the median bar COMMENSURABLE with the two fraction bars, and therefore
    what makes the adjudication possible at all. If more than half the stratum sits above the floor,
    both central order statistics do, so the (interpolated) median does too. Hence site 2's
    broadly_low can fire ONLY at fraction_expressed <= 0.5 — and may fire anywhere in (0, 0.5],
    i.e. its EFFECTIVE breadth bar is 0.5: 5x site 3's 0.10 and 1.67x site 1's 0.3."""
    rows = _stratified_rows()
    low = [r for r in rows if r["A"] == "broadly_low"]
    assert len(low) > 0
    over = [r for r in low if r["fraction_expressed"] > 0.5 + EPS]
    assert not over, f"median<floor with fraction>0.5 — the bound is wrong: {over[:3]}"
    under = [r for r in rows if r["A"] != "broadly_low" and r["fraction_expressed"] < 0.5 - EPS]
    assert not under, f"median>=floor with fraction<0.5 on measured data: {under[:3]}"
    # The bound is reached, not merely respected — otherwise it would be a vacuous statement about a
    # panel that happens to sit far from 0.5.
    assert max(r["fraction_expressed"] for r in low) > 0.30, (
        "no broadly_low stratum reaches a third of its panel; the divergence would be inert here"
    )
    # The single ambiguous point, stated as a constructed witness rather than left implicit: at
    # EXACTLY fraction 0.5 with even n the interpolated median can land either side of the floor.
    floor = DEP_READ._EXPRESSED
    assert DEP_READ._expression_class(float(np.median([0.9, floor + 0.2]))) == "broadly_detected"
    assert DEP_READ._expression_class(float(np.median([0.0, floor + 0.2]))) == "broadly_low"


def test_rebasing_site2s_low_rung_on_a_fraction_moves_strata_in_ONE_direction_only():
    """Measured, both directions: adopting either sibling's bar only ever REMOVES strata from
    broadly_low. So the median basis is strictly the most generous of the three — which on a TRUE
    fall-through puts the least-evidenced label at the most reachable position."""
    rows = _stratified_rows()
    for key, arm in MATRIX["grain_stratified"]["arms"].items():
        movers = [r for r in rows if r[key] != r["A"]]
        assert len(movers) == arm["movers"]
        assert arm["enter_broadly_low"] == 0, f"{key}: {arm['enter_broadly_low']} strata ENTER broadly_low"
        assert all(r["A"] == "broadly_low" for r in movers), f"{key}: a mover left a non-low class"
        # Non-movers byte-identical (protocol rule 5).
        assert all(r[key] == r["A"] for r in rows if r not in movers)
        assert arm["byte_identical"] == len(rows) - len(movers)
        assert sorted(arm["mover_ids"]) == sorted(f"{r['target']}/{r['stratum']}" for r in movers)
    # Reach: the divergence is not a rounding artefact on a handful of rows.
    assert MATRIX["grain_stratified"]["arms"]["B_0.10"]["movers"] >= 20
    assert MATRIX["grain_stratified"]["arms"]["B_0.30"]["movers"] >= 10


def test_the_median_ladder_never_calls_broadly_low_LESS_often_than_the_fraction_ladder():
    """Same claim at the pan-cancer grain, where site 2's basis and site 3's basis read the IDENTICAL
    vector — the cleanest statement of the mismatch. The named targets are the adjudication's
    evidence, so a panel change that removes them must RED and be re-argued."""
    m = MATRIX["grain_pan_cancer"]["measured"]
    # Re-derive both directions from the per-row columns rather than reading the stored aggregate —
    # a summary list is a DERIVED value, and a clause that only reads it back can never fail.
    rows = {r["target"]: r for r in MATRIX["grain_pan_cancer"]["rows"]}
    low2 = {t for t, r in rows.items() if r["site2_median_ladder_class"] == "broadly_low"}
    low3 = {t for t, r in rows.items() if r["site3_expression_class"] == "broadly_low"}
    assert sorted(low3 - low2) == sorted(m["site3_broadly_low_where_site2_is_not"]) == [], (
        "the fraction basis now calls broadly_low where the median basis does not — the divergence "
        f"changed DIRECTION and finding 3/4 must be re-derived: {sorted(low3 - low2)}"
    )
    assert sorted(low2 - low3) == sorted(m["site2_broadly_low_where_site3_is_not"]), (
        "the matrix's recorded divergence set no longer matches its own per-target columns: "
        f"re-derived {sorted(low2 - low3)} vs recorded {sorted(m['site2_broadly_low_where_site3_is_not'])}"
    )
    assert len(low2 - low3) >= 3
    for t in ("CEACAM5", "MSLN", "TACSTD2"):
        assert t in m["site2_broadly_low_where_site3_is_not"], f"{t} no longer witnesses the divergence"
        assert rows[t]["site2_median_ladder_class"] == "broadly_low"
        assert rows[t]["site3_expression_class"] == "lineage_restricted"
        assert rows[t]["n_lineage_restricted_lineages"] >= 1, (
            f"{t}: the lineage_restricted call rests on an enriched lineage; without one the "
            "'a positive signal is being sent to the lowest tier' argument does not hold"
        )


# ---------------------------------------------------------------------------------------------
# 6. The tumour arm — what harmonising site 1 DOWN would cost.
# ---------------------------------------------------------------------------------------------
def test_tumour_anchors_rederive_their_live_captured_class():
    anchors = MATRIX["grain_tumour"]["anchors"]
    for row in anchors:
        a = json.loads((REC / "anchors" / row["anchor"]).read_text())
        cls = TUM_READ._classify_tumor_expression(
            a["expected_detectable_fraction"],
            a["expected_high_fraction"],
            a["expected_distribution_pattern"],
            a["expected_moderate_fraction"],
        )
        assert cls == a["expected_tumor_expression_class"] == row["pinned_class"] == row["A"], (
            f"{row['target']}/{row['code']}: re-derived {cls} != live-captured {row['pinned_class']}"
        )
    assert MATRIX["grain_tumour"]["measured"]["anchors_reproducing_their_pinned_class"] == len(anchors)


def test_tumour_arm_b_movers_are_exactly_the_three_named_broadly_low_reads():
    """Harmonising site 1 DOWN to the cell-line sibling's 0.10 EMPTIES the panel's broadly_low class.
    Each mover is justified individually in the PR body and in the matrix's `adjudication`; this
    clause pins the identities so the justification cannot silently stop matching the evidence."""
    bar = RESOLVE._PRESENCE_FLOOR_FRACTION  # == site 3's 0.10, pinned equal above
    key = f"B_{bar:.2f}"
    rows = MATRIX["grain_tumour"]["panel"] + MATRIX["grain_tumour"]["anchors"]
    movers = [r for r in rows if r[key] != r["A"]]
    assert {f"{r['target']}/{r['code']}" for r in movers} == {"TERT/SKCM", "DLK1/LIHC", "CTAG1B/SKCM"}
    for r in movers:
        assert r["A"] == "broadly_low" and r[key] == "broadly_moderate"
        assert bar <= r["det"] < _site("site1_tumour_detectable_fraction")["constant"]
        # Re-derive both arms rather than trusting the stored columns.
        assert TUM_READ._classify_tumor_expression(r["det"], r["high"], r["pat"], r.get("mod")) == r["A"]
        assert REGEN.tumour_ladder(r["det"], r["high"], r["pat"], r.get("mod"), low_bar=bar) == r[key]
    assert sum(1 for r in rows if r["A"] == "broadly_low") == len(movers), (
        "the panel retains a broadly_low read at the harmonised bar; the 'it empties the class' "
        "argument in the adjudication no longer holds"
    )
    assert all(r[key] == r["A"] for r in rows if r not in movers)


def test_the_shape_rung_preempts_the_low_bar_on_measured_data():
    """MAGEA3/LUAD sits BELOW site 1's 0.3 bar (det 0.2907) and is still not broadly_low, because the
    long_tail + high_fraction>=0.1 rung fires first. So site 1's 0.3 is a RESIDUAL minority bar after
    shape has had its say — a different object from site 2's unconditional fall-through, and the
    reason the two cannot be compared as bare numbers even after unit conversion."""
    rows = MATRIX["grain_tumour"]["panel"]
    hits = [
        r
        for r in rows
        if r["det"] is not None
        and r["det"] < _site("site1_tumour_detectable_fraction")["constant"]
        and r["A"] != "broadly_low"
    ]
    assert hits, "no measured pair below the bar escapes broadly_low — the pre-emption is unexercised"
    for r in hits:
        assert r["A"] == "subset_high"
        assert TUM_READ._classify_tumor_expression(r["det"], r["high"], r["pat"]) == "subset_high"


# ---------------------------------------------------------------------------------------------
# 7. Recorded findings that are NOT fixed here, pinned so they cannot rot into folklore.
# ---------------------------------------------------------------------------------------------
def test_site3_ladder_is_exhaustive_so_its_documented_fall_through_is_unreachable():
    """`_classify_expression`'s final `return "broadly_moderate"` is commented '70-90% range
    fallback'. That band is already claimed by the `>= 0.70` branch, so the line is unreachable for
    ANY fraction in [0, 1] — reachable only for a NaN, which would launder an unmeasured panel into a
    measured middling call. INERT today (the sole caller returns early on an empty panel), so it is
    recorded as a finding rather than fixed inside a no-change adjudication."""
    for fe in np.linspace(0.0, 1.0, 2001):
        for fh in (0.0, 0.30, 1.0):
            for n_lin in (0, 1):
                got = DEP_CLI._classify_expression(float(fe), fh, n_lin, 0.70, 0.30, 0.10, 0.70)
                assert got in ("broadly_high", "broadly_moderate", "lineage_restricted", "broadly_low")
    # The fall-through is reached ONLY via a non-finite fraction — the documented band never gets there.
    assert DEP_CLI._classify_expression(0.8, 0.0, 1, 0.70, 0.30, 0.10, 0.70) == "broadly_moderate"  # branch 1
    assert DEP_CLI._classify_expression(float("nan"), 0.0, 1, 0.70, 0.30, 0.10, 0.70) == "broadly_moderate"
    assert _site("site3_cellline_pancancer_fraction")["dead_fall_through"]


def test_the_stratified_reader_emits_the_fraction_its_own_classifier_ignores():
    """The premise of finding 3/4: the breadth input is not missing from site 2's record, only from
    its classifier. A future re-basing therefore needs no new measurement — which is why the remedy
    was routed up as a design choice rather than blocked on data."""
    row = _stratified_rows()[0]
    tpm, _meta, lins, mids = _load_vector(row["vector_fixture"].rsplit("/", 1)[-1])
    rec = _drive_stratified(tpm, lins, mids, row["target"])[row["stratum"]]
    assert "fraction_expressed" in rec and rec["fraction_expressed"] is not None
    assert "median_log2tpm" in rec and rec["median_log2tpm"] is not None
    # ... and the classifier reads only the median (signature pinned above), so the two can disagree.
    assert rec["expression_class"] == DEP_READ._expression_class(rec["median_log2tpm"])


def test_the_adjudication_record_is_present_and_names_its_outcome():
    """`document-all / adjudicate-flagged`: silence is not an outcome. The verdict and each finding
    must exist in the committed evidence, not only in a PR body that no future reader will find."""
    adj = MATRIX["adjudication"]
    assert adj["outcome"].startswith("DOCUMENTED-INTENTIONAL")
    for k in (
        "finding_1_the_title_s_triple_is_not_three_settings_of_one_bar",
        "finding_2_0_3_vs_0_10_is_commensurable_and_the_spread_is_required",
        "finding_3_the_unit_mismatch_is_real_but_RESOLVABLE_and_the_divergence_is_0_5_vs_0_3_vs_0_10",
        "finding_4_what_that_costs_on_measured_data",
        "why_no_change_here",
        "catalog_write_deferred",
    ):
        assert adj.get(k), f"adjudication is missing `{k}`"
    assert MATRIX["_meta"]["regenerated_by"].endswith("regenerate_broadly_low_flip_matrix.py")
    assert (HERE / MATRIX["_meta"]["regenerated_by"].rsplit("/", 1)[-1]).exists()


def test_no_production_threshold_was_moved_by_this_adjudication():
    """The outcome is `no change`, and the four constants are the subject of the claim. Pinned here
    as a SET so that a later PR which does move one cannot leave this adjudication's prose standing
    as if it still described the code."""
    sig = inspect.signature(DEP_CLI._classify_expression).parameters
    observed = {
        "site1_tumour_broadly_low_bar": 0.3
        if TUM_READ._classify_tumor_expression(0.3, 0.0, "continuous") != "broadly_low"
        and TUM_READ._classify_tumor_expression(0.3 - EPS, 0.0, "continuous") == "broadly_low"
        else None,
        "site2_stratum_median_floor": DEP_READ._EXPRESSED,
        "site3_pancancer_fraction_floor": sig["lineage_restricted_min_fraction"].default,
        "site4_presence_floor": RESOLVE._PRESENCE_FLOOR_FRACTION,
    }
    assert observed == {
        "site1_tumour_broadly_low_bar": 0.3,
        "site2_stratum_median_floor": 1.0,
        "site3_pancancer_fraction_floor": 0.10,
        "site4_presence_floor": 0.10,
    }, f"a broadly_low determinant moved; re-run the flip matrix before editing the adjudication: {observed}"
