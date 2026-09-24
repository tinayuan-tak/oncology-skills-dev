"""Teeth for the S5 batch run ledger (analysis-methods#698).

The acceptance is mutation-style: ``--self-check`` must RED on an INJECTED divergence, for the
RIGHT reason. Every reconciliation test starts from a green baseline (three consistent sources ->
zero divergences) and then perturbs exactly ONE axis, asserting (a) the baseline was green so the
red is caused by the perturbation and (b) the specific divergence code fires. The three asymmetry
classes from the plan-review — present-not-declared, declared-not-present, manifest-without-config —
each get a case, as does every QC failure mode. QC is proven independent (re-derived from the
dataframe bytes, never a recorded status), and the vacuous-ledger failure mode is guarded.

All reconciliation tests are hermetic (injected fixtures) so they carry the teeth in CI. Two extra
tests reconcile the REAL catalog / read the REAL S3 products; they skip cleanly when the sibling
clone or creds are absent and are the local "green for the right reason" check.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest
import yaml

from methods.dge_deseq2 import build_run_ledger as B
from methods.dge_deseq2.build_run_ledger import CatalogedProduct, ExpectedProduct


# --------------------------------------------------------------------------- #
# expected_products from the real config intent
# --------------------------------------------------------------------------- #
def test_expected_products_from_config_is_the_37_product_universe():
    exp = B.expected_products()
    # 28 recount3 sensitivity (27 published + NSCLC) + 1 xenatoil sens + 2 AG + 3 subgroup + 3 singletons
    assert len(exp) == 37, sorted(exp)
    assert "coadread-dge-tumor-vs-normal-sensitivity-v1" in exp
    assert "nsclc-dge-tumor-vs-normal-sensitivity-v1" in exp  # the extra composite
    assert "coadread-dge-tumor-vs-normal-sensitivity-xenatoil-v1" in exp
    assert "coadread-dge-adj-vs-gtex-v1" in exp
    assert "coadread-dge-adj-vs-gtex-xenatoil-v1" in exp
    assert "coadread-dge-tumor-vs-normal-sensitivity-by-subgroup-v1" in exp
    assert {
        "pancan-dge-tumor-vs-normal-v1",
        "dge-deseq2-qc-index-v1",
        "gencode-v26-gene-lengths-union-of-exons-v1",
    } <= set(exp)
    # substrate axis populated on the sensitivity family
    assert exp["coadread-dge-tumor-vs-normal-sensitivity-xenatoil-v1"].substrate == "xena_toil"
    assert exp["coadread-dge-tumor-vs-normal-sensitivity-v1"].substrate == "recount3"


def test_expected_products_rejects_duplicate_intent_id():
    intent = {"singletons": [{"id": "dup-v1", "role": "qc_index", "substrate": None}] * 2}
    with pytest.raises(ValueError, match="duplicate expected product id"):
        B.expected_products(intent)


# --------------------------------------------------------------------------- #
# green baseline + the three asymmetry classes (one-axis mutation, right reason)
# --------------------------------------------------------------------------- #
def _baseline():
    """Three consistent sources over a small mixed-family universe."""
    expected = {
        "coadread-dge-tumor-vs-normal-sensitivity-v1": ExpectedProduct(
            "coadread-dge-tumor-vs-normal-sensitivity-v1", "COADREAD", "recount3", "tumor-vs-normal", "verdict-input"
        ),
        "coadread-dge-adj-vs-gtex-v1": ExpectedProduct(
            "coadread-dge-adj-vs-gtex-v1", "COADREAD", "recount3", "adjacent-vs-gtex", "secondary-diagnostic"
        ),
        "dge-deseq2-qc-index-v1": ExpectedProduct("dge-deseq2-qc-index-v1", None, None, "qc-index", "qc_index"),
    }
    manifests = {
        cid: CatalogedProduct(
            catalog_id=cid,
            notebook="methods/dge_deseq2/x.py",
            s3_uri=f"s3://onc-compbio/data-catalog/derived/{cid}/p.parquet",
            git_commit="abc123",
            created_date="2026-07-06",
            indication=(exp.indication or None),
            substrate_raw=("recount3-tcga-gtex-2023-01-04" if exp.substrate == "recount3" else None),
        )
        for cid, exp in expected.items()
    }
    s3 = set(expected)
    return expected, manifests, s3


def test_baseline_is_green():
    expected, manifests, s3 = _baseline()
    rows = B.build_ledger(expected, manifests, s3, config_hash="sha256:test")
    assert all(r.reconciled for r in rows)
    assert B.self_check_divergences(rows, expected) == []
    assert len(rows) == len(expected)  # count reconciliation: union == expected


def test_present_not_declared_manifest_without_config_reds():
    expected, manifests, s3 = _baseline()
    # a dge_deseq2 manifest (and its S3 prefix) that config intent does NOT declare
    orphan = "brca-dge-tumor-vs-normal-sensitivity-v1"
    manifests[orphan] = CatalogedProduct(
        orphan,
        "methods/dge_deseq2/steps/06_four_cell_driver.R",
        f"s3://onc-compbio/data-catalog/derived/{orphan}/sensitivity.parquet",
        "def456",
        "2026-07-06",
        "BRCA",
        "recount3",
    )
    s3.add(orphan)
    rows = B.build_ledger(expected, manifests, s3, config_hash="sha256:test")
    row = next(r for r in rows if r.catalog_id == orphan)
    assert not row.reconciled
    assert "manifest-without-config" in row.divergences
    # the previously-green rows stay green -> the red is caused by the injected manifest only
    assert all(r.reconciled for r in rows if r.catalog_id != orphan)


def test_s3_orphan_with_no_manifest_reds():
    expected, manifests, s3 = _baseline()
    s3.add("luad-dge-tumor-vs-normal-sensitivity-v1")  # dge-shaped, no manifest, not declared
    rows = B.build_ledger(expected, manifests, s3, config_hash="sha256:test")
    row = next(r for r in rows if r.catalog_id == "luad-dge-tumor-vs-normal-sensitivity-v1")
    assert not row.reconciled and "s3-orphan-not-declared" in row.divergences


def test_declared_without_manifest_reds():
    expected, manifests, s3 = _baseline()
    dropped = "coadread-dge-adj-vs-gtex-v1"
    del manifests[dropped]
    s3.discard(dropped)
    rows = B.build_ledger(expected, manifests, s3, config_hash="sha256:test")
    row = next(r for r in rows if r.catalog_id == dropped)
    assert not row.reconciled and "declared-without-manifest" in row.divergences


def test_catalogued_not_present_in_s3_reds():
    expected, manifests, s3 = _baseline()
    # manifest exists, but its S3 prefix is gone
    s3.discard("coadread-dge-adj-vs-gtex-v1")
    rows = B.build_ledger(expected, manifests, s3, config_hash="sha256:test")
    row = next(r for r in rows if r.catalog_id == "coadread-dge-adj-vs-gtex-v1")
    assert not row.reconciled and "catalogued-not-present-in-s3" in row.divergences


def test_manifest_s3_uri_stem_mismatch_reds():
    expected, manifests, s3 = _baseline()
    cid = "coadread-dge-adj-vs-gtex-v1"
    manifests[cid].s3_uri = "s3://onc-compbio/data-catalog/derived/WRONG-STEM/p.parquet"
    rows = B.build_ledger(expected, manifests, s3, config_hash="sha256:test")
    row = next(r for r in rows if r.catalog_id == cid)
    assert not row.reconciled and "manifest-s3-uri-stem-mismatch" in row.divergences


def test_substrate_mismatch_reds():
    expected, manifests, s3 = _baseline()
    cid = "coadread-dge-tumor-vs-normal-sensitivity-v1"  # declared recount3
    manifests[cid].substrate_raw = "xena-toil/tcga-target-gtex-snapshot-2026-09-20"  # normalizes to xena_toil
    rows = B.build_ledger(expected, manifests, s3, config_hash="sha256:test")
    row = next(r for r in rows if r.catalog_id == cid)
    assert not row.reconciled
    assert any(d.startswith("substrate-mismatch") for d in row.divergences)


def test_offline_skips_s3_divergences_but_keeps_config_manifest_asymmetry():
    expected, manifests, _ = _baseline()
    # a manifest missing entirely -> declared-without-manifest still fires offline (no S3 needed)
    del manifests["coadread-dge-adj-vs-gtex-v1"]
    rows = B.build_ledger(expected, manifests, s3_prefixes=None, config_hash="sha256:test")
    row = next(r for r in rows if r.catalog_id == "coadread-dge-adj-vs-gtex-v1")
    assert "declared-without-manifest" in row.divergences
    # a present manifest is NOT flagged catalogued-not-present-in-s3 when S3 is unknown
    ok = next(r for r in rows if r.catalog_id == "dge-deseq2-qc-index-v1")
    assert not any("s3" in d for d in ok.divergences)


# --------------------------------------------------------------------------- #
# vacuous-ledger guard
# --------------------------------------------------------------------------- #
def test_empty_intent_is_a_divergence():
    rows = B.build_ledger({}, {}, set(), config_hash="sha256:test")
    assert rows == []
    msgs = B.self_check_divergences(rows, expected={})
    assert any("empty intent roster" in m for m in msgs)


# --------------------------------------------------------------------------- #
# QC re-derivation — independent, per family, each failure mode
# --------------------------------------------------------------------------- #
def test_qc_zero_rows_fails():
    status, reasons = B.derive_qc_status(pd.DataFrame({"log2fc_C": []}), "tumor-vs-normal")
    assert status == "fail" and reasons == ["zero-rows"]


def test_qc_all_nan_value_column_fails():
    df = pd.DataFrame(
        {"log2fc_C": [float("nan")] * 5, "log2fc_A": [float("nan")] * 5, "max_abs_log2fc": [float("nan")] * 5}
    )
    status, reasons = B.derive_qc_status(df, "tumor-vs-normal")
    assert status == "fail" and any("entirely NaN" in r for r in reasons)


def test_qc_sign_collapse_fails_but_both_signs_passes():
    all_up = pd.DataFrame({"log2fc_C": [1.0, 2.0, 3.0], "max_abs_log2fc": [1.0, 2.0, 3.0]})
    status, reasons = B.derive_qc_status(all_up, "tumor-vs-normal")
    assert status == "fail" and any("sign sanity" in r for r in reasons)
    mixed = pd.DataFrame({"log2fc_C": [1.0, -2.0, 3.0], "max_abs_log2fc": [1.0, 2.0, 3.0]})
    assert B.derive_qc_status(mixed, "tumor-vs-normal") == ("pass", [])


def test_qc_gene_lengths_positivity():
    good = pd.DataFrame({"effective_length_bp": [100, 250, 999]})
    assert B.derive_qc_status(good, "gene-lengths") == ("pass", [])
    bad = pd.DataFrame({"effective_length_bp": [100, 0, -5]})
    status, reasons = B.derive_qc_status(bad, "gene-lengths")
    assert status == "fail" and any("positivity" in r for r in reasons)


def test_qc_index_family_needs_only_rowcount_and_nonnull():
    good = pd.DataFrame({"n_sig_fdr05": [10, 20], "n_tested": [100, 200], "median_abs_lfc_sig": [1.1, 0.9]})
    assert B.derive_qc_status(good, "qc-index") == ("pass", [])
    empty = pd.DataFrame({"n_sig_fdr05": [], "n_tested": [], "median_abs_lfc_sig": []})
    assert B.derive_qc_status(empty, "qc-index")[0] == "fail"


def test_apply_qc_never_greenlights_an_unread_product():
    rows = [
        B.LedgerRow("a", None, None, "tumor-vs-normal", None, "h", None, None, "s3://x/a.parquet", "unchecked", True),
        B.LedgerRow("b", None, None, "tumor-vs-normal", None, "h", None, None, None, "unchecked", True),
    ]

    def _boom(_uri):
        raise OSError("no creds")

    B.apply_qc(rows, _boom)
    assert rows[0].qc_status.startswith("skip:read-failed")  # read error is a skip, not a pass
    assert rows[1].qc_status == "skip:no-product-uri"


def test_apply_qc_marks_fail_and_self_check_reds_on_qc():
    rows = [
        B.LedgerRow("a", None, None, "tumor-vs-normal", None, "h", None, None, "s3://x/a.parquet", "unchecked", True)
    ]
    B.apply_qc(rows, lambda _uri: pd.DataFrame({"log2fc_C": [1.0, 2.0]}))  # all-positive -> sign fail
    assert rows[0].qc_status.startswith("fail:")
    msgs = B.self_check_divergences(rows, expected={"a": ExpectedProduct("a", None, None, "tumor-vs-normal", "x")})
    assert any(m.startswith("a: qc fail") for m in msgs)


# --------------------------------------------------------------------------- #
# scan_manifests notebook filter (hermetic tmp catalog)
# --------------------------------------------------------------------------- #
def _write_manifest(dirpath: Path, cid: str, notebook: str, **extra):
    m = {"id": cid, "notebook": notebook, "s3_uri": f"s3://onc-compbio/data-catalog/derived/{cid}/p.parquet"}
    m.update(extra)
    (dirpath / f"{cid}.yaml").write_text(yaml.safe_dump(m))


def test_scan_manifests_filters_on_dge_deseq2_notebook(tmp_path):
    d = tmp_path / "manifests" / "derived"
    d.mkdir(parents=True)
    _write_manifest(d, "coadread-dge-tumor-vs-normal-sensitivity-v1", "methods/dge_deseq2/steps/06_four_cell_driver.R")
    _write_manifest(d, "sclc-dge-tumor-vs-normal-sensitivity-v1", "methods/sclc_dge_tumor_vs_gtex/cli.py")
    _write_manifest(d, "coadread-dge-tumor-vs-gtex-v1", "methods/dge_tcga_gtex_precompute/cli.py")
    dge, all_stems = B.scan_manifests(tmp_path)
    assert set(dge) == {"coadread-dge-tumor-vs-normal-sensitivity-v1"}  # only the dge_deseq2 one
    assert "sclc-dge-tumor-vs-normal-sensitivity-v1" in all_stems  # other-method stem still tracked


def test_dge_prefixes_on_s3_excludes_other_method_but_flags_true_orphan():
    dge_ids = {"coadread-dge-tumor-vs-normal-sensitivity-v1"}
    all_stems = {"coadread-dge-tumor-vs-normal-sensitivity-v1", "sclc-dge-tumor-vs-normal-sensitivity-v1"}
    all_prefixes = {
        "coadread-dge-tumor-vs-normal-sensitivity-v1",  # ours
        "sclc-dge-tumor-vs-normal-sensitivity-v1",  # dge-shaped but another method's manifest -> skip
        "luad-dge-tumor-vs-normal-sensitivity-v1",  # dge-shaped, no manifest -> orphan
        "some-other-product-v1",  # not dge-shaped -> ignore
    }
    relevant = B.dge_prefixes_on_s3(all_prefixes, all_stems, dge_ids)
    assert relevant == {
        "coadread-dge-tumor-vs-normal-sensitivity-v1",
        "luad-dge-tumor-vs-normal-sensitivity-v1",
    }


# --------------------------------------------------------------------------- #
# live / real-clone checks (skip cleanly; run locally for green-for-right-reason)
# --------------------------------------------------------------------------- #
def _real_catalog_root() -> Path | None:
    root = Path(os.environ.get("DATA_CATALOG_ROOT") or B.DATA_CATALOG)
    return root if (root / "manifests" / "derived").is_dir() else None


def test_real_catalog_reconciles_offline_green():
    """The live catalog must reconcile to zero divergences today (config intent == authored set)."""
    root = _real_catalog_root()
    if root is None:
        pytest.skip("no data-catalog clone available (set DATA_CATALOG_ROOT)")
    rows, divergences = B.build_and_check(root, offline=True)
    assert divergences == [], divergences
    assert len(rows) == 37 and all(r.reconciled for r in rows)


@pytest.mark.skipif(
    not os.environ.get("DGE_LEDGER_LIVE_S3"),
    reason="live S3 qc re-derivation — set DGE_LEDGER_LIVE_S3=1 to run locally with creds",
)
def test_real_s3_products_pass_qc():
    root = _real_catalog_root()
    assert root is not None, "live S3 test requires the data-catalog clone"
    rows, divergences = B.build_and_check(root, offline=False)
    assert divergences == [], divergences
    assert all(r.qc_status == "pass" for r in rows), [
        (r.catalog_id, r.qc_status) for r in rows if r.qc_status != "pass"
    ]
