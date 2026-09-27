"""Hermetic unit tests for the GATE-A re-key driver's pure helpers.

The heavy end-to-end path (DESeq2 arms + full-universe snapshot) is exercised by
running the driver against live scratch; these tests pin the verdict-neutral
relabel-bridge logic that decides which stem-keyed rows become symbol-readable
and which stay stem-labelled (attributed to the ensg_ambiguous pick-policy).
"""

from __future__ import annotations

import pandas as pd
import pyarrow.parquet as pq

from methods.dge_deseq2 import rekey_gatea_run as drv


def test_manifest_id_for():
    assert drv.manifest_id_for("ACC") == "acc-dge-tumor-vs-normal-sensitivity-v1"
    assert drv.manifest_id_for("COADREAD") == "coadread-dge-tumor-vs-normal-sensitivity-v1"


def test_arms_spec_is_the_three_arm_decomposition():
    labels = [a[0] for a in drv.ARMS]
    assert labels == ["C0", "C1", "C2"]
    # C0 = shipped symbol collapse; C1 = identity (has_symbol); C2 = universe (all)
    assert drv.ARM_BY_LABEL["C0"][1:3] == ("gene_symbol", "all")
    assert drv.ARM_BY_LABEL["C1"][1:3] == ("gene_stem", "has_symbol")
    assert drv.ARM_BY_LABEL["C2"][1:3] == ("gene_stem", "all")
    # C0/C2 reuse the #844 scratch dir names; C1 gets its own so all three coexist.
    keys = {a[0]: a[3] for a in drv.ARMS}
    assert keys == {"C0": "gene_symbol", "C1": "gene_stem__has_symbol", "C2": "gene_stem"}
    assert len({a[3] for a in drv.ARMS}) == 3  # distinct scratch dirs


def _toy_authority() -> pd.DataFrame:
    # SYM1 backed by ONE stem (clean 1:1); SYM2 backed by TWO stems (ambiguous);
    # a symbol-less stem (symbol_hgnc NaN) must be excluded from the map.
    return pd.DataFrame(
        {
            "gene_id": ["ENSG00000000001", "ENSG00000000002", "ENSG00000000003", "ENSG00000000004"],
            "symbol_hgnc": ["SYM1", "SYM2", "SYM2", None],
        }
    )


def test_build_stem_maps_identifies_ambiguous_and_drops_symbolless():
    stem_to_symbol, ambiguous = drv.build_stem_maps(_toy_authority())
    assert stem_to_symbol["ENSG00000000001"] == "SYM1"
    assert stem_to_symbol["ENSG00000000002"] == "SYM2"
    assert "ENSG00000000004" not in stem_to_symbol  # symbol-less excluded
    assert ambiguous == {"SYM2"}  # backed by >1 stem
    assert "SYM1" not in ambiguous


def test_relabel_stem_product_bridges_clean_and_keeps_ambiguous_stemlabelled(tmp_path):
    stem_to_symbol, ambiguous = drv.build_stem_maps(_toy_authority())
    # A stem-keyed sensitivity product: gene_symbol column holds STEMS.
    stem_prod = tmp_path / "sensitivity.parquet"
    pd.DataFrame(
        {
            "gene_symbol": [
                "ENSG00000000001",  # clean 1:1 -> relabel to SYM1
                "ENSG00000000002",  # ambiguous -> keep stem
                "ENSG00000000004",  # symbol-less -> keep stem
                "ENSG00000000999",  # not in authority -> keep stem
            ],
            "log2fc_C": [1.0, 2.0, 3.0, 4.0],
            "padj_C": [0.01, 0.02, 0.03, 0.04],
        }
    ).to_parquet(stem_prod, index=False)

    out = drv.relabel_stem_product(stem_prod, stem_to_symbol, ambiguous)
    got = pq.read_table(str(out)).to_pandas()

    assert list(got["gene_symbol"]) == [
        "SYM1",  # bridged
        "ENSG00000000002",  # ambiguous stays stem (no pick) -> reads data_unavailable
        "ENSG00000000004",  # symbol-less stays stem
        "ENSG00000000999",  # unknown stays stem
    ]
    # gene_stem column preserves the original stem for every row.
    assert list(got["gene_stem"]) == [
        "ENSG00000000001",
        "ENSG00000000002",
        "ENSG00000000004",
        "ENSG00000000999",
    ]
    # Verdict-neutral: numeric columns are byte-untouched.
    assert list(got["log2fc_C"]) == [1.0, 2.0, 3.0, 4.0]
    assert list(got["padj_C"]) == [0.01, 0.02, 0.03, 0.04]
