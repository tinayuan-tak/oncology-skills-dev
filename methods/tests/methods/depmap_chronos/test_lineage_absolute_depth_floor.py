"""Absolute-depth admissibility floor on enriched_lineages (2026-09-12).

The enrichment test is RELATIVE (Mann-Whitney lineage-vs-rest + delta_vs_rest), so on its own it
cannot distinguish "this lineage is genuinely dependent and the rest of the panel is not" from
"this lineage is trivially less-neutral than a neutral panel". Because `lineage_selective` outranks
the `non_dependent` veto in dependency.resolver.yaml, the latter would license a positive verdict on
no absolute signal. This module pins the floor that closes it, and — critically — pins that the floor
is evaluated at the finest ADEQUATELY-POWERED grain, so a sublineage-restricted dependency whose
coarse-lineage median is diluted (IRF4/PCM inside Lymphoid, SPI1/AML inside Myeloid) is NOT lost.

Synthetic panels (no S3).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "onc_methods" / "depmap_chronos" / "cli.py"


def _load():
    spec = importlib.util.spec_from_file_location("chr_depth_cli", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["chr_depth_cli"] = m
    spec.loader.exec_module(m)
    return m


cli = _load()


def _panel(code_rows: dict):
    """{ (lineage, code): [scores] } → (chronos_by_model, model_metadata w/ OncotreeCode)."""
    chronos, meta, i = {}, {}, 0
    for (lineage, code), scores in code_rows.items():
        for s in scores:
            mid = f"ACH-{i:05d}"
            chronos[mid] = float(s)
            meta[mid] = {"ModelID": mid, "OncotreeLineage": lineage, "OncotreeCode": code}
            i += 1
    return chronos, meta


def _neutral(n, base=0.0):
    # Small spread so Mann-Whitney has ties to break; centred at `base`.
    return [base + 0.01 * (k % 7) for k in range(n)]


def _at(n, depth):
    return [depth + 0.01 * (k % 7) for k in range(n)]


def test_shallow_relative_hit_does_not_reach_lineage_selective():
    """A lineage significantly LESS neutral than a neutral panel is not a dependency."""
    chronos, meta = _panel(
        {
            ("Shallow", "SHAL"): _at(30, -0.40),  # clears delta_vs_rest <= -0.3, but not the -0.5 depth cut
            ("RestA", "RA"): _neutral(60, 0.0),
            ("RestB", "RB"): _neutral(60, 0.02),
        }
    )
    s = cli.compute_lineage_summary(chronos, meta, min_n_lineage=5)
    assert s["enrichment_class"] != "lineage_selective", s["enrichment_class"]
    assert s["n_enriched_lineages"] == 0
    # Not silently dropped — disclosed on the verdict-inert list.
    assert s["n_relative_only_enriched_lineages"] >= 1
    assert {r["lineage"] for r in s["relative_only_enriched_lineages"]} == {"Shallow"}


def test_deep_lineage_still_reaches_lineage_selective():
    """The true-positive shape must survive the floor: a near-zero POOLED median is what
    selectivity looks like, so the floor is applied to the LINEAGE's depth, never the panel's."""
    chronos, meta = _panel(
        {
            ("Deep", "DP"): _at(30, -1.20),
            ("RestA", "RA"): _neutral(60, 0.0),
            ("RestB", "RB"): _neutral(60, 0.02),
        }
    )
    s = cli.compute_lineage_summary(chronos, meta, min_n_lineage=5)
    assert s["enrichment_class"] == "lineage_selective"
    assert [r["lineage"] for r in s["enriched_lineages"]] == ["Deep"]
    assert s["enriched_lineages"][0]["depth_cleared_at_grain"] == "lineage"
    # Pooled panel median is shallow — that is selectivity, not a disqualification.
    assert s["median_chronos_panel"] > -0.5


def test_sublineage_restricted_dependency_clears_a_diluted_coarse_median():
    """The IRF4/PCM shape: the coarse lineage median is diluted above the cut, but an
    adequately-powered constituent OncotreeCode is deeply dependent. Must still be admitted,
    and must NAME the sublineage that carried the call."""
    chronos, meta = _panel(
        {
            # Mirrors IRF4 26Q1: Lymphoid pools to -0.455 while PCM sits at -2.041.
            ("Lymphoid", "PCM"): _at(15, -2.00),  # myeloma — the real dependency
            ("Lymphoid", "AMLNOS"): _at(35, -0.42),  # dilutes the coarse median above -0.5
            ("RestA", "RA"): _neutral(60, 0.0),
            ("RestB", "RB"): _neutral(60, 0.02),
        }
    )
    s = cli.compute_lineage_summary(chronos, meta, min_n_lineage=5)
    lymphoid = next(r for r in s["per_lineage_stats"] if r["lineage"] == "Lymphoid")
    assert lymphoid["median_chronos"] > -0.5, "fixture must dilute the coarse median above the cut"
    assert s["enrichment_class"] == "lineage_selective"
    admitted = next(r for r in s["enriched_lineages"] if r["lineage"] == "Lymphoid")
    assert admitted["depth_cleared_at_grain"] == "oncotree_code"
    assert [x["oncotree_code"] for x in admitted["depth_cleared_sublineages"]] == ["PCM"]


def test_underpowered_sublineage_cannot_rescue_a_shallow_lineage():
    """A sublineage below the enrichment table's own n floor must not carry a positive verdict."""
    chronos, meta = _panel(
        {
            ("Shallow", "TINY"): _at(3, -2.00),  # deep but n=3 < min_n_lineage
            ("Shallow", "BULK"): _at(30, -0.40),
            ("RestA", "RA"): _neutral(60, 0.0),
            ("RestB", "RB"): _neutral(60, 0.02),
        }
    )
    s = cli.compute_lineage_summary(chronos, meta, min_n_lineage=5)
    assert s["n_enriched_lineages"] == 0, s["enriched_lineages"]
    assert s["enrichment_class"] != "lineage_selective"


def test_floor_fields_always_present():
    """Fail-closed shape: the disclosure fields exist even on an empty / degenerate panel, so a
    consumer never has to distinguish 'absent key' from 'no relative-only hits'."""
    for chronos, meta in (({}, {}), _panel({("Only", "ONE"): _neutral(10, 0.0)})):
        s = cli.compute_lineage_summary(chronos, meta, min_n_lineage=5)
        assert "relative_only_enriched_lineages" in s
        assert "n_relative_only_enriched_lineages" in s
        assert s["n_relative_only_enriched_lineages"] == 0
