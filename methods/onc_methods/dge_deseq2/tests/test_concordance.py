"""Tests for the cross-substrate reproducibility concordance QC (S3c, #732).

The hermetic tests build synthetic gene-id-authority + products so the pure
join/metric/reconciliation path runs with no S3, and prove the fail-loud teeth
by perturbing ONE axis of a GREEN baseline (empty join, degenerate gated set)
into a RED. The live test (env-gated) reproduces the ad-hoc S1b COADREAD signal
(cell A/C Spearman ~0.92-0.97) as a checked assertion.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from onc_methods.dge_deseq2 import concordance as C
from onc_methods.dge_deseq2.concordance import (
    ConcordanceError,
    ConcordancePair,
    concordance_for_cell,
    coverage_denominators,
    declared_concordance_pairs,
    resolve_products,
)

# --------------------------------------------------------------------------- #
# synthetic fixtures (raw inputs — the metrics are RE-DERIVED in the test, so a
# derived fixture can never falsely pass; store the inputs, compute the numbers)
# --------------------------------------------------------------------------- #
_N = 400


def _authority(n: int = _N, *, drift_split_symbol: bool = False) -> pd.DataFrame:
    """A minimal authority: n genes, same symbol in both namespaces, plus one
    ambiguous collapse (a symbol backing two recount3 genes). When
    `drift_split_symbol` is set, gene 0 carries a DIFFERENT symbol in each
    namespace (recount3='OLD', xena='NEW') — a symbol-string join would drop it,
    the gene_id join keeps it."""
    gids = [f"ENSG{i:05d}" for i in range(n)]
    hgnc = [f"SYM{i}" for i in range(n)]
    gencode = list(hgnc)
    if drift_split_symbol:
        hgnc[0], gencode[0] = "OLD", "NEW"
    auth = pd.DataFrame(
        {
            "gene_id": gids,
            "symbol_hgnc": hgnc,
            "symbol_gencode_v23": gencode,
            "symbol_drift": [False] * n,
            "symbol_reuse_conflict": [False] * n,
        }
    )
    # one extra gene making SYM1 ambiguous in the recount3 (symbol_hgnc) namespace
    extra = pd.DataFrame(
        [
            {
                "gene_id": "ENSG_AMBIG",
                "symbol_hgnc": "SYM1",
                "symbol_gencode_v23": "ZZZAMB",
                "symbol_drift": False,
                "symbol_reuse_conflict": False,
            }
        ]
    )
    return pd.concat([auth, extra], ignore_index=True)


def _correlated_products(seed: int = 0, *, all_sig: bool = True, drift_split_symbol: bool = False):
    """Two products with strongly-correlated per-cell log2fc across substrates."""
    rng = np.random.default_rng(seed)
    hgnc = [f"SYM{i}" for i in range(_N)]
    gencode = list(hgnc)
    if drift_split_symbol:
        hgnc[0], gencode[0] = "OLD", "NEW"
    base = rng.normal(0, 2, _N)
    lfc_r = base + rng.normal(0, 0.3, _N)
    lfc_x = base + rng.normal(0, 0.3, _N)
    padj = rng.uniform(0, 0.02, _N) if all_sig else rng.uniform(0.2, 0.9, _N)

    def _prod(symbols, lfc):
        return pd.DataFrame(
            {"gene_symbol": symbols, "log2fc_A": lfc, "padj_A": padj, "log2fc_C": lfc * 0.9, "padj_C": padj}
        )

    return _prod(hgnc, lfc_r), _prod(gencode, lfc_x)


# --------------------------------------------------------------------------- #
# coverage denominators
# --------------------------------------------------------------------------- #
def test_coverage_accounts_for_every_row():
    auth = _authority()
    r_prod, x_prod = _correlated_products()
    r_res, _ = resolve_products(r_prod, x_prod, auth)
    cov = coverage_denominators(r_res, "recount3")
    assert cov.n_product_rows == _N
    # SYM1 is ambiguous in recount3 namespace -> dropped from the usable universe
    assert cov.n_ambiguous_dropped == 1
    assert cov.n_unmapped_dropped == 0
    assert cov.n_usable_gene_id == _N - 1
    # buckets partition the product exactly
    assert cov.n_mapped == cov.n_product_rows - cov.n_unmapped_dropped


# --------------------------------------------------------------------------- #
# the concordance metric
# --------------------------------------------------------------------------- #
def test_concordance_computes_and_is_labelled_reproducibility_only():
    auth = _authority()
    r_prod, x_prod = _correlated_products()
    r_res, x_res = resolve_products(r_prod, x_prod, auth)
    cc = concordance_for_cell(r_res, x_res, "A", "TEST")
    assert cc.reproducibility_only is True
    assert cc.spearman_rho > 0.9  # correlated inputs -> high rho
    assert cc.n_gated == cc.n_shared_gene_id  # all_sig fixture
    assert cc.n_shared_gene_id == _N - 1  # SYM1 ambiguous dropped
    assert set(cc.coverage) == {"recount3", "xena_toil"}


def test_ambiguous_and_unmapped_never_enter_the_join():
    """A fused (ambiguous) symbol and an unmapped symbol must be excluded from the
    shared-gene set — they have no single stable id to join on."""
    auth = _authority()
    r_prod, x_prod = _correlated_products()
    # inject an unmapped symbol into recount3
    r_prod.loc[0, "gene_symbol"] = "NOT_IN_AUTHORITY"
    r_res, x_res = resolve_products(r_prod, x_prod, auth)
    cc = concordance_for_cell(r_res, x_res, "A", "TEST")
    # SYM1 ambiguous (both sides) + the one now-unmapped recount3 symbol dropped
    assert cc.n_shared_gene_id == _N - 2


def test_gene_id_join_recovers_a_symbol_drift_that_a_symbol_join_would_drop():
    """The core reason this QC joins on gene_id, not symbol: a gene whose symbol
    drifted between the two substrate vocabularies (recount3 'OLD' vs xena 'NEW')
    is a SHARED gene under the authority gene_id, but a naive symbol merge would
    silently drop it."""
    auth = _authority(drift_split_symbol=True)
    r_prod, x_prod = _correlated_products(drift_split_symbol=True)
    r_res, x_res = resolve_products(r_prod, x_prod, auth)
    cc = concordance_for_cell(r_res, x_res, "A", "TEST")
    # gene_id join keeps ENSG00000 (OLD<->NEW); a symbol merge on gene_symbol would not
    naive_symbol_shared = set(r_prod["gene_symbol"]) & set(x_prod["gene_symbol"])
    assert "OLD" not in naive_symbol_shared and "NEW" not in naive_symbol_shared
    assert "ENSG00000" in set(r_res.loc[r_res["gene_symbol"] == "OLD", "gene_id"])
    # the drifted gene is counted in the shared gene_id set (SYM1 ambiguous still dropped)
    assert cc.n_shared_gene_id == _N - 1


# --------------------------------------------------------------------------- #
# fail-loud teeth (mutation: one-axis perturbation of a GREEN baseline -> RED)
# --------------------------------------------------------------------------- #
def test_empty_join_raises_not_green_on_empty():
    """Disjoint gene sets between substrates -> zero shared genes -> FAIL LOUD."""
    n = _N
    gids_r = [f"ENSG{i:05d}" for i in range(n)]
    gids_x = [f"ENSGX{i:05d}" for i in range(n)]
    syms_r = [f"R{i}" for i in range(n)]
    syms_x = [f"X{i}" for i in range(n)]
    auth = pd.DataFrame(
        {
            "gene_id": gids_r + gids_x,
            "symbol_hgnc": syms_r + [None] * n,
            "symbol_gencode_v23": [None] * n + syms_x,
            "symbol_drift": [False] * (2 * n),
            "symbol_reuse_conflict": [False] * (2 * n),
        }
    )
    padj = np.full(n, 0.01)
    lfc = np.linspace(-3, 3, n)
    r_prod = pd.DataFrame({"gene_symbol": syms_r, "log2fc_A": lfc, "padj_A": padj, "log2fc_C": lfc, "padj_C": padj})
    x_prod = pd.DataFrame({"gene_symbol": syms_x, "log2fc_A": lfc, "padj_A": padj, "log2fc_C": lfc, "padj_C": padj})
    r_res, x_res = resolve_products(r_prod, x_prod, auth)  # each resolves fine on its own
    with pytest.raises(ConcordanceError, match="degenerate"):
        concordance_for_cell(r_res, x_res, "A", "TEST")


def test_degenerate_gated_set_raises():
    """Genes are shared but none are significant in BOTH substrates -> the Spearman
    would be over an empty/tiny set -> FAIL LOUD rather than emit a NaN rho."""
    auth = _authority()
    r_prod, x_prod = _correlated_products(all_sig=False)  # padj all >> 0.05
    r_res, x_res = resolve_products(r_prod, x_prod, auth)
    with pytest.raises(ConcordanceError, match="significant"):
        concordance_for_cell(r_res, x_res, "A", "TEST")


def test_min_shared_floor_is_load_bearing():
    """A shared set above 0 but below min_shared still reds (the floor, not just emptiness)."""
    auth = _authority()
    r_prod, x_prod = _correlated_products()
    r_res, x_res = resolve_products(r_prod, x_prod, auth)
    # succeeds at a low floor, reds when the floor exceeds the shared count
    ok = concordance_for_cell(r_res, x_res, "A", "TEST", min_shared=10)
    with pytest.raises(ConcordanceError, match="degenerate"):
        concordance_for_cell(r_res, x_res, "A", "TEST", min_shared=ok.n_shared_gene_id + 1)


# --------------------------------------------------------------------------- #
# discovery + reconciliation
# --------------------------------------------------------------------------- #
def test_declared_pairs_are_the_both_substrate_intersection():
    intent = {"sensitivity": {"recount3": ["COADREAD", "LUAD", "BRCA"], "xena_toil": ["COADREAD", "BRCA"]}}
    pairs = declared_concordance_pairs(intent)
    assert [p.indication for p in pairs] == ["BRCA", "COADREAD"]
    assert pairs[0] == ConcordancePair(
        "BRCA", "brca-dge-tumor-vs-normal-sensitivity-v1", "brca-dge-tumor-vs-normal-sensitivity-xenatoil-v1"
    )


def test_no_declared_pair_raises_not_vacuous_green():
    intent = {"sensitivity": {"recount3": ["LUAD"], "xena_toil": []}}
    with pytest.raises(ConcordanceError, match="nothing to compare"):
        declared_concordance_pairs(intent)


def test_build_concordance_reconciles_missing_manifest(tmp_path):
    """A declared pair whose manifest is absent surfaces as a divergence and is
    skipped for compute — a missing product must RED, not silently shrink the set."""
    (tmp_path / "manifests" / "derived").mkdir(parents=True)
    intent = {"sensitivity": {"recount3": ["COADREAD"], "xena_toil": ["COADREAD"]}}
    auth = _authority()
    r_prod, x_prod = _correlated_products()
    reads = {
        "coadread-dge-tumor-vs-normal-sensitivity-v1": r_prod,
        "coadread-dge-tumor-vs-normal-sensitivity-xenatoil-v1": x_prod,
    }
    # no manifest files written -> both manifests missing -> divergence, no rows
    rows, div = C.build_concordance(tmp_path, reader=lambda mid: reads[mid], authority=auth, intent=intent)
    assert rows == []
    assert len(div) == 1 and "missing manifest" in div[0]


def test_build_concordance_computes_when_manifests_present(tmp_path):
    derived = tmp_path / "manifests" / "derived"
    derived.mkdir(parents=True)
    intent = {"sensitivity": {"recount3": ["COADREAD"], "xena_toil": ["COADREAD"]}}
    for mid in ("coadread-dge-tumor-vs-normal-sensitivity-v1", "coadread-dge-tumor-vs-normal-sensitivity-xenatoil-v1"):
        (derived / f"{mid}.yaml").write_text("id: x\n")
    auth = _authority()
    r_prod, x_prod = _correlated_products()
    reads = {
        "coadread-dge-tumor-vs-normal-sensitivity-v1": r_prod,
        "coadread-dge-tumor-vs-normal-sensitivity-xenatoil-v1": x_prod,
    }
    rows, div = C.build_concordance(tmp_path, reader=lambda mid: reads[mid], authority=auth, intent=intent)
    assert div == []
    assert {r.cell for r in rows} == {"A", "C"}
    assert all(r.indication == "COADREAD" and r.reproducibility_only for r in rows)


def test_report_round_trips(tmp_path):
    derived = tmp_path / "manifests" / "derived"
    derived.mkdir(parents=True)
    intent = {"sensitivity": {"recount3": ["COADREAD"], "xena_toil": ["COADREAD"]}}
    for mid in ("coadread-dge-tumor-vs-normal-sensitivity-v1", "coadread-dge-tumor-vs-normal-sensitivity-xenatoil-v1"):
        (derived / f"{mid}.yaml").write_text("id: x\n")
    auth = _authority()
    r_prod, x_prod = _correlated_products()
    reads = {
        "coadread-dge-tumor-vs-normal-sensitivity-v1": r_prod,
        "coadread-dge-tumor-vs-normal-sensitivity-xenatoil-v1": x_prod,
    }
    rows, div = C.build_concordance(tmp_path, reader=lambda mid: reads[mid], authority=auth, intent=intent)
    out = tmp_path / "concordance.json"
    C._write_report(rows, div, out)
    import json

    payload = json.loads(out.read_text())
    assert payload["reproducibility_only"] is True
    assert payload["n_rows"] == 2
    assert "not biological validation" in payload["note"].lower()


# --------------------------------------------------------------------------- #
# live / real-clone check — reproduces the ad-hoc S1b COADREAD signal
# --------------------------------------------------------------------------- #
def _real_catalog_root() -> Path | None:
    from onc_methods.dge_deseq2.read import DATA_CATALOG

    root = Path(os.environ.get("DATA_CATALOG_ROOT") or DATA_CATALOG)
    return root if (root / "manifests" / "derived").is_dir() else None


@pytest.mark.skipif(
    not os.environ.get("DGE_CONCORDANCE_LIVE_S3"),
    reason="live S3 cross-substrate read — set DGE_CONCORDANCE_LIVE_S3=1 to run locally with cbg creds",
)
def test_real_coadread_reproduces_adhoc_spearman_signal():
    """The tested form of the ad-hoc S1b finding: recount3-vs-Xena/Toil COADREAD
    concordance is ~0.92-0.97 for cells A and C (reproducibility-only)."""
    root = _real_catalog_root()
    assert root is not None, "live test requires the data-catalog clone"
    rows, divergences = C.build_concordance(root)
    assert divergences == [], divergences
    by_cell = {r.cell: r for r in rows if r.indication == "COADREAD"}
    assert set(by_cell) == {"A", "C"}
    for cell, r in by_cell.items():
        assert 0.90 <= r.spearman_rho <= 0.98, (cell, r.spearman_rho)
        assert r.n_gated >= C.DEFAULT_MIN_GATED
        assert r.reproducibility_only is True
    # The GTEx tissue-composition confound (epithelial-marker discordance) concentrates
    # in cell C (tumor vs whole-tissue GTEx colon), not cell A (tumor vs adjacent-normal):
    # cell C carries materially more sign-discordant significant genes across substrates.
    assert by_cell["C"].n_sign_discordant > by_cell["A"].n_sign_discordant
