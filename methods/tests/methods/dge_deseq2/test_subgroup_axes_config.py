"""Config-drive + reconciliation teeth for the by-subgroup DGE axes (analysis-methods#738).

`config/subgroup_axes.yaml` maps each by-subgroup indication -> an ordered list of
(axis, assignments_manifest, strata) triples. This file pins:

  1. self-consistency: the indications keyed in `subgroup_axes` equal the by-subgroup roster declared
     in `run_ledger_intent()["subgroup"]["recount3"]` (drift either way is a bug), and the assert
     actually FIRES on injected drift;
  2. every mapped `assignments_manifest` resolves to a real data-catalog derived manifest (all 11 on
     main today) — the positive control for the reconciliation teeth;
  3. MUTATION teeth: a bogus mapped manifest id makes `subgroup_axis_reconciliation` return a
     non-empty, id-naming error list (never green-on-empty);
  4. `expected_products()` projects all six `<ind>-...-by-subgroup-v1` ids and the 41-product universe.

Hermetic apart from the `requires_catalog` positive controls (which read manifest filenames only).
"""

from __future__ import annotations

import pytest

from methods.dge_deseq2 import config as cfg
from methods.dge_deseq2 import read as dge
from methods.dge_deseq2.build_run_ledger import expected_products

CATALOG = dge.DATA_CATALOG  # portable sibling default, see methods.dge_deseq2.read (SK#2137)

requires_catalog = pytest.mark.skipif(
    not (CATALOG / "manifests" / "derived").is_dir(),
    reason=f"data-catalog checkout not present at {CATALOG}",
)

_SIX = ("coadread", "esca", "hnsc", "nsclc", "paad", "stad")


# ── 1. self-consistency ──────────────────────────────────────────────────────
def test_subgroup_axes_keys_equal_the_declared_recount3_roster():
    keyed = set(cfg.subgroup_axes())
    declared = set(cfg.run_ledger_intent()["subgroup"]["recount3"])
    assert keyed == declared, f"{sorted(keyed)} != {sorted(declared)}"
    assert keyed == {"COADREAD", "ESCA", "HNSC", "NSCLC", "PAAD", "STAD"}


def test_self_consistency_assert_fires_on_injected_drift(monkeypatch):
    """The loader must FAIL LOUD if the curated indications drift from the ledger roster — a green
    loader that silently tolerates drift would desync the orchestrator from the run-ledger."""
    cfg.subgroup_axes.cache_clear()
    monkeypatch.setattr(cfg, "run_ledger_intent", lambda: {"subgroup": {"recount3": ["COADREAD"]}})
    with pytest.raises(AssertionError, match="drift either way is a bug"):
        cfg.subgroup_axes()
    cfg.subgroup_axes.cache_clear()  # drop the failed call's state; next real call re-derives


def test_every_axis_carries_the_expected_triple_shape():
    for ind, axes in cfg.subgroup_axes().items():
        assert axes, f"{ind} has no curated axes"
        for ax in axes:
            assert set(ax) >= {"axis", "assignments_manifest", "strata"}, ax
            assert isinstance(ax["strata"], list) and ax["strata"], ax


# ── 2. every mapped assignment manifest resolves (positive control) ──────────
@requires_catalog
def test_all_mapped_assignment_manifests_exist_in_the_catalog():
    assert cfg.subgroup_axis_reconciliation(CATALOG) == []


@requires_catalog
def test_mapped_manifests_are_the_eleven_on_main():
    mapped = {ax["assignments_manifest"] for axes in cfg.subgroup_axes().values() for ax in axes}
    derived = CATALOG / "manifests" / "derived"
    for mid in mapped:
        assert (derived / f"{mid}.yaml").is_file(), mid
    assert len(mapped) == 11


# ── 3. MUTATION teeth ────────────────────────────────────────────────────────
def test_reconciliation_flags_a_bogus_mapped_manifest(monkeypatch):
    """A curated axis pointing at an assignment product with no manifest must RED (fail-open guard)."""
    bogus = {"COADREAD": [{"axis": "bogus_axis", "assignments_manifest": "tcga-does-not-exist-v1", "strata": ["X"]}]}
    monkeypatch.setattr(cfg, "subgroup_axes", lambda: bogus)
    errs = cfg.subgroup_axis_reconciliation(CATALOG)
    assert errs, "a mapped-but-missing manifest produced no error — the teeth are toothless"
    assert any("tcga-does-not-exist-v1" in e for e in errs), errs


def test_reconciliation_is_clean_on_the_real_config_positive_control(monkeypatch):
    """Positive control paired with the mutation above: the real config over the real catalog is
    clean, so the mutation test's non-empty result is meaningful, not a constant."""
    if not (CATALOG / "manifests" / "derived").is_dir():
        pytest.skip(f"data-catalog checkout not present at {CATALOG}")
    assert cfg.subgroup_axis_reconciliation(CATALOG) == []


# ── 4. expected_products projection ──────────────────────────────────────────
def test_expected_products_includes_six_subgroup_ids_and_totals_41():
    exp = expected_products()
    for ind in _SIX:
        assert f"{ind}-dge-tumor-vs-normal-sensitivity-by-subgroup-v1" in exp
    assert len(exp) == 41, sorted(exp)
