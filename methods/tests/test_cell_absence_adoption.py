"""Stage 1 adoption of methods/cell_absence.py — the equivalence each swap CLAIMS, pinned.

Every adoption in this stage claims to be a no-op. A claim like that decays silently: someone widens
a predicate in cell_absence.py for a good reason at one call site and a different call site quietly
changes verdict. So each swap's PREVIOUS BODY is kept here as the oracle and the live code is
measured against it over a shared corpus of every shape these cells actually arrive in.

Two things this file is careful about:

  1. THE ORACLE IS THE OLD CODE, NOT MY DESCRIPTION OF IT. `_legacy_*` below are verbatim copies of
     the bodies that shipped before the swap, so the test cannot drift toward what I *meant*.

  2. IT PINS THE NEGATIVE TOO. `classify(x) == PRESENT` is a plausible-looking substitution for
     "is this a usable number?" that is measurably WRONG (17 divergences, all admitting non-numeric
     cells into a numeric path). #650's description tabled it. If it were ever swapped in, the
     positive tests would still pass — so the wrongness is asserted directly.

Libraries are imported at module scope, not via importorskip: a silent skip on the file that pins
these equivalences is indistinguishable from a pass.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]

from onc_methods import cell_absence as ca

_STEP = REPO / "onc_methods" / "cptac_protein_deg" / "steps" / "03_pool_and_write.py"


def _load_step():
    """Load 03_pool_and_write.py by path — its filename is not a valid identifier."""
    spec = importlib.util.spec_from_file_location("_pool03_adoption", _STEP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_pool03_adoption"] = mod
    spec.loader.exec_module(mod)
    return mod


# --- the shared corpus: every shape a cell arrives in on these paths ---------------------------
# Ordered roughly null → non-finite → finite. Names are used in failure messages.
CORPUS: list[tuple[str, object]] = [
    ("None", None),
    ("float_nan", float("nan")),
    ("np_nan", np.nan),
    ("np_float64_nan", np.float64("nan")),
    ("pd_NA", pd.NA),
    ("pd_NaT", pd.NaT),
    ("decimal_nan", Decimal("NaN")),
    ("str_nan", "nan"),
    ("str_NaN", "NaN"),
    ("str_NAN", "NAN"),
    ("str_nan_padded", "  nan  "),
    ("str_none", "none"),
    ("str_None", "None"),
    ("str_null", "null"),
    ("str_na", "na"),
    ("str_NA", "NA"),
    ("str_angle_NA", "<NA>"),
    ("str_nat", "nat"),
    ("str_nil", "<nil>"),
    ("empty_str", ""),
    ("whitespace_str", "   "),
    ("pos_inf", math.inf),
    ("neg_inf", -math.inf),
    ("np_inf", np.inf),
    ("str_inf", "inf"),
    ("str_neg_inf", "-inf"),
    ("str_Infinity", "Infinity"),
    ("str_1e400", "1e400"),
    ("zero_int", 0),
    ("zero_float", 0.0),
    ("false", False),
    ("true", True),
    ("int_7", 7),
    ("float_2p5", 2.5),
    ("np_float64_2p5", np.float64(2.5)),
    ("np_int64_7", np.int64(7)),
    ("decimal_2p5", Decimal("2.5")),
    ("str_2p5", "2.5"),
    ("str_0", "0"),
    ("str_text", "Detected in all"),
    ("str_hyphen", "-"),
    ("bytes", b"x"),
]


def _outcome(fn, value):
    """Evaluate a predicate, recording an exception as its own outcome so a RAISE-vs-False change
    is visible as a divergence rather than crashing the comparison."""
    try:
        return bool(fn(value))
    except Exception as exc:  # noqa: BLE001 — the exception TYPE is the observation
        return f"RAISE:{type(exc).__name__}"


def _divergences(oracle, live):
    return [
        (n, v, _outcome(oracle, v), _outcome(live, v)) for n, v in CORPUS if _outcome(oracle, v) != _outcome(live, v)
    ]


# --- SITE: cptac_protein_deg/steps/03_pool_and_write.py::_is_finite ----------------------------


def _legacy_is_finite(x) -> bool:
    """VERBATIM the body that shipped before the swap. Do not tidy — it is the oracle."""
    try:
        return x is not None and not pd.isna(x) and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def test_pool_is_finite_is_unchanged_by_the_swap():
    """`_is_finite` now delegates to as_float(non_finite='missing'); prove that changed nothing.

    This guard decides whether an MSstatsTMT ±Inf (an unestimable contrast — a ratio with no
    denominator) reaches the `q >= 0.05` arm and gets labelled `not_significant`. A widening here
    reintroduces the exact defect test_unestimable_contrast.py exists to prevent.
    """
    step = _load_step()
    diffs = _divergences(_legacy_is_finite, step._is_finite)
    assert not diffs, "\n".join(f"  {n:18} {v!r:22} legacy={a!s:10} live={b!s:10}" for n, v, a, b in diffs)


def test_pool_is_finite_still_rejects_the_things_that_matter():
    """Belt-and-braces on the two shapes with a recorded incident behind them, so this file fails
    loudly rather than only reporting 'the oracle agrees' if the corpus is ever thinned."""
    step = _load_step()
    for bad in (math.inf, -math.inf, float("nan"), None, "", "not a number"):
        assert step._is_finite(bad) is False, f"{bad!r} must not read as a usable number"
    for good in (0.0, -1.5, 2.5, "0.04", 7):
        assert step._is_finite(good) is True, f"{good!r} must read as a usable number"


def test_classify_present_is_NOT_a_usable_number_test():
    """The falsified mapping from #650's description, asserted as wrong so it cannot be swapped back.

    `classify(x) == PRESENT` means 'not missing and not non-finite' — it says nothing about being
    numeric, so it admits text, '' and bytes into a numeric path. Every divergence runs in the
    permissive direction for a guard whose job is to REJECT garbage.
    """
    diffs = _divergences(_legacy_is_finite, lambda x: ca.classify(x) == ca.PRESENT)
    assert len(diffs) >= 15, f"expected the wrong mapping to diverge widely; got {len(diffs)}"
    # and specifically: it admits things that are plainly not numbers
    for text in ("Detected in all", "", "   ", "-"):
        assert ca.classify(text) == ca.PRESENT, "precondition: classify calls these PRESENT"
        assert _legacy_is_finite(text) is False, "precondition: the real guard rejects them"
    # the correct substitution, restated as an executable claim
    for name, value in CORPUS:
        assert _legacy_is_finite(value) == (ca.as_float(value, non_finite="missing") is not None), name


# --- SITE: depmap_common/loaders.py::model_metadata_by_id -------------------------------------


def _legacy_plain_cell(v):
    """VERBATIM the per-cell rule that shipped before the swap: {k: None if pd.isna(v) else v}."""
    return None if pd.isna(v) else v


def test_depmap_row_normalisation_is_unchanged_by_the_swap():
    """plain_row() must null exactly what `pd.isna` nulled — no more, no less.

    ±Inf is the load-bearing case: a ±Inf in a numeric metadata column is a VALUE, not a gap, and
    nulling it would destroy data. Both the old rule and plain_row leave it alone.
    """
    diffs = _divergences(
        lambda v: _legacy_plain_cell(v) is None,
        lambda v: ca.plain_row({"k": v})["k"] is None,
    )
    # np.ma.masked is deliberately excluded from CORPUS: pd.isna returns the masked constant itself
    # (which bools to False, i.e. "present") while it IS missing. plain_row is more correct there,
    # but no pandas reader emits it, so it is unreachable on this path and not worth a divergence.
    assert not diffs, "\n".join(f"  {n:18} {v!r:22} legacy_null={a!s:10} live_null={b!s:10}" for n, v, a, b in diffs)


def test_depmap_metadata_frame_round_trips_identically(tmp_path):
    """The frame-level claim, on a frame built the way the real loader builds one: a MIXED-dtype
    CSV read, which is the construction path that produces float nan in an object column."""
    from onc_methods.depmap_common import loaders

    csv = tmp_path / "Model.csv"
    csv.write_text("ModelID,CCLEName,OncotreeLineage,Age\nACH-1,A549_LUNG,Lung,58\nACH-2,,,\n,ORPHAN,Skin,40\n")
    df = pd.read_csv(csv)

    legacy = {
        row["ModelID"]: {k: _legacy_plain_cell(v) for k, v in row.to_dict().items()}
        for _, row in df.iterrows()
        if not pd.isna(row["ModelID"])
    }
    live = loaders.model_metadata_by_id(df)
    assert live == legacy, f"live={live}\nlegacy={legacy}"

    # and the properties the docstring promises, stated directly rather than only via the oracle
    assert set(live) == {"ACH-1", "ACH-2"}, "the row with a MISSING KEY must be dropped, not kept under None"
    assert live["ACH-2"]["CCLEName"] is None, "a missing object-dtype cell must become None, not float nan"
    assert not any(isinstance(v, float) and math.isnan(v) for m in live.values() for v in m.values())


def test_depmap_normalisation_refuses_a_non_scalar_cell():
    """Previously a caveat in prose ('assumes scalar columns'); now enforced.

    `pd.isna` on a list-valued cell returns an ARRAY, so the old `if pd.isna(v)` raised only because
    bool() of a multi-element array raises. A LENGTH-1 container was the dangerous case: its truth
    value is well-defined, so it would have answered 'present' and shipped a container into JSON.
    """
    with pytest.raises(TypeError, match="SCALAR cell"):
        ca.plain_row({"k": [1, 2]})
    with pytest.raises(TypeError, match="SCALAR cell"):
        ca.plain_row({"k": [None]})  # the length-1 case bool() would NOT have caught
    with pytest.raises(TypeError, match="SCALAR cell"):
        ca.plain_row({"k": pd.Series([np.nan])})


# --- the corpus itself must stay able to express these failures --------------------------------


def test_the_corpus_is_not_vacuous():
    """A corpus that no longer discriminates turns every test above into a tautology.

    Asserts the corpus still contains all three classes AND that the two predicates under test
    genuinely disagree with a deliberately broken variant — so 'no divergences' is evidence.
    """
    classes = {ca.classify(v) for _, v in CORPUS}
    assert classes == {ca.MISSING, ca.NON_FINITE, ca.PRESENT}, classes
    # a broken _is_finite (drops the non-finite guard) MUST be caught by the oracle comparison
    broken = _divergences(_legacy_is_finite, lambda x: x is not None and not pd.isna(x))
    assert broken, "the corpus can no longer detect a dropped non-finite guard"
    assert any(n in {"pos_inf", "neg_inf", "np_inf"} for n, _, _, _ in broken), [n for n, *_ in broken]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# BATCH 2 — four more sites, and the reachability fact that batch 1 got WRONG
# ═══════════════════════════════════════════════════════════════════════════════════════════════
#
# Batch 1's PR description asserted that `pd.NA` is not reachable in this repo. That was measured,
# and it was measured on the wrong population: I probed the READERS (pd.read_parquet,
# pq.read_table().to_pandas(), read_csv with and without dtype=str) and found pd.NA unreachable from
# every one of them, under both pandas majors. It is unreachable from all of them. But pyarrow stores
# the pandas dtype in the parquet FILE METADATA and RESTORES the extension dtype on read, so a
# repo-internal `.astype("string")` / `.astype("Int64")` in a WRITER puts pd.NA back on the READ side
# of the very next stage. REACHABILITY HAS TWO SOURCES — external inputs AND in-repo dtype casts —
# and the first probe covered one of them.
#
# That matters here because the four batch-2 swaps are claimed to be NO-OPS, and they are no-ops
# only because these particular methods make no such cast. So this file pins BOTH halves: the
# equivalence, and the premise the equivalence rests on.
#
# WHAT THESE TESTS DO AND DO NOT CATCH — measured by mutation, 2026-09-16, not asserted:
#   Reverting `ca.is_missing(tw)` to the legacy 2-term guard in arm_loss_sl_scan::_concordance, or
#   reverting tcga_fusion_consensus::_distinct_non_null, leaves the WHOLE SUITE GREEN. That is the
#   correct result, not a gap: over the shapes those sites can hold the two predicates are the same
#   function, which is the entire claim. A behavioural test cannot distinguish them, so the tests
#   below compare PREDICATES over a corpus instead. The one swap with behavioural teeth is
#   arm_loss_sl_scan's focality guard, whose old form was a bare `tw is not None` rather than the
#   legacy 2-term guard — reverting THAT reds exactly one test (see
#   tests/methods/arm_loss_sl_scan/test_arm_loss_sl_scan.py::
#   test_a_nan_twohit_freq_yields_no_data_labels_and_NOT_a_nan_ranking_score).


def _legacy_group_c(x):
    """VERBATIM the guard that shipped at tcga_fusion_consensus/cli.py:80 and
    arm_loss_sl_scan/scan.py:216 before the swap. Do not tidy — it is the oracle."""
    return x is None or (isinstance(x, float) and pd.isna(x))


def _legacy_group_b(v):
    """VERBATIM the per-cell rule that shipped at functional_gene_state/read.py:238-239 and
    tcga_aneuploidy_burden/read.py (the `_num` helper plus three inline str casts)."""
    return bool(pd.isna(v))


# The shapes each site's cells can ACTUALLY hold, measured from the construction path rather than
# assumed. A no-op claim is only as good as this list, so each entry names why it is reachable.
_REACHABLE = {
    # float64 ABSOLUTE segment columns -> numpy floats and real numbers only.
    "functional_gene_state": ["None", "float_nan", "np_nan", "np_float64_nan", "zero_float", "float_2p5"],
    # pq.read_table(...).to_pandas() over a mixed str/float product: object-or-str cells and floats.
    "tcga_aneuploidy_burden": ["None", "float_nan", "np_float64_nan", "str_text", "str_2p5", "float_2p5", "zero_int"],
    # groupby-agg `list` over partner_gene / frame_pred: None on pandas 2 (object), nan on pandas 3 (str).
    "tcga_fusion_consensus": ["None", "float_nan", "np_nan", "str_text", "str_2p5"],
    # dict .get() -> None for an absent key; cli.py:198 guards `if denom:` over an int numerator,
    # so a present value is a FINITE float. Nothing else can arrive.
    "arm_loss_sl_scan": ["None", "zero_float", "float_2p5"],
}


def _subcorpus(names):
    by_name = dict(CORPUS)
    missing = [n for n in names if n not in by_name]
    assert not missing, f"_REACHABLE names not in CORPUS: {missing}"
    return [(n, by_name[n]) for n in names]


@pytest.mark.parametrize("site", sorted(_REACHABLE))
def test_batch2_swaps_are_exact_no_ops_over_each_SITE_S_reachable_domain(site):
    """Each batch-2 swap, measured against its verbatim oracle over the shapes that site can hold.

    Scoped per-site on purpose. The whole-corpus comparison (below) DOES diverge — that is the point
    of the swap — so a corpus-wide equality assertion would be false, and a corpus-wide inequality
    assertion would not tell you the shipped behaviour is unchanged. The reachable domain is the only
    population on which 'no-op' is a meaningful claim.
    """
    oracle = _legacy_group_c if site in ("tcga_fusion_consensus", "arm_loss_sl_scan") else _legacy_group_b
    diffs = [
        (n, v, _outcome(oracle, v), _outcome(ca.is_missing, v))
        for n, v in _subcorpus(_REACHABLE[site])
        if _outcome(oracle, v) != _outcome(ca.is_missing, v)
    ]
    assert not diffs, f"{site}: " + "\n".join(
        f"  {n:18} {v!r:22} legacy={a!s:10} live={b!s:10}" for n, v, a, b in diffs
    )


def test_the_group_c_swap_IS_a_widening_off_the_reachable_domain():
    """The companion negative: off the reachable domain the swap is NOT a no-op, and every divergence
    runs present -> missing.

    Kept because 'no-op over the reachable domain' is only informative if the predicate genuinely
    differs somewhere — otherwise the per-site tests above would pass against a predicate that had
    silently become an alias for the old one, and the adoption would be pointless rather than safe.
    Direction matters as much as count: at all four batch-2 sites 'missing' is the CONSERVATIVE
    answer (drop the value from a JSON list, emit None, label no_twohit_data), so if a future cast
    ever makes these shapes reachable the new code is BETTER than the old, and it is this file's
    no-op CLAIM that needs restating — not the code.
    """
    diffs = _divergences(_legacy_group_c, ca.is_missing)
    names = sorted(n for n, _v, _a, _b in diffs)
    # np.ma.masked is NOT here, and not by oversight: CORPUS excludes it deliberately (see the comment
    # in test_depmap_row_normalisation_is_unchanged_by_the_swap). It is covered on its own below.
    assert names == ["decimal_nan", "pd_NA", "pd_NaT"], names
    for n, v, legacy, live in diffs:
        assert legacy is False and live is True, f"{n}={v!r} diverges the WRONG WAY: {legacy} -> {live}"


def test_pd_NA_SURVIVES_a_parquet_round_trip_so_reachability_has_TWO_sources(tmp_path):
    """The measurement that corrects batch 1's PR description. Pinned as a test, not a memory.

    A nullable-dtype cast is not confined to the process that makes it: pyarrow writes the pandas
    dtype into the parquet metadata and rebuilds the extension dtype on read, so `.astype("string")`
    in a writer hands `pd.NA` to whatever reads the file next. Verified identically under pandas
    3.0.3/pyarrow 25 and 2.3.3/pyarrow 21.

    The control column is what makes this falsifiable: a DEFAULT-dtype string column round-trips to a
    sentinel the OLD guard catches, so the difference is attributable to the CAST rather than to
    parquet, to pyarrow, or to the pandas version.
    """
    df = pd.DataFrame(
        {
            "cast_str": pd.Series(["P01116", None]).astype("string"),
            "cast_int": pd.to_numeric(pd.Series(["1", None]), errors="coerce").astype("Int64"),
            "default_str": pd.Series(["P01116", None]),
            "default_float": pd.Series([1.0, None]),
        }
    )
    p = tmp_path / "t.parquet"
    df.to_parquet(p)
    back = pd.read_parquet(p).iloc[1]

    for col in ("cast_str", "cast_int"):
        v = back[col]
        assert type(v).__name__ == "NAType", f"{col}: expected pd.NA to survive, got {v!r} ({type(v).__name__})"
        assert _legacy_group_c(v) is False, f"{col}: the legacy guard was expected to MISS pd.NA"
        assert ca.is_missing(v) is True, f"{col}: is_missing must catch pd.NA"

    # CONTROL: without the cast, the sentinel is one the legacy guard already handled. If this ever
    # fails, the test above is no longer isolating the cast and its conclusion does not follow.
    for col in ("default_str", "default_float"):
        v = back[col]
        assert type(v).__name__ != "NAType", f"{col}: unexpectedly nullable — control invalid"
        assert _legacy_group_c(v) is True, f"{col}={v!r}: control expected the legacy guard to catch it"
        assert ca.is_missing(v) is True, col


# The scan that keeps the no-op claim honest. Patterns that MANUFACTURE a pd.NA-bearing dtype.
_NULLABLE_CAST_PATTERNS = (
    'astype("string")',
    "astype('string')",
    'astype("Int64")',
    "astype('Int64')",
    'astype("boolean")',
    'astype("Float64")',
    "convert_dtypes",
    "dtype_backend",
    "ArrowDtype",
    'dtype="string"',
    'dtype="Int64"',
)


def _nullable_casts_in(method_dir: Path) -> list[str]:
    hits = []
    for py in sorted(method_dir.rglob("*.py")):
        text = py.read_text()
        for pat in _NULLABLE_CAST_PATTERNS:
            if pat in text:
                hits.append(f"{py.relative_to(REPO)}: {pat}")
    return hits


@pytest.mark.parametrize("method", sorted(_REACHABLE))
def test_the_batch2_methods_manufacture_no_pd_NA_which_is_WHY_the_swaps_are_no_ops(method):
    """The PREMISE, ratcheted. `_REACHABLE` above omits pd.NA/pd.NaT for these four methods; this is
    the check that the omission stays true.

    If this fails, nothing is broken — read the failure as 'the no-op claim in
    tests/test_cell_absence_adoption.py and in PR #6xx no longer describes this site'. The new
    predicate handles the cast correctly and the old one did not, so the code is fine; it is the
    DOCUMENTATION of the change that has gone stale, which is the thing that silently rots.
    """
    hits = _nullable_casts_in(REPO / "onc_methods" / method)
    assert not hits, (
        f"{method} now manufactures a nullable dtype:\n  " + "\n  ".join(hits) + "\n"
        "pd.NA is therefore reachable here and the batch-2 swap at this site is a WIDENING, not a "
        "no-op. Re-derive the equivalence and update _REACHABLE."
    )


def test_the_nullable_cast_scan_can_actually_FAIL():
    """Positive control for the scan above — without it, a typo'd pattern list would make every
    premise test vacuously green.

    These two methods DO cast, measured 2026-09-16: cptac_protein_deg/steps/03_pool_and_write.py
    (uniprot_ac -> string) and kinome_atlas_prediction/derive.py (six string columns plus an Int64
    rank). Neither is a batch-2 site. Asserted here so the scan is known to detect the thing it is
    used to rule out.
    """
    for method in ("cptac_protein_deg", "kinome_atlas_prediction"):
        hits = _nullable_casts_in(REPO / "onc_methods" / method)
        assert hits, f"{method} was expected to contain a nullable cast — the scan has gone blind"


def test_both_legacy_guards_MISS_np_ma_masked_which_is_why_it_stays_out_of_CORPUS():
    """The one CORPUS-excluded sentinel, pinned on its own.

    Scope, stated precisely because the neighbouring claim is easy to overstate: the OUTCOME
    (`is_missing(masked) is True`) is already covered by
    test_cell_absence.py::test_is_missing_true_for_every_null_shape[np_masked]. What is NOT covered
    anywhere is the two facts this adoption turns on — the MECHANISM that catches it, and what the
    replaced guards did with it.

    Mechanism: `is_missing`'s general rule is the IEEE self-inequality `value != value`, which
    identifies every nan spelling without naming a type. That rule FAILS here:
    `np.ma.masked != np.ma.masked` evaluates to the masked constant, and
    `bool(masked)` is False — so the generic test reports 'present'. Only the explicit
    `type(value).__name__ in {..., "MaskedConstant"}` branch saves it.

    `pd.isna(masked)` has the same problem for the opposite reason: it returns the masked constant
    rather than a bool, so `bool(pd.isna(v))` is False and BOTH legacy oracles call it present. Kept
    out of CORPUS on reachability grounds (no reader emits it) — see
    test_depmap_row_normalisation_is_unchanged_by_the_swap — so this test carries the fact instead.
    """
    m = np.ma.masked
    assert type(m).__name__ == "MaskedConstant"
    assert bool(m != m) is False, (
        "if this ever becomes True the generic null test suffices and the special-case is dead code"
    )
    assert bool(pd.isna(m)) is False, "pd.isna returns the masked constant, which bools to 'present'"
    assert _legacy_group_c(m) is False, "the legacy guard misses it (masked is not a float subclass)"
    assert _legacy_group_b(m) is False, "the legacy pd.isna guard misses it too, via bool(masked)"
    assert ca.is_missing(m) is True, "is_missing must catch it via the MaskedConstant type-name branch"
