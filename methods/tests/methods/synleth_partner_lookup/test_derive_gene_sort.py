"""sweep2 Fix 7: synleth_partner_lookup.derive writes the per-gene product sorted by gene_symbol.

read.py does a gene_symbol point-lookup, so the product should be gene-sorted to let pyarrow
predicate-pushdown prune to ~1 row-group per gene. It was written in dict-insertion order (unsorted).
This test builds the product from a synthetic SynLethDB TSV and asserts the on-disk gene_symbol
column is sorted ascending.
"""

from __future__ import annotations

import importlib

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")


derive = importlib.import_module("onc_methods.synleth_partner_lookup.derive")

_TSV_HEADER = "x:START_ID\tx_name\ty:END_ID\ty_name\trel_source\tcell_line\tpubmed_id\tcancer"


def _write_tsv(tmp_path):
    # Edges chosen so gene dict-insertion order is NON-alphabetical (ZZZ, AAA, MMM, BBB).
    rows = [
        "100\tZZZ\t200\tAAA\tCRISPR/CRISPRi\tHeLa\t111\tCRC",
        "300\tMMM\t400\tBBB\tComputational Prediction\t\t\tLUAD",
    ]
    p = tmp_path / "Human.SL.detailed.tsv"
    p.write_text(_TSV_HEADER + "\n" + "\n".join(rows) + "\n")
    return p


def test_product_written_gene_symbol_sorted(tmp_path):
    tsv = _write_tsv(tmp_path)
    out = tmp_path / "synlethdb_sl_partners_per_gene.parquet"
    out_df = derive.build_and_write(tsv_path=tsv, out_path=out)

    # returned frame is sorted
    genes_ret = out_df["gene_symbol"].tolist()
    assert genes_ret == sorted(genes_ret), f"returned frame not gene-sorted: {genes_ret}"

    # on-disk parquet is sorted (the load-bearing property for pushdown)
    genes_disk = pd.read_parquet(out)["gene_symbol"].tolist()
    assert genes_disk == sorted(genes_disk), f"on-disk not gene-sorted: {genes_disk}"
    assert set(genes_disk) == {"AAA", "BBB", "MMM", "ZZZ"}
