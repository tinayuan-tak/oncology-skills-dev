"""#715 (O): `_allgene_effect_percentile` previously recomputed `df["cohort"].str.upper() == cohort`
over the FULL ~101K-row cohort column on every call — a warm path fired once per gene query
(surface-abundance-density). The fix hoists that normalization into `_load_indexed`'s lru_cache
(built once per process, as `cohort_effect_null: dict[cohort_upper -> list[protein_effect_size]]`).

Pins numeric identity: percentile outputs on a real multi-cohort fixture are unchanged by the
hoist — computed via the OLD full-column-scan method vs. the NEW precomputed-dict method.
"""

from __future__ import annotations

import random

import pandas as pd
import pytest

from onc_methods.cptac_protein_deg import read as cptac


def _old_allgene_effect_percentile(df, cohort, effect_size):
    """The pre-#715 implementation (full-column `.str.upper()` scan every call), kept here only to
    prove the hoisted version is numerically identical."""
    from onc_methods.percentile_null import classify_percentile, percentile_rank

    try:
        null_vals = df.loc[df["cohort"].str.upper() == cohort, "protein_effect_size"].tolist()
    except Exception:
        return None, "data_unavailable"
    pct = percentile_rank(effect_size, null_vals)
    return pct, classify_percentile(pct)


def _fixture_df(n_per_cohort=400, seed=13):
    rng = random.Random(seed)
    rows = []
    for cohort in ("BRCA", "LUAD", "COAD"):
        for i in range(n_per_cohort):
            rows.append(
                {
                    "cohort": cohort,
                    "gene_symbol": f"GENE{cohort}{i}",
                    "protein_effect_size": rng.uniform(-4.0, 4.0),
                }
            )
    return pd.DataFrame(rows)


def test_hoisted_percentile_matches_old_full_scan_across_sampled_values():
    df = _fixture_df()
    cohort_effect_null = {}
    for cohort in df["cohort"].str.upper().unique():
        cohort_effect_null[cohort] = df.loc[df["cohort"].str.upper() == cohort, "protein_effect_size"].tolist()

    rng = random.Random(99)
    for _ in range(200):
        cohort = rng.choice(["BRCA", "LUAD", "COAD"])
        value = rng.uniform(-5.0, 5.0)
        old_pct, old_cls = _old_allgene_effect_percentile(df, cohort, value)
        new_pct, new_cls = cptac._allgene_effect_percentile(cohort_effect_null, cohort, value)
        assert new_pct == pytest.approx(old_pct)
        assert new_cls == old_cls


def test_hoisted_percentile_matches_old_full_scan_at_ties_min_max_and_nonfinite():
    df = _fixture_df()
    cohort_effect_null = {}
    for cohort in df["cohort"].str.upper().unique():
        cohort_effect_null[cohort] = df.loc[df["cohort"].str.upper() == cohort, "protein_effect_size"].tolist()

    brca_vals = df.loc[df["cohort"] == "BRCA", "protein_effect_size"].tolist()
    edge_values = [min(brca_vals), max(brca_vals), brca_vals[7], float("inf"), float("-inf"), float("nan"), None]
    for value in edge_values:
        old_pct, old_cls = _old_allgene_effect_percentile(df, "BRCA", value)
        new_pct, new_cls = cptac._allgene_effect_percentile(cohort_effect_null, "BRCA", value)
        assert new_pct == old_pct or (new_pct == pytest.approx(old_pct) if new_pct is not None else new_pct == old_pct)
        assert new_cls == old_cls


def test_unknown_cohort_degrades_to_none_not_a_crash():
    """A cohort absent from the precomputed dict (should not happen in practice — every cohort
    with rows is a key) degrades to an honest None/data_unavailable rather than a KeyError."""
    pct, cls = cptac._allgene_effect_percentile({}, "ZZZZ", 1.0)
    assert pct is None
    assert cls == "data_unavailable"
