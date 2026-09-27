"""read_tumor_elevation_breadth (Slice B1, 2026-07-21).

A TARGET-GRAIN roll-up over CPTAC cohorts: "elevated in K of N cancers." Built on
read_all_cohorts (per-cohort summary). Breadth over INDICATIONS for ONE target (allowed),
NOT a ranking over targets. "Elevated" = protein_expression_class in {strong_up, modest_up}.

Tests (no S3 — _load_indexed monkeypatched to synthetic multi-cohort rows) pin:
  - the count (n_tested / n_elevated / fraction) over the existing per-cohort classes;
  - median effect is over ELEVATED cohorts only;
  - the breadth_class ladder (broadly / multi / single / not / data_unavailable);
  - most_elevated_cohorts is effect-sorted and elevated-only;
  - a target absent from all cohorts degrades to data_unavailable (never a fabricated negative).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = importlib.import_module("methods.cptac_protein_deg.read")


def _patch(monkeypatch, rows):
    df = pd.DataFrame(rows)
    gi, cohort_effect_null = {}, {}
    for i, row in enumerate(rows):
        gi.setdefault(str(row["gene_symbol"]).upper(), []).append(i)
        cohort_effect_null.setdefault(str(row["cohort"]).upper(), []).append(row["protein_effect_size"])
    monkeypatch.setattr(r, "_load_indexed", lambda: (df, {}, gi, cohort_effect_null))


def _row(cohort, gene, cls, effect, q=1e-6):
    return {
        "cohort": cohort,
        "gene_symbol": gene,
        "protein_effect_size": effect,
        "protein_bh_q_value": q,
        "protein_p_value": q,
        "protein_median_log2_tumor": 5.0,
        "protein_median_log2_normal": 3.0,
        "n_tumor_samples": 100,
        "n_normal_samples": 20,
        "protein_expression_class": cls,
        "stat_test_used": "msstatstmt_limma_ebayes_moderated",
        "method_version": "1.0.0",
    }


# 4 cohorts: 3 elevated (2 strong + 1 modest), 1 ns → broadly (frac 3/4 >= .5, n_elev 3)
_BROAD = [
    _row("BRCA", "EGFR", "strong_up", 2.0),
    _row("LUAD", "EGFR", "strong_up", 1.6),
    _row("COAD", "EGFR", "modest_up", 0.8),
    _row("OV", "EGFR", "not_significant", 0.1, q=0.3),
]


def test_broadly_tumor_elevated(monkeypatch):
    _patch(monkeypatch, _BROAD)
    b = r.read_tumor_elevation_breadth("EGFR")
    assert b["tumor_elevation_breadth_class"] == "broadly_tumor_elevated"
    assert b["n_cohorts_tested"] == 4
    assert b["n_cohorts_elevated"] == 3
    assert b["fraction_elevated"] == 0.75
    # median effect over ELEVATED only (2.0, 1.6, 0.8) → 1.6, not dragged by the ns cohort
    assert b["median_effect_across_elevated"] == 1.6
    # most_elevated is effect-sorted + elevated-only (ns cohort excluded)
    assert [c["cohort"] for c in b["most_elevated_cohorts"]] == ["BRCA", "LUAD", "COAD"]
    assert b["cohorts_tested"] == ["BRCA", "COAD", "LUAD", "OV"]


def test_multi_tumor_elevated(monkeypatch):
    # 2 elevated of 5 → n_elev 2 (>=2) but fraction 0.4 (<0.5) → multi, not broadly
    rows = [
        _row("BRCA", "MET", "strong_up", 2.0),
        _row("LUAD", "MET", "modest_up", 0.7),
        _row("COAD", "MET", "not_significant", 0.1, q=0.4),
        _row("OV", "MET", "not_significant", 0.0, q=0.9),
        _row("GBM", "MET", "strong_down", -1.7),
    ]
    _patch(monkeypatch, rows)
    b = r.read_tumor_elevation_breadth("MET")
    assert b["tumor_elevation_breadth_class"] == "multi_tumor_elevated"
    assert b["n_cohorts_elevated"] == 2 and b["n_cohorts_tested"] == 5
    assert b["fraction_elevated"] == 0.4


def test_single_tumor_elevated(monkeypatch):
    rows = [_row("BRCA", "X", "strong_up", 2.0), _row("LUAD", "X", "not_significant", 0.1, q=0.4)]
    _patch(monkeypatch, rows)
    b = r.read_tumor_elevation_breadth("X")
    assert b["tumor_elevation_breadth_class"] == "single_tumor_elevated"
    assert b["n_cohorts_elevated"] == 1
    assert b["median_effect_across_elevated"] == 2.0


def test_not_tumor_elevated_when_tested_but_none_elevated(monkeypatch):
    rows = [_row("BRCA", "Y", "not_significant", 0.1, q=0.5), _row("LUAD", "Y", "strong_down", -2.0)]
    _patch(monkeypatch, rows)
    b = r.read_tumor_elevation_breadth("Y")
    assert b["tumor_elevation_breadth_class"] == "not_tumor_elevated"
    assert b["n_cohorts_elevated"] == 0
    assert b["fraction_elevated"] == 0.0
    assert b["median_effect_across_elevated"] is None
    assert b["most_elevated_cohorts"] == []


def test_absent_target_is_data_unavailable(monkeypatch):
    _patch(monkeypatch, _BROAD)
    b = r.read_tumor_elevation_breadth("GHOST")
    assert b["tumor_elevation_breadth_class"] == "data_unavailable"
    assert b["n_cohorts_tested"] == 0
    assert b["fraction_elevated"] is None
    assert b["most_elevated_cohorts"] == []
    assert b["cohorts_tested"] == []


def _prow(cohort, gene, cls, effect, p, n_tumor, n_normal):
    """A per-cohort row with explicit p / n so the read-time Cohen's d (standardized effect) is
    computed — used to exercise the G6 effect-weighting of the breadth roll-up."""
    return {
        "cohort": cohort,
        "gene_symbol": gene,
        "protein_effect_size": effect,
        "protein_bh_q_value": p,
        "protein_p_value": p,
        "protein_median_log2_tumor": 5.0,
        "protein_median_log2_normal": 3.0,
        "n_tumor_samples": n_tumor,
        "n_normal_samples": n_normal,
        "protein_expression_class": cls,
        "stat_test_used": "msstatstmt_limma_ebayes_moderated",
        "method_version": "1.0.0",
    }


def test_breadth_strips_significant_but_effect_negligible_cohort_G6(monkeypatch):
    """G6: a cohort that cleared significance only via large n (Cohen's d negligible) must NOT count as
    elevated — breadth reflects reproducible effect size, not cohort power. Two genuine strong_up cohorts
    (tiny p, small n → large d) stay elevated; a modest_up power-artifact (marginal p, large n →
    negligible d) is stripped and surfaced via n_cohorts_sig_up_effect_negligible."""
    rows = [
        _prow("BRCA", "W", "strong_up", 2.0, 1e-6, 100, 20),  # z~4.75, n_eff~16.7 → d~1.16 large
        _prow("LUAD", "W", "strong_up", 1.6, 1e-6, 100, 20),  # large
        _prow("COAD", "W", "modest_up", 0.6, 0.04, 250, 250),  # z~2.05, n_eff=125 → d~0.18 NEGLIGIBLE
    ]
    _patch(monkeypatch, rows)
    b = r.read_tumor_elevation_breadth("W")
    assert b["n_cohorts_tested"] == 3
    assert b["n_cohorts_elevated"] == 2  # the negligible-effect COAD is stripped
    assert b["n_cohorts_sig_up_effect_negligible"] == 1
    assert {c["cohort"] for c in b["most_elevated_cohorts"]} == {"BRCA", "LUAD"}
    # was broadly (3/3) on significance alone; now multi (2 elevated, fraction 2/3<0.5 with n_elev 2)
    assert b["tumor_elevation_breadth_class"] == "multi_tumor_elevated"
    # data_unavailable standardized class (missing p AND se AND n) must NOT strip a real up-cohort
    row_no_meta = {
        "cohort": "OV",
        "gene_symbol": "W",
        "protein_effect_size": 1.8,
        "protein_bh_q_value": None,
        "protein_p_value": None,
        "n_tumor_samples": None,
        "n_normal_samples": None,
        "protein_expression_class": "strong_up",
    }
    _patch(monkeypatch, [row_no_meta])
    b2 = r.read_tumor_elevation_breadth("W")
    assert b2["n_cohorts_elevated"] == 1  # fallback: significance-gated, not penalized


def test_median_effect_even_count(monkeypatch):
    # 2 elevated → even count → average of the two effects
    rows = [
        _row("BRCA", "Z", "strong_up", 2.0),
        _row("LUAD", "Z", "modest_up", 1.0),
        _row("COAD", "Z", "not_significant", 0.1, q=0.4),
    ]
    _patch(monkeypatch, rows)
    b = r.read_tumor_elevation_breadth("Z")
    assert b["n_cohorts_elevated"] == 2
    assert b["median_effect_across_elevated"] == 1.5  # (1.0 + 2.0)/2


# --- #1664 F2: read-time pan-cohort BH/FDR under the K-of-N breadth panel --------------------------
# The gate must have TEETH: a cohort that is significance-gated-up AND non-negligible by Cohen's d but
# whose RAW p fails Benjamini-Hochberg over the breadth panel is STRIPPED from n_cohorts_elevated (a
# real demotion, not a vacuous pass), while a genuinely broad target is left UNCHANGED. The two strips
# (negligible-Cohen's-d, G6; pan-cohort-FDR, F2) are exercised independently so neither masks the other.


def test_pan_cohort_fdr_strips_chance_up_calls_demotes_broadly_F2(monkeypatch):
    # 5 cohorts, ALL significance-gated strong_up with a LARGE (non-negligible) Cohen's d, so WITHOUT
    # the pan-cohort FDR this is broadly_tumor_elevated (5/5). Two carry a genuinely tiny raw p; three
    # carry a marginal raw p (0.048/0.049/0.060 at small n) that FAILS BH over the 5-cohort panel
    # (BH step-up: largest rank k with p_(k) <= (k/5)*0.05 is k=2). The FDR must strip those three:
    # n_elevated 5 -> 2 -> multi_tumor_elevated. If the gate were vacuous this would stay broadly.
    rows = [
        _prow("BRCA", "T", "strong_up", 2.5, 1e-8, 100, 20),  # tiny p -> passes BH, large d
        _prow("LUAD", "T", "strong_up", 2.4, 1e-8, 100, 20),  # tiny p -> passes BH, large d
        _prow("COAD", "T", "strong_up", 2.0, 0.048, 8, 8),  # marginal p, small n -> d large, FAILS BH
        _prow("GBM", "T", "strong_up", 2.0, 0.049, 8, 8),  # FAILS BH
        _prow("OV", "T", "strong_up", 2.0, 0.060, 8, 8),  # FAILS BH
    ]
    _patch(monkeypatch, rows)
    b = r.read_tumor_elevation_breadth("T")
    assert b["n_cohorts_tested"] == 5
    # sanity: none stripped by the G6 negligible strip (all three marginal cohorts are large-d)
    assert b["n_cohorts_sig_up_effect_negligible"] == 0
    assert b["n_cohorts_elevated"] == 2  # 3 chance up-calls stripped by the pan-cohort BH
    assert b["n_cohorts_sig_up_pan_cohort_fdr_fail"] == 3
    assert b["tumor_elevation_breadth_class"] == "multi_tumor_elevated"  # demoted from broadly
    assert {c["cohort"] for c in b["most_elevated_cohorts"]} == {"BRCA", "LUAD"}


def test_pan_cohort_fdr_leaves_genuine_breadth_unchanged_F2(monkeypatch):
    # MUTATION COMPLEMENT: 4 strong_up cohorts, ALL with a genuinely tiny raw p -> all pass BH ->
    # broadly_tumor_elevated is UNCHANGED and nothing is recorded as an FDR strip.
    rows = [
        _prow("BRCA", "U", "strong_up", 2.5, 1e-8, 100, 20),
        _prow("LUAD", "U", "strong_up", 2.4, 1e-8, 100, 20),
        _prow("COAD", "U", "strong_up", 2.3, 1e-7, 100, 20),
        _prow("GBM", "U", "strong_up", 2.2, 1e-7, 100, 20),
    ]
    _patch(monkeypatch, rows)
    b = r.read_tumor_elevation_breadth("U")
    assert b["n_cohorts_elevated"] == 4
    assert b["n_cohorts_sig_up_pan_cohort_fdr_fail"] == 0
    assert b["tumor_elevation_breadth_class"] == "broadly_tumor_elevated"


def test_pan_cohort_fdr_missing_raw_p_falls_back_not_stripped_F2(monkeypatch):
    # A strong_up cohort with NO raw p must NOT be stripped by the pan-cohort FDR (absent from the
    # pass-map -> significance-gated fallback), mirroring the data_unavailable-standardized fallback in
    # _cohort_elevated. Missing metadata never fabricates NOR silently strips an elevated call.
    rows = [
        _prow("BRCA", "V", "strong_up", 2.5, 1e-8, 100, 20),
        {
            "cohort": "LUAD",
            "gene_symbol": "V",
            "protein_effect_size": 2.0,
            "protein_bh_q_value": None,
            "protein_p_value": None,
            "n_tumor_samples": 100,
            "n_normal_samples": 20,
            "protein_expression_class": "strong_up",
        },
    ]
    _patch(monkeypatch, rows)
    b = r.read_tumor_elevation_breadth("V")
    assert b["n_cohorts_elevated"] == 2  # LUAD kept via the missing-p fallback
    assert b["n_cohorts_sig_up_pan_cohort_fdr_fail"] == 0


def test_bh_reject_helper_matches_textbook():
    # Direct unit check of the BH step-up so the gate's arithmetic is pinned independently of the reader.
    # [1e-8, 1e-8, 0.048, 0.049, 0.060] @ alpha=0.05, m=5: kmax=2 -> only the two tiny p reject.
    assert r._bh_reject([1e-8, 1e-8, 0.048, 0.049, 0.060], 0.05) == [True, True, False, False, False]
    # A rescue at a higher rank rejects everything below it (BH step-up property):
    assert r._bh_reject([1e-8, 0.04, 0.045, 0.05], 0.05) == [True, True, True, True]
    assert r._bh_reject([], 0.05) == []
    # Order-independence: the same multiset in any order yields the same per-element verdict.
    assert r._bh_reject([0.060, 0.048, 1e-8, 0.049, 1e-8], 0.05) == [False, False, True, False, True]
