"""build_authority: schema, id normalisation, drift/reuse flags, union rule.

Re-derives the authority from raw source snippets (tests/.../_fixtures.py) so
every assertion is against freshly computed output, not a stored blob.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.gene_id_authority.build import _strip_version, build_authority  # noqa: E402

from ._fixtures import write_sources  # noqa: E402


def _authority(tmp_path):
    ens, v23 = write_sources(tmp_path)
    return build_authority(ens, v23).set_index("gene_id")


def test_strip_version_idempotent():
    assert _strip_version("ENSG00000133703.13") == "ENSG00000133703"
    assert _strip_version("ENSG00000133703") == "ENSG00000133703"


def test_schema_columns(tmp_path):
    ens, v23 = write_sources(tmp_path)
    df = build_authority(ens, v23)
    assert list(df.columns) == [
        "gene_id",
        "symbol_hgnc",
        "hgnc_id",
        "gene_name_ensembl",
        "symbol_gencode_v23",
        "symbol_canonical",
        "in_ensembl116",
        "in_gencode_v23",
        "symbol_drift",
        "symbol_reuse_conflict",
    ]
    # gene_id is the unversioned key and unique.
    assert df["gene_id"].is_unique
    assert (df["gene_id"] == df["gene_id"].str.replace(r"\..*$", "", regex=True)).all()


def test_symbol_canonical_never_null(tmp_path):
    """The join-relevant restriction guarantees every row carries a symbol."""
    a = _authority(tmp_path)
    assert a["symbol_canonical"].notna().all()


def test_symbolless_ens116_gene_is_dropped(tmp_path):
    """ENSG00000333333 has null HGNC and is absent from v23 → inert → dropped."""
    a = _authority(tmp_path)
    assert "ENSG00000333333" not in a.index


def test_clean_gene_no_drift_no_reuse(tmp_path):
    a = _authority(tmp_path)
    kras = a.loc["ENSG00000133703"]
    assert kras["symbol_hgnc"] == "KRAS"
    assert kras["symbol_gencode_v23"] == "KRAS"
    assert kras["symbol_canonical"] == "KRAS"
    assert bool(kras["in_ensembl116"]) and bool(kras["in_gencode_v23"])
    assert not bool(kras["symbol_drift"])
    assert not bool(kras["symbol_reuse_conflict"])


def test_symbol_drift_detected_and_hgnc_canonical(tmp_path):
    a = _authority(tmp_path)
    g = a.loc["ENSG00000000460"]
    assert g["symbol_gencode_v23"] == "C1orf112"
    assert g["symbol_hgnc"] == "FIRRM"
    assert bool(g["symbol_drift"])  # same gene, different symbol per release
    assert g["symbol_canonical"] == "FIRRM"  # HGNC (v116) wins


def test_symbol_reuse_detected_both_genes(tmp_path):
    """'MEG8' is v23's name for ENSG...258399 but v116's name for ENSG...225746.
    A symbol-string join would fuse them; both must be flagged."""
    a = _authority(tmp_path)
    assert bool(a.loc["ENSG00000258399"]["symbol_reuse_conflict"])
    assert bool(a.loc["ENSG00000225746"]["symbol_reuse_conflict"])
    # And they are DISTINCT authority rows — the id join keeps them separate.
    assert a.loc["ENSG00000258399"]["symbol_canonical"] == "MEG8"
    assert a.loc["ENSG00000225746"]["symbol_canonical"] == "MEG8"


def test_source_presence_flags(tmp_path):
    a = _authority(tmp_path)
    assert not bool(a.loc["ENSG00000111111"]["in_ensembl116"])  # v23-only
    assert bool(a.loc["ENSG00000111111"]["in_gencode_v23"])
    assert bool(a.loc["ENSG00000222222"]["in_ensembl116"])  # ens116-only
    assert not bool(a.loc["ENSG00000222222"]["in_gencode_v23"])
    assert a.loc["ENSG00000222222"]["symbol_canonical"] == "BARONLY"
