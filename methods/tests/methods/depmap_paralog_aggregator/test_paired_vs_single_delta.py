"""Tests for the re-derived paralog buffering metric (dep_delta_paired_vs_max_single).

PR-B' (2026-07-17): the reader was aligned to the card + rule contract. Previously it
emitted strong/moderate/weak/none off the RAW dual-KO Chronos effect (conflating
buffering with baseline essentiality); moderate/weak matched no rule and the
`partial` rule was dead. Now it emits strong/partial/none off
    delta = min(single_a, single_b) - median_dual
(the additional lethality of the dual KO over the STRONGEST single = true buffering;
min = most negative = most lethal on the Chronos scale).

2026-09-12 (FR 20-target literature panel): the baseline was `max(...)` — the LEAST
lethal single — so for any pair with one baseline-ESSENTIAL member the delta collapsed
to that member's own gene effect and manufactured buffering with no genetic interaction
(ERBB2+PTK2, PRMT5+PRMT8, AR+ESRRA; 35.7% of the 26Q1 library over-classified). Every
case in the original fixture gave BOTH singles ~0, where max() == min(), so these tests
could not fail on the bug: the GI/GJ/GK block below is the guard that can.

Hermetic: monkeypatches _ensure_paralog_cached to a synthetic CSV in tmp — the real
~/.cache is never touched (cache-pollution discipline).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Resolve the repo root from THIS test file's location (parents[3] = repo root) so the test
# imports the reader from the SAME checkout it lives in — not a hardcoded absolute path that
# would silently import a DIFFERENT checkout (e.g. the primary tree while editing in a worktree).
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import methods.depmap_paralog_aggregator.read as R  # noqa: E402


def _write_csv(tmp_path: Path, header: list[str], rows: list[list]) -> Path:
    import csv

    p = tmp_path / "ParalogGeneEffect.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
    return p


@pytest.fixture
def reader(tmp_path, monkeypatch):
    """A synthetic ParalogGeneEffect.csv with single-KO + dual-KO columns.

    Design:
      GA/GB: STRONG buffering — singles ~0 (viable), dual ~-1.2 → delta ~1.2
      GC/GD: PARTIAL — singles ~0, dual ~-0.35 → delta ~0.35
      GE/GF: NONE — singles ~0, dual ~0 → delta ~0
      GG/GH: dual present but NO single-KO column for either → delta unmeasured

      ESSENTIAL-PARTNER block (the max()-baseline regression — the ERBB2/PTK2 shape).
      GI is viable (~-0.06); GJ is baseline-ESSENTIAL on its own (~-0.64); GK is viable
      (~-0.02). Two duals:
        GI_GJ ~-0.79  -> min-baseline: -0.64-(-0.79) = +0.15 -> NONE
                         max-baseline: -0.06-(-0.79) = +0.73 -> "strong" (= GJ's own essentiality)
        GI_GK ~-0.40  -> min-baseline: -0.06-(-0.40) = +0.34 -> PARTIAL (a real interaction)
      So the baseline decides BOTH the class (none vs strong) AND which partner is named
      strongest (GK vs GJ). Under max() these assertions fail; that is the point.
    """
    header = [
        "ModelID",
        "GA",
        "GB",
        "GC",
        "GD",
        "GE",
        "GF",  # single-KO baselines (~0 = viable)
        "GI",
        "GJ",
        "GK",  # single-KO baselines for the essential-partner block (GJ is essential)
        "GA_GB",
        "GC_GD",
        "GE_GF",
        "GG_GH",  # dual-KO pairs
        "GI_GJ",
        "GI_GK",  # essential-partner duals
        "AAVS1_chr2",  # control — must be skipped
    ]
    rows = [
        # GA   GB    GC     GD     GE     GF   GI     GJ     GK  |GA_GB GC_GD GE_GF GG_GH|GI_GJ GI_GK|ctl
        ["ACH-1", 0.0, 0.05, -0.02, 0.0, 0.01, 0.0, -0.05, -0.64, -0.02, -1.20, -0.34, 0.01, -1.4, -0.79, -0.40, -0.5],
        ["ACH-2", 0.02, 0.0, 0.0, -0.03, 0.0, 0.02, -0.06, -0.66, 0.0, -1.25, -0.36, -0.01, -1.5, -0.80, -0.41, -0.6],
        ["ACH-3", 0.0, 0.01, 0.01, 0.0, -0.01, 0.0, -0.07, -0.62, -0.03, -1.18, -0.35, 0.00, -1.3, -0.78, -0.39, -0.4],
    ]
    csv_path = _write_csv(tmp_path, header, rows)
    monkeypatch.setattr(R, "_ensure_paralog_cached", lambda: csv_path)
    # Force the RAW-CSV FALLBACK path: pretend the derived product is unreachable so these
    # buffering-MATH tests exercise the live recompute (the primary product-read path is
    # covered separately in test_derived_product_path.py). _derived_parquet_uri → None makes
    # _read_from_derived_product return None → read_target_summary falls back to _read_from_raw_csv.
    monkeypatch.setattr(R, "_derived_parquet_uri", lambda: None)

    # Reset the reader's two PROCESS-GLOBAL caches, in both directions. `_load_paralog_indexed`
    # is a ZERO-ARG lru_cache (nothing to key a synthetic CSV on) and `_PARALOG_STATUS` is a
    # module-level latch, so both outlive a single test FILE: any earlier caller in the same
    # process that resolved the CSV to None — e.g. tests/calibration/recomputation/
    # test_paralog_buffering_recomputation.py — latches an EMPTY index, this fixture's synthetic
    # CSV is then never parsed, and every assertion below reads `data_unavailable` instead of the
    # computed class. Whether that happens depends on how xdist groups files onto a worker, which
    # is why it presents as an intermittent flake rather than a stable red. test_derived_product_
    # path.py already clears the cache around its reads; this fixture did not. See skills#2100.
    R._load_paralog_indexed.cache_clear()
    monkeypatch.setattr(R, "_PARALOG_STATUS", None)
    yield R
    # Don't hand OUR synthetic parse to whatever file this worker runs next, either.
    R._load_paralog_indexed.cache_clear()


def test_strong_buffering_pair(reader):
    res = reader.read_target_summary("GA")
    assert res["paralog_buffering_class"] == "strong"
    assert res["strongest_paralog_symbol"] == "GB"
    assert res["strongest_paralog_delta"] > 0.5


def test_partial_buffering_pair(reader):
    res = reader.read_target_summary("GC")
    assert res["paralog_buffering_class"] == "partial"
    assert 0.2 <= res["strongest_paralog_delta"] <= 0.5


def test_no_buffering_pair(reader):
    res = reader.read_target_summary("GE")
    assert res["paralog_buffering_class"] == "none"


def test_delta_sign_convention(reader):
    """delta = min(single) - median_dual → POSITIVE when the dual KO is more lethal
    than the STRONGEST single (Chronos: more-negative = more lethal)."""
    res = reader.read_target_summary("GA")
    fp = res["functional_paralogs"][0]
    assert fp["median_dual_ko_effect"] < 0  # dual KO is lethal
    assert fp["single_ko_effect"] > fp["median_dual_ko_effect"]  # single less lethal
    assert fp["dep_delta_paired_vs_max_single"] == pytest.approx(
        fp["single_ko_effect"] - fp["median_dual_ko_effect"], abs=1e-6
    )


def test_missing_single_ko_baseline_is_unmeasured_not_none(reader):
    """GG/GH: dual present, NO single-KO column → delta None. The target must NOT be
    called `none` (a confirmed no-buffer) off a missing baseline — measured-vs-null."""
    res = reader.read_target_summary("GG")
    # only partner is GH, whose delta is unmeasured → no measured partner → data_unavailable
    assert res["paralog_buffering_class"] == "data_unavailable"
    assert res["_data_note"] == "paralog_single_ko_baseline_unavailable"


def test_class_vocab_matches_card_contract(reader):
    """Every class the reader can emit must be in the card's declared vocabulary
    (strong/partial/none/data_unavailable) — the reader↔card alignment PR-B' fixes."""
    emitted = set()
    for g in ("GA", "GC", "GE", "GG", "NOSUCHGENE"):
        emitted.add(reader.read_target_summary(g)["paralog_buffering_class"])
    assert emitted <= {"strong", "partial", "none", "data_unavailable"}


# --- The max()-vs-min() baseline regression (2026-09-12) ---------------------------------------
# These four are the ONLY tests in this file that can fail if the baseline reverts to max():
# every other case has both singles ~0, where max() == min().


def test_essential_partner_does_not_manufacture_buffering(reader):
    """GI/GJ: the dual KO is barely more lethal than GJ alone, so the pair does NOT buffer.

    Under the superseded max() baseline the delta was GI's (viable) effect minus the dual =
    +0.73 -> `strong`, i.e. GJ's own essentiality re-labelled as redundancy. This is the
    ERBB2/PTK2, PRMT5/PRMT8 and AR/ESRRA artifact in miniature.
    """
    fps = {p["partner_gene_symbol"]: p for p in reader.read_target_summary("GI")["functional_paralogs"]}
    gj = fps["GJ"]
    assert gj["dep_delta_paired_vs_max_single"] == pytest.approx(0.15, abs=0.03)
    assert gj["buffering_class"] == "none"


def test_strongest_partner_is_not_the_essential_one(reader):
    """The named strongest paralog must be the one with the real genetic interaction (GK, delta ~0.34),
    not the baseline-essential member whose inflated delta topped the max()-baseline ranking (GJ).
    Fleet-wide this mis-named strongest_paralog_symbol for 1384/4475 genes (30.9%)."""
    res = reader.read_target_summary("GI")
    assert res["strongest_paralog_symbol"] == "GK"
    assert res["paralog_buffering_class"] == "partial"
    assert res["strongest_paralog_delta"] == pytest.approx(0.34, abs=0.03)


def test_baseline_is_the_most_lethal_single_not_the_least(reader):
    """single_ko_effect is the baseline the delta is measured against, and it must be the MOST
    lethal single of the pair. For GI/GJ that is GJ (~-0.64), not GI (~-0.06)."""
    fps = {p["partner_gene_symbol"]: p for p in reader.read_target_summary("GI")["functional_paralogs"]}
    gj = fps["GJ"]
    assert gj["single_ko_effect"] == pytest.approx(-0.64, abs=0.03)
    # the identity holds on BOTH read paths (see _strongest_single)
    assert gj["dep_delta_paired_vs_max_single"] == pytest.approx(
        gj["single_ko_effect"] - gj["median_dual_ko_effect"], abs=1e-6
    )


def test_one_sided_baseline_uses_the_measured_member(reader):
    """GG/GH has NO single for either member -> unmeasured (never `none`). The one-sided case is
    the complement: a delta computed against the single member that IS measured, which stays a
    LOWER bound — the unmeasured member is not assumed neutral."""
    assert reader._strongest_single(-0.64, None) == pytest.approx(-0.64)
    assert reader._strongest_single(None, -0.06) == pytest.approx(-0.06)
    assert reader._strongest_single(None, None) is None  # NOT 0.0 — no fabricated viable baseline


# --- AM-3 (2026-08-05): RAW-CSV FALLBACK path — honest provenance + ohnolog=None ---
# The `reader` fixture forces this path (_derived_parquet_uri → None). The PRIMARY
# product-read path (with real ohnolog) is covered in test_derived_product_path.py.


def test_fallback_data_source_reports_raw_csv(reader):
    """On the raw-CSV FALLBACK, _data_source must say so (not claim the derived product). The
    derived product is named separately as the preferred/intended source — no misleading stamp."""
    res = reader.read_target_summary("GA")
    assert "ParalogGeneEffect.csv" in res["_data_source"]
    assert "raw" in res["_data_source"].lower()
    assert res["_intended_derived_product"] == "depmap-paralog-buffering-per-gene-v1"
    assert res["_data_source"] != "depmap-paralog-buffering-per-gene-v1"


def test_fallback_ohnolog_is_none_with_reason(reader):
    """On the fallback path the reader can't compute ohnolog (no Ensembl-Compara join), so it
    emits strongest_paralog_ohnolog=None WITH a documented reason — never omit or fabricate."""
    res = reader.read_target_summary("GA")  # a measured (strong) target
    assert "strongest_paralog_ohnolog" in res
    assert res["strongest_paralog_ohnolog"] is None
    assert "ohnolog" in res["_paralog_ohnolog_note"].lower()
    # also present (None) on the data_unavailable path
    empty = reader.read_target_summary("NOSUCHGENE")
    assert empty["strongest_paralog_ohnolog"] is None
