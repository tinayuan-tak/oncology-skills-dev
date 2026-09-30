"""Adjacent-arm adequacy tier for the tumour-vs-normal selectivity read (#865).

The 2026-09-28 DGE product review found PAAD's tumour-vs-adjacent arm (cell A) statistically
non-informative — n_adjacent=4, corr(log2fc_A,log2fc_C)=0.14, canonical markers non-significant and
PRSS1 SIGN-REVERSED — because the TCGA PAAD "normals" are not true acinar-rich pancreas. A handful of
other cohorts (CESC/PCPG/GBM/READ/ESCA) have small-but-honest adjacent arms whose SIGNIFICANCE is
power-limited though direction stands.

This file pins the two orthogonal responses:
  1. BIOLOGY (curated, indication-keyed like the LAML INDICATION_NORMAL_CAVEAT precedent): PAAD's
     cell A is EXCLUDED — the row is recast GTEx-population-only and routes through the SAME FIX-4b
     machinery, so a formerly-`strong` call caps to `modest`. This is VERDICT-AFFECTING.
  2. POWER (n-keyed, sourced from the manifest cohort block, never a hardcoded n map): fit-floor <=
     n_adjacent <= 10 gets an ADDITIVE power caveat and NO classification change.

And the invariant the review's acceptance criteria names: an adequately-powered cohort's
classification is BYTE-IDENTICAL (the exclusion never fires, the row is never rebuilt).
"""

from __future__ import annotations

import pytest

from onc_methods.dge_deseq2 import read as dge
from onc_methods.dge_deseq2.read import _classify_selectivity_from_sensitivity as classify

CATALOG = dge.DATA_CATALOG  # portable sibling default, see methods.dge_deseq2.read (SK#2137)
requires_catalog = pytest.mark.skipif(
    not (CATALOG / "manifests" / "derived").is_dir(),
    reason=f"data-catalog checkout not present at {CATALOG}",
)

ADEQUACY_VOCAB = {"unreliable_excluded", "power_limited", "no_adjacent_arm", "adequate", "unknown"}


def _raw(**kw):
    """A raw sensitivity parquet row (UPPERCASE cell tags), as `read_..._gene_row` builds it."""
    base = dict(
        gene_symbol="X",
        cells_ran=2,
        cells_supporting=2,
        dominant_direction="up",
        sig_all_cells=True,
        discordant=False,
        max_abs_log2fc=2.0,
        log2fc_A=None,
        padj_A=None,
        log2fc_C=None,
        padj_C=None,
    )
    base.update(kw)
    return base


def _classifier_row_from_raw(raw: dict) -> dict:
    """Mirror the field-map the gene_row reader applies before calling the classifier."""
    return {
        "cells_ran": raw.get("cells_ran"),
        "cells_supporting": raw.get("cells_supporting"),
        "dominant_direction": raw.get("dominant_direction"),
        "sig_all_cells": raw.get("sig_all_cells"),
        "discordant": raw.get("discordant"),
        "max_abs_log2fc": raw.get("max_abs_log2fc"),
        "log2fc_cell_a": raw.get("log2fc_A"),
        "q_value_cell_a": raw.get("padj_A"),
        "log2fc_cell_c": raw.get("log2fc_C"),
        "q_value_cell_c": raw.get("padj_C"),
    }


# ── 1. PAAD reclassification: exclude cell A → GTEx-only → strong caps to modest ──────────────────
def test_excluded_adjacent_caps_strong_to_modest():
    # A gene that WOULD be strong on the full row: both families sig-up, both raw |lfc| >= 1.5.
    raw = _raw(log2fc_A=2.6, padj_A=1e-8, log2fc_C=3.1, padj_C=1e-30)
    assert classify(_classifier_row_from_raw(raw)) == "strong_tumor_selective"
    # After PAAD-style exclusion the adjacent arm is gone → single GTEx family → FIX-4b caps to modest.
    dge._rebuild_gtex_only_row(raw)
    row = _classifier_row_from_raw(raw)
    assert row["log2fc_cell_a"] is None and row["q_value_cell_a"] is None
    assert classify(row) == "modest_tumor_selective"


def test_excluded_adjacent_turns_a_conflict_into_a_clean_gtex_call():
    # Producer flags discordant because cell A (sig-DOWN, the spurious PAAD normals) conflicts with a
    # strong-up cell C. If we naively nulled only the per-cell fields but LEFT discordant=True, the
    # classifier would route to discordant_across_comparators. Rebuilding the aggregates prevents that.
    raw = _raw(
        dominant_direction="down",
        discordant=True,
        log2fc_A=-3.8,
        padj_A=1e-4,  # PRSS1-style sign-reversed adjacent
        log2fc_C=8.5,
        padj_C=1e-40,  # excellent GTEx signal
    )
    # On the FULL row this is the FIX-2 field-cancerization signature (adjacent sig-down + GTEx
    # strong-up) → field_effect_tumor_selective, a tumour-selective call that LEANS ON the spurious
    # PAAD adjacent arm. That is exactly the credit #865 removes.
    assert classify(_classifier_row_from_raw(raw)) == "field_effect_tumor_selective"
    dge._rebuild_gtex_only_row(raw)
    row = _classifier_row_from_raw(raw)
    assert row["discordant"] is False
    assert row["dominant_direction"] == "up"  # rebuilt from cell C's sign
    # Clean single-family GTEx-up call, capped at modest (no adjacent arm to earn strong).
    assert classify(row) == "modest_tumor_selective"


def test_paad_is_the_biology_keyed_exclusion():
    tier, caveat, exclude = dge._adjacent_arm_adequacy("paad-dge-tumor-vs-normal-sensitivity-v1", "PAAD")
    assert (tier, exclude) == ("unreliable_excluded", True)
    assert caveat and "acinar" in caveat and "population_normal_only" in caveat
    # Keyed on the indication, not the manifest — holds even with an unresolvable manifest_id.
    assert dge._adjacent_arm_adequacy(None, "PAAD")[2] is True


# ── 2. threshold boundary (n-keyed, from the manifest cohort block) ──────────────────────────────
@requires_catalog
@pytest.mark.parametrize(
    "indication,expected_tier",
    [
        ("CESC", "power_limited"),  # n_adjacent=3
        ("PCPG", "power_limited"),  # n_adjacent=3
        ("GBM", "power_limited"),  # n_adjacent=5
        ("READ", "power_limited"),  # n_adjacent=10 (upper boundary, inclusive)
        ("ESCA", "power_limited"),  # n_adjacent=10
        ("BLCA", "adequate"),  # n_adjacent=19 (first cohort above the ceiling)
        ("ACC", "no_adjacent_arm"),  # n_adjacent=0 (GTEx-only, arm never fit)
    ],
)
def test_power_tier_boundary_from_real_manifests(indication, expected_tier):
    mid = f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-v1"
    tier, caveat, exclude = dge._adjacent_arm_adequacy(mid, indication)
    assert tier == expected_tier, f"{indication}: {tier}"
    # A power caveat NEVER excludes cell A (direction stands) — classification is unchanged.
    assert exclude is False
    if expected_tier == "power_limited":
        assert caveat and "n_adjacent=" in caveat and "underpowered" in caveat
    else:
        assert caveat is None


@requires_catalog
def test_n_adjacent_is_sourced_from_the_manifest_cohort_block():
    # Not a hardcoded map: the value comes straight off the product's own manifest.
    assert dge._adjacent_cohort_meta("paad-dge-tumor-vs-normal-sensitivity-v1")[0] == 4
    assert dge._adjacent_cohort_meta("blca-dge-tumor-vs-normal-sensitivity-v1")[0] == 19


# ── 3. adequately-powered cohorts are BYTE-IDENTICAL (exclusion never fires) ─────────────────────
@requires_catalog
def test_adequate_cohort_classification_is_byte_identical():
    # The exclusion is what could change an adequate cohort's verdict. Prove it does not fire, and
    # that a strong adequate row is classified identically with the adequacy path present.
    for indication in ("BLCA", "LUAD", "BRCA", "COADREAD", "KIRC"):
        mid = f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-v1"
        assert dge._adjacent_arm_adequacy(mid, indication)[2] is False, indication
    # A strong adequate row is untouched by the adequacy machinery (never rebuilt) → same class.
    raw = _raw(log2fc_A=2.6, padj_A=1e-8, log2fc_C=3.1, padj_C=1e-30)
    before = classify(_classifier_row_from_raw(raw))
    # Simulate the reader path for an ADEQUATE cohort: exclude=False → _rebuild_gtex_only_row NOT called.
    assert before == classify(_classifier_row_from_raw(raw))  # idempotent, cell A retained
    assert before == "strong_tumor_selective"


# ── 4. vocabulary closed + every rung reachable ──────────────────────────────────────────────────
@requires_catalog
def test_adequacy_vocabulary_is_closed_and_reachable_over_the_corpus():
    glob = "manifests/derived/*-dge-tumor-vs-normal-sensitivity-v1.yaml"
    ids = sorted(p.stem for p in CATALOG.glob(glob))
    assert len(ids) >= 5
    tiers = set()
    for mid in ids:
        indication = mid.split("-dge-")[0].upper()
        t, _, _ = dge._adjacent_arm_adequacy(mid, indication)
        assert t in ADEQUACY_VOCAB, f"{mid}: off-vocabulary tier {t!r}"
        tiers.add(t)
    # The three tiers the review's cohorts populate must all be reachable on the shipped corpus.
    assert {"unreliable_excluded", "power_limited", "adequate"} <= tiers, tiers
    # `unknown` = a product whose manifest carries no cohort.n_adjacent. The ONLY such product today
    # is the NSCLC pooled composite (its cohort backfill is tracked in data-catalog #702); any OTHER
    # product falling into unknown means a manifest lost cohort.n_adjacent and must be caught.
    unknown = {
        mid.split("-dge-")[0].upper()
        for mid in ids
        if dge._adjacent_arm_adequacy(mid, mid.split("-dge-")[0].upper())[0] == "unknown"
    }
    assert unknown <= {"NSCLC"}, f"unexpected products without cohort.n_adjacent: {unknown - {'NSCLC'}}"
