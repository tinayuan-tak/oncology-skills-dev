"""Tests for the re-derived paralog buffering metric (dep_delta_paired_vs_max_single).

PR-B' (2026-07-17): the reader was aligned to the card + rule contract. Previously it
emitted strong/moderate/weak/none off the RAW dual-KO Chronos effect (conflating
buffering with baseline essentiality); moderate/weak matched no rule and the
`partial` rule was dead. Now it emits strong/partial/none off
    delta = max(single_a, single_b) - median_dual
(the additional lethality of the dual KO over the best single = true buffering).

Hermetic: monkeypatches _ensure_paralog_cached to a synthetic CSV in tmp — the real
~/.cache is never touched (cache-pollution discipline).
"""
from __future__ import annotations

import importlib
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
    """
    header = [
        "ModelID",
        "GA", "GB", "GC", "GD", "GE", "GF",          # single-KO baselines (~0 = viable)
        "GA_GB", "GC_GD", "GE_GF", "GG_GH",          # dual-KO pairs
        "AAVS1_chr2",                                 # control — must be skipped
    ]
    rows = [
        ["ACH-1", 0.0, 0.05, -0.02, 0.0, 0.01, 0.0,  -1.20, -0.34, 0.01, -1.4, -0.5],
        ["ACH-2", 0.02, 0.0, 0.0, -0.03, 0.0, 0.02,  -1.25, -0.36, -0.01, -1.5, -0.6],
        ["ACH-3", 0.0, 0.01, 0.01, 0.0, -0.01, 0.0,  -1.18, -0.35, 0.00, -1.3, -0.4],
    ]
    csv_path = _write_csv(tmp_path, header, rows)
    monkeypatch.setattr(R, "_ensure_paralog_cached", lambda: csv_path)
    # Force the RAW-CSV FALLBACK path: pretend the derived product is unreachable so these
    # buffering-MATH tests exercise the live recompute (the primary product-read path is
    # covered separately in test_derived_product_path.py). _derived_parquet_uri → None makes
    # _read_from_derived_product return None → read_target_summary falls back to _read_from_raw_csv.
    monkeypatch.setattr(R, "_derived_parquet_uri", lambda: None)
    return R


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
    """delta = max(single) - median_dual → POSITIVE when the dual KO is more lethal
    than either single (Chronos: more-negative = more lethal)."""
    res = reader.read_target_summary("GA")
    fp = res["functional_paralogs"][0]
    assert fp["median_dual_ko_effect"] < 0          # dual KO is lethal
    assert fp["single_ko_effect"] > fp["median_dual_ko_effect"]  # single less lethal
    assert fp["dep_delta_paired_vs_max_single"] == pytest.approx(
        fp["single_ko_effect"] - fp["median_dual_ko_effect"], abs=1e-6)


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
    res = reader.read_target_summary("GA")               # a measured (strong) target
    assert "strongest_paralog_ohnolog" in res
    assert res["strongest_paralog_ohnolog"] is None
    assert "ohnolog" in res["_paralog_ohnolog_note"].lower()
    # also present (None) on the data_unavailable path
    empty = reader.read_target_summary("NOSUCHGENE")
    assert empty["strongest_paralog_ohnolog"] is None
