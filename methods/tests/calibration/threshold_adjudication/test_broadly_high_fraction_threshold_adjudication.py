"""#2273 — adjudication teeth for the `broadly_high_fraction` cut (epic #2210).

WHAT WAS ADJUDICATED, and the outcome: **documented-intentional, no threshold moved.** The prose
lives in `broadly_high_fraction_flip_matrix.json::adjudication`; this module is what makes it a claim
that can FAIL rather than a comment that rots. Sibling of `test_broadly_low_threshold_adjudication.py`
(#2222); shares its fixtures, its worktree-methods-first shim, and its discipline.

Pinned here:

1. **Each site's cut, and the QUANTITY IT CUTS**, BEHAVIOURALLY — by driving the real classifier
   across the boundary, never by reading back the literal it was written from (a cut asserted by
   reading its own literal can never fail). Site A's 0.30 is GUARDED (inside `frac_expressed >= 0.70`);
   sites B and C's 0.50 fire UNGUARDED. Site A and site B read the IDENTICAL `fraction_highly_expressed`
   field at the IDENTICAL 5.0 floor; site C reads the same concept on another denominator and a
   different 5.6724 floor.

2. **The counterfactual**, re-derived. Arm A is the PRODUCTION call; arm B is the same ladder with
   exactly one bar re-based on a sibling's value, required to reproduce production bit-for-bit at its
   status-quo bar.

3. **No production threshold moved** — the three constants pinned as a SET.

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

import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
MATRIX_PATH = HERE / "broadly_high_fraction_flip_matrix.json"
REC = HERE.parent / "recomputation"
_METHODS_ROOT = HERE.parents[2]

# ONE import path for both the generator and this module — the counterfactual ladders must see the
# SAME code objects as the production classifiers (the generator owns the `methods.*` binding shim;
# see its `_worktree_methods_first` docstring). Loaded by path because it is a script.
_spec = importlib.util.spec_from_file_location(
    "adj2273_regen", HERE / "regenerate_broadly_high_fraction_flip_matrix.py"
)
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
MIN_PAN_CANCER_TARGETS = 8
MIN_TUMOUR_ANCHORS = 8
MIN_TUMOUR_PANEL_PAIRS = 20
MIN_SITES = 4
EPS = 1e-9


def _site(site_id: str) -> dict:
    hits = [s for s in MATRIX["sites"] if s["site_id"] == site_id]
    assert len(hits) == 1, f"expected exactly one `{site_id}` entry in sites, found {len(hits)}"
    return hits[0]


def _load_vector(name: str):
    """Reconstruct (tpm_by_model, meta) from the committed parquet, exactly as
    ../recomputation/test_expression_distribution_recomputation.py does."""
    t = pq.read_table(REC / "expression_vectors" / name, columns=["model_id", "log2tpm", "lineage"])
    mids = t.column("model_id").to_pylist()
    log2 = t.column("log2tpm").to_pylist()
    lins = t.column("lineage").to_pylist()
    meta = {m: {"OncotreeLineage": (float("nan") if lin is None else lin)} for m, lin in zip(mids, lins)}
    return dict(zip(mids, log2)), meta


PAN_TARGETS = [pytest.param(r["target"], id=r["target"]) for r in MATRIX["grain_pan_cancer"]["rows"]]


# ---------------------------------------------------------------------------------------------
# 0. Provenance — is this suite even looking at THIS tree?
# ---------------------------------------------------------------------------------------------
def test_the_code_under_test_is_the_code_in_this_tree():
    """FIRST clause, because every other clause is worthless without it. `methods` is installed
    EDITABLE against the PRIMARY CHECKOUT and `methods/conftest.py` binds it into `sys.modules` during
    COLLECTION; a later `sys.path.insert` cannot dislodge it, so a `/tmp`-worktree run silently
    exercises TRUNK. The generator's shim rebinds; this assert makes a failure to rebind a RED. (The
    #2222 sibling MEASURED six constant mutations all surviving with the shim removed.)"""
    loaded = REGEN._loaded_from()
    assert set(loaded) == set(REGEN.MODULE_NAMES), "the generator's module set drifted from its map"
    strays = {a: f for a, f in loaded.items() if not Path(f).resolve().is_relative_to(_METHODS_ROOT)}
    assert not strays, (
        "these modules resolved OUTSIDE this tree, so the suite is testing another checkout and every "
        f"threshold clause below is vacuous: {strays}"
    )
    assert REGEN.DEP_CLI is DEP_CLI and REGEN.TUM_READ is TUM_READ and REGEN.RESOLVE is RESOLVE


# ---------------------------------------------------------------------------------------------
# 1. Anti-vacuity — a zeroed or shrunken matrix must never read as green.
# ---------------------------------------------------------------------------------------------
def test_matrix_is_not_vacuous():
    rows = MATRIX["grain_pan_cancer"]["rows"]
    assert len(rows) >= MIN_PAN_CANCER_TARGETS, f"pan-cancer grain has {len(rows)} targets"
    assert len(MATRIX["grain_tumour"]["anchors"]) >= MIN_TUMOUR_ANCHORS
    assert len(MATRIX["grain_tumour"]["panel"]) >= MIN_TUMOUR_PANEL_PAIRS
    assert len(MATRIX["sites"]) >= MIN_SITES
    # The panel must span >1 expression_class or it cannot discriminate the arms.
    assert len({r["siteA_expression_class"] for r in rows}) >= 3
    assert sum(1 for r in rows if r["siteA_expression_class"] == "broadly_high") > 0, "no broadly_high row"


def test_every_excluded_tumour_row_is_named_with_a_reason():
    """Protocol rule 2: an undecidable row is EXCLUDED BY NAME. An unexplained shrink is
    indistinguishable from a coverage loss."""
    excluded = MATRIX["grain_tumour"]["excluded"]
    assert MATRIX["grain_tumour"]["measured"]["panel_pairs_excluded"] == len(excluded)
    for row in excluded:
        assert row.get("reason") and row.get("target") and row.get("code")


# ---------------------------------------------------------------------------------------------
# 2. Each cut pinned BEHAVIOURALLY, together with the quantity it cuts.
# ---------------------------------------------------------------------------------------------
def test_siteA_is_0_30_on_the_highly_expressed_fraction_and_is_GUARDED_by_breadth():
    sig = inspect.signature(DEP_CLI._classify_expression).parameters
    bar = sig["broadly_high_fraction"].default
    assert bar == _site("siteA_cellline_expression_class_broadly_high")["constant"] == 0.30

    def call(fe, fh):
        return DEP_CLI._classify_expression(fe, fh, 1, 0.70, bar, 0.10, 0.70)

    # Inside the breadth band, the bar splits broadly_high from broadly_moderate at 0.30 exactly.
    assert call(0.80, bar) == "broadly_high"
    assert call(0.80, bar - EPS) == "broadly_moderate"
    # GUARDED: below the frac_expressed>=0.70 breadth gate, NO frac_highly makes it broadly_high.
    assert call(0.40, 0.99) != "broadly_high"
    assert call(0.69, 1.0) != "broadly_high"
    # The quantity is the HIGHLY-expressed fraction (floor 5.0), not the merely-expressed fraction.
    assert _site("siteA_cellline_expression_class_broadly_high")["high_floor_log2tpm"] == 5.0


def test_siteB_is_0_50_on_the_SAME_fraction_and_fires_UNGUARDED():
    bar = RESOLVE._BROADLY_HIGH_FRACTION_MIN
    assert bar == _site("siteB_expression_property_magnitude_and_prevalence")["constant"] == 0.50
    # _prevalence's FIRST rung: fh>=0.5 -> broad, with no breadth gate before it. At fh just under the
    # bar with a mid fraction and no shape, it falls through to subset.
    assert RESOLVE._prevalence({"fraction_expressed": 0.50, "fraction_highly_expressed": bar}) == "broad"
    below = {"fraction_expressed": 0.50, "fraction_highly_expressed": bar - EPS, "distribution_pattern": "continuous"}
    assert RESOLVE._prevalence(below) == "subset"
    # UNGUARDED: broad fires even where the merely-expressed fraction is tiny, if the HIGH fraction clears.
    assert RESOLVE._prevalence({"fraction_expressed": 0.05, "fraction_highly_expressed": bar}) == "broad"
    # It reads the IDENTICAL field name, at the IDENTICAL floor, as site A.
    siteA, siteB = (
        _site("siteA_cellline_expression_class_broadly_high"),
        _site("siteB_expression_property_magnitude_and_prevalence"),
    )
    assert siteA["quantity"] == siteB["quantity"] == "fraction_highly_expressed"
    assert siteB["high_floor_log2tpm"] == RESOLVE._HIGHLY_EXPRESSED_LOG2TPM == siteA["high_floor_log2tpm"] == 5.0


def test_siteC_is_0_50_on_the_tumour_high_fraction_UNGUARDED_and_at_a_DIFFERENT_floor():
    site = _site("siteC_tumour_broadly_high")
    assert site["constant"] == 0.5
    # Unguarded first rung: broadly_high fires at high>=0.5 even with detectable_fraction 0.0.
    assert TUM_READ._classify_tumor_expression(0.0, 0.5, "continuous") == "broadly_high"
    assert TUM_READ._classify_tumor_expression(0.0, 0.5 - EPS, "continuous") == "broadly_low"
    # DIFFERENT denominator (one indication) and DIFFERENT high floor from sites A/B.
    assert site["high_floor_log2tpm"] == TUM_STATS.HIGH_LOG2TPM == 5.6724
    assert TUM_STATS.HIGH_LOG2TPM != 5.0, "the #2221 anchor divergence collapsed — re-derive this adjudication"


def test_the_0_50_numeral_in_presence_supported_is_a_DIFFERENT_quantity():
    """Guard against the #2220 error: a shared numeral is not a shared bar. `_PRESENCE_SUPPORTED_FRACTION`
    is also 0.50 but cuts fraction_EXPRESSED (floor 1.0), not fraction_HIGHLY_EXPRESSED (floor 5.0)."""
    site = _site("not_a_broadly_high_cut__presence_supported_fraction")
    assert site["constant"] == RESOLVE._PRESENCE_SUPPORTED_FRACTION == 0.50
    assert site["quantity"] == "fraction_expressed" != "fraction_highly_expressed"
    # It carries presence=supported on the merely-expressed fraction, independent of the HIGH fraction.
    assert RESOLVE._presence({"fraction_expressed": 0.50, "median_log2tpm_panel": 0.0}) == "supported"


def test_harmonising_the_number_alone_does_not_converge_the_words():
    """Structural, not numeric: even at a shared 0.50 bar, site A's guarded `broadly_high` and site B's
    unguarded `prevalence=broad` disagree on the measured panel — because B's `broad` ALSO fires on the
    breadth rung `fraction_expressed >= 0.70` that A's `broadly_high` never uses. Named so a panel
    change that removes the witnesses must RED and be re-argued."""
    disagree = MATRIX["grain_pan_cancer"]["measured"][
        "targets_where_guarded_A_and_unguarded_B_disagree_at_the_same_0_50_bar"
    ]
    rows = {r["target"]: r for r in MATRIX["grain_pan_cancer"]["rows"]}
    # Re-derive the disagreement set from the per-row columns rather than trusting the aggregate.
    rederived = sorted(
        t for t, r in rows.items() if (r["siteA_at_0_50"] == "broadly_high") != (r["siteB_prevalence"] == "broad")
    )
    assert rederived == sorted(disagree)
    assert set(disagree) >= {"APC", "ERBB2"}, f"the named same-bar disagreements changed: {disagree}"
    for t in ("APC", "ERBB2"):
        r = rows[t]
        assert r["siteA_at_0_50"] != "broadly_high" and r["siteB_prevalence"] == "broad"
        assert r["fraction_expressed"] >= 0.70, (
            f"{t}: B's broad here rests on the breadth rung; fe<0.70 breaks the argument"
        )


# ---------------------------------------------------------------------------------------------
# 3. The counterfactual ladders reproduce production at their status-quo bar.
# ---------------------------------------------------------------------------------------------
def test_counterfactual_ladders_reproduce_production_at_the_status_quo_bar():
    # Site A: the production classifier IS the counterfactual (it takes the bar as a keyword), so this
    # confirms the wiring rather than a re-implementation.
    for fe in (0.0, 0.10, 0.5, 0.69, 0.70, 0.8, 1.0):
        for fh in (0.0, 0.29, 0.30, 0.49, 0.50, 1.0):
            assert REGEN.cellline_class(fe, fh, 1, 0.30) == DEP_CLI._classify_expression(
                fe, fh, 1, 0.70, 0.30, 0.10, 0.70
            )
    # Site B: the prevalence/magnitude mirrors must reproduce the real functions at bar 0.5.
    for fe in (None, 0.0, 0.05, 0.5, 0.7, 1.0):
        for fh in (None, 0.0, 0.1, 0.2, 0.49, 0.5, 1.0):
            for pat in ("continuous", "bimodal", "long_tail", None):
                for med in (None, 0.0, 1.0, 5.0, 9.0):
                    s = {
                        "fraction_expressed": fe,
                        "fraction_highly_expressed": fh,
                        "distribution_pattern": pat,
                        "median_log2tpm_panel": med,
                    }
                    pres = RESOLVE._presence(s)
                    assert REGEN.resolve_prevalence(s, 0.5) == RESOLVE._prevalence(s)
                    assert REGEN.resolve_magnitude(s, pres, 0.5) == RESOLVE._magnitude(s, pres)
    # Site C: the tumour ladder must reproduce `_classify_tumor_expression` at bar 0.5.
    for det in (None, 0.0, 0.29, 0.3, 0.7, 1.0):
        for high in (None, 0.0, 0.1, 0.49, 0.5, 0.9):
            for pat in ("continuous", "bimodal", "long_tail", None):
                for mod in (None, 0.0, 0.5, 0.9):
                    assert REGEN.tumour_high_ladder(
                        det, high, pat, mod, high_bar=0.5
                    ) == TUM_READ._classify_tumor_expression(det, high, pat, mod)


# ---------------------------------------------------------------------------------------------
# 4. Arm A re-derives from the IRREPRODUCIBLE raw input through the production reader.
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("target", PAN_TARGETS)
def test_pan_cancer_row_rederives_through_compute_summary_stats(target: str):
    row = next(r for r in MATRIX["grain_pan_cancer"]["rows"] if r["target"] == target)
    tpm, meta = _load_vector(row["vector_fixture"].rsplit("/", 1)[-1])
    assert len(tpm) == row["n_cell_lines"], "panel size drifted from the matrix — fixture truncated?"
    s = DEP_CLI.compute_summary_stats(tpm, meta)
    assert s["fraction_highly_expressed"] == row["fraction_highly_expressed"]
    assert s["fraction_expressed"] == row["fraction_expressed"]
    assert s["expression_class"] == row["siteA_expression_class"]
    pres = RESOLVE._presence(s)
    assert RESOLVE._prevalence(s) == row["siteB_prevalence"]
    assert RESOLVE._magnitude(s, pres) == row["siteB_magnitude"]


def test_teeth_zeroing_a_vector_moves_its_rederived_class():
    """If clause 4 compared the matrix to a copy of its own output it would be green with the reader
    broken. Perturb the raw input and the re-derived class must move."""
    row = max(MATRIX["grain_pan_cancer"]["rows"], key=lambda r: r["fraction_highly_expressed"])
    tpm, meta = _load_vector(row["vector_fixture"].rsplit("/", 1)[-1])
    mutated = {m: 0.0 for m in tpm}
    s = DEP_CLI.compute_summary_stats(mutated, meta)
    assert s["fraction_highly_expressed"] == 0.0 != row["fraction_highly_expressed"]
    assert s["expression_class"] == "broadly_low"
    assert s["expression_class"] != row["siteA_expression_class"], "the max-fh target was already broadly_low?"


# ---------------------------------------------------------------------------------------------
# 5. The cost of each harmonisation, measured — and the redundancy finding.
# ---------------------------------------------------------------------------------------------
def test_siteA_up_to_0_50_demotes_exactly_the_named_cellline_broadly_high_reads():
    """Raising site A 0.30 -> 0.50 demotes broadly_high -> broadly_moderate for the named targets. This
    changes expression_class, which feeds tumor-presence `model_expression_structure` -> the
    tumour-presence golden (FORBIDDEN this arc). Movers named so the cost cannot silently drift."""
    rows = {r["target"]: r for r in MATRIX["grain_pan_cancer"]["rows"]}
    movers = sorted(t for t, r in rows.items() if r["siteA_at_0_50"] != r["siteA_expression_class"])
    assert movers == ["ERBB2", "MET"], f"the site-A movers changed: {movers}"
    for t in movers:
        assert rows[t]["siteA_expression_class"] == "broadly_high" and rows[t]["siteA_at_0_50"] == "broadly_moderate"
        # Each mover clears the breadth gate but sits in [0.30, 0.50) highly-expressed.
        assert rows[t]["fraction_expressed"] >= 0.70
        assert 0.30 <= rows[t]["fraction_highly_expressed"] < 0.50


def test_siteB_down_to_0_30_moves_exactly_the_named_prevalence_and_magnitude_reads():
    """Lowering site B 0.50 -> 0.30 (the only golden-safe direction) moves the named prevalence and
    magnitude reads. Pinned so the routed-up owner-call's cost statement stays matched to the data."""
    rows = {r["target"]: r for r in MATRIX["grain_pan_cancer"]["rows"]}
    prev = sorted(t for t, r in rows.items() if r["siteB_prevalence_at_0_30"] != r["siteB_prevalence"])
    mag = sorted(t for t, r in rows.items() if r["siteB_magnitude_at_0_30"] != r["siteB_magnitude"])
    assert prev == ["EPCAM", "MET", "TACSTD2"], f"site-B prevalence movers changed: {prev}"
    assert mag == ["EPCAM", "ERBB2", "MET", "TACSTD2"], f"site-B magnitude movers changed: {mag}"
    for t in prev:
        assert rows[t]["siteB_prevalence"] == "subset" and rows[t]["siteB_prevalence_at_0_30"] == "broad"


def test_the_fh_ge_0_5_condition_in_magnitude_is_redundant_with_the_median_floor():
    """finding_4: fh>=0.5 forces median>=5.0 (central-order-statistic bound), so the `fh>=0.5`
    OR-condition in `_magnitude` is subsumed by `med>=5.0` and bites ONLY in `_prevalence` today.
    Measured on the panel: no row has fh>=0.5 with median<5.0. And every site-B magnitude mover has
    median<5.0 with fh in [0.30, 0.50) — i.e. lowering the bar makes it newly bite in `_magnitude`."""
    rows = MATRIX["grain_pan_cancer"]["rows"]
    counter = [r["target"] for r in rows if r["fraction_highly_expressed"] >= 0.5 and r["median_log2tpm_panel"] < 5.0]
    assert not counter, f"fh>=0.5 with median<5.0 breaks the bound: {counter}"
    # Constructed witness of the redundancy inside _magnitude itself: at fh>=0.5 the median rung has
    # already fired, so dropping the fraction OR-condition changes nothing there.
    hi = {"fraction_highly_expressed": 0.6, "median_log2tpm_panel": 5.0}
    assert RESOLVE._magnitude(hi, "supported") == REGEN.resolve_magnitude(hi, "supported", 0.5) == "high"
    mag_movers = {r["target"]: r for r in rows if r["siteB_magnitude_at_0_30"] != r["siteB_magnitude"]}
    assert mag_movers, "no magnitude mover — the finding-4 reachability claim is unexercised on this panel"
    for r in mag_movers.values():
        assert r["median_log2tpm_panel"] < 5.0 and 0.30 <= r["fraction_highly_expressed"] < 0.50


# ---------------------------------------------------------------------------------------------
# 6. The tumour arm — anchors re-derive, and what harmonising site C DOWN would cost (forbidden).
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


def test_tumour_arm_b_lowering_the_bar_promotes_only_reads_below_the_current_bar():
    """Lowering site C 0.50 -> 0.30 only ever ADDS broadly_high reads (the rung is monotone), and only
    for pairs with high_fraction in [0.30, 0.50). This is the FORBIDDEN direction (moves tumour
    classes -> needs the tumour-presence golden); measured as a cost, re-derived both arms."""
    rows = MATRIX["grain_tumour"]["panel"] + MATRIX["grain_tumour"]["anchors"]
    movers = [r for r in rows if r["B_0.30"] != r["A"]]
    assert len(movers) == MATRIX["grain_tumour"]["measured"]["movers_down_to_0_30"] > 0
    for r in movers:
        assert r["B_0.30"] == "broadly_high" and r["A"] != "broadly_high"
        assert r["high"] is not None and 0.30 <= r["high"] < 0.50
        assert TUM_READ._classify_tumor_expression(r["det"], r["high"], r["pat"], r.get("mod")) == r["A"]
        assert REGEN.tumour_high_ladder(r["det"], r["high"], r["pat"], r.get("mod"), high_bar=0.30) == r["B_0.30"]
    # Non-movers byte-identical (protocol rule 5).
    assert all(r["B_0.30"] == r["A"] for r in rows if r not in movers)


# ---------------------------------------------------------------------------------------------
# 7. The adjudication record itself, and the no-change invariant.
# ---------------------------------------------------------------------------------------------
def test_the_adjudication_record_is_present_and_names_its_outcome():
    adj = MATRIX["adjudication"]
    assert adj["outcome"].startswith("DOCUMENTED-INTENTIONAL")
    for k in (
        "finding_1_the_three_values_confirmed_same_quantity_two_panels",
        "finding_2_the_divergence_is_structural_not_only_numeric",
        "finding_3_what_each_harmonisation_costs_on_measured_data",
        "finding_4_the_magnitude_or_condition_is_redundant_today",
        "why_no_change_here",
        "direction_routed_up",
        "catalog_write",
    ):
        assert adj.get(k), f"adjudication is missing `{k}`"
    assert MATRIX["_meta"]["regenerated_by"].endswith("regenerate_broadly_high_fraction_flip_matrix.py")
    assert (HERE / MATRIX["_meta"]["regenerated_by"].rsplit("/", 1)[-1]).exists()


def test_no_production_threshold_was_moved_by_this_adjudication():
    """The outcome is `no change`, and the three constants are the subject of the claim. Pinned as a
    SET so a later PR that moves one cannot leave this adjudication's prose standing as if it still
    described the code."""
    sig = inspect.signature(DEP_CLI._classify_expression).parameters
    observed = {
        "siteA_cellline_broadly_high_fraction": sig["broadly_high_fraction"].default,
        "siteB_resolve_broadly_high_fraction_min": RESOLVE._BROADLY_HIGH_FRACTION_MIN,
        "siteC_tumour_high_bar": 0.5
        if TUM_READ._classify_tumor_expression(0.0, 0.5, "continuous") == "broadly_high"
        and TUM_READ._classify_tumor_expression(0.0, 0.5 - EPS, "continuous") != "broadly_high"
        else None,
    }
    assert observed == {
        "siteA_cellline_broadly_high_fraction": 0.30,
        "siteB_resolve_broadly_high_fraction_min": 0.50,
        "siteC_tumour_high_bar": 0.5,
    }, f"a broadly_high determinant moved; re-run the flip matrix before editing the adjudication: {observed}"
