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

REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
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
