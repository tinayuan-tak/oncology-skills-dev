"""Pan-cancer stacked tumor-vs-normal product (Slice C-1).

derive_pancan_stack.build_stack concatenates the 27 per-indication sensitivity
parquets into one stacked frame with an `indication` column + a `cell_b_semantics`
provenance column. The load-bearing hazard: three cell-B vintages exist (one indication
skips cell B entirely, so its parquet LACKS log2fc_B/padj_B). These tests pin, with S3
stubbed (pyarrow monkeypatched to synthetic per-indication tables):
  - union-schema alignment: an indication missing cell-B cols is NaN-filled, concat OK;
  - the indication column is present + correct per source;
  - cell_b_semantics is stamped per the vintage map (skipped/design-comparison/combat);
  - one row per (indication, gene); deterministic ordering.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

d = importlib.import_module("methods.dge_deseq2.derive_pancan_stack")


def _full_cols(gene, run_b=True):
    row = {"gene_symbol": gene, "cells_ran": 3.0 if run_b else 2.0,
           "cells_supporting": 3.0 if run_b else 2.0, "dominant_direction": "up",
           "sig_all_cells": True, "discordant": False,
           "log2fc_A": 2.0, "padj_A": 1e-6, "log2fc_C": 1.8, "padj_C": 1e-5,
           "max_abs_log2fc": 2.0}
    if run_b:
        row["log2fc_B"] = 1.9
        row["padj_B"] = 1e-5
    return row


# synthetic per-indication tables: COADREAD + LUAD have cell B; UCEC does NOT (skipped)
_SYNTH = {
    "COADREAD": pd.DataFrame([_full_cols("EPCAM"), _full_cols("KRAS")]),
    "LUAD": pd.DataFrame([_full_cols("EPCAM"), _full_cols("KRAS")]),
    "UCEC": pd.DataFrame([_full_cols("EPCAM", run_b=False), _full_cols("KRAS", run_b=False)]),
}


class _FakeTable:
    def __init__(self, df): self._df = df
    def to_pandas(self): return self._df.copy()


def _patch(monkeypatch):
    class _FakePq:
        @staticmethod
        def read_table(path, filesystem=None):
            # path ends with {ind}-dge-tumor-vs-normal-sensitivity-v1/sensitivity.parquet
            for ind, df in _SYNTH.items():
                if f"{ind.lower()}-dge" in path:
                    return _FakeTable(df)
            raise FileNotFoundError(path)

    class _FakeFs:
        class S3FileSystem:  # noqa: N801
            def __init__(self, *a, **k): pass

    monkeypatch.setitem(sys.modules, "pyarrow.parquet", _FakePq)
    monkeypatch.setitem(sys.modules, "pyarrow.fs", _FakeFs)


def test_union_schema_ucec_missing_cell_b_is_nan_filled(monkeypatch):
    _patch(monkeypatch)
    stacked = d.build_stack(["COADREAD", "LUAD", "UCEC"])
    # union columns present for every indication
    assert "log2fc_B" in stacked.columns and "padj_B" in stacked.columns
    ucec = stacked[stacked.indication == "UCEC"]
    assert ucec["log2fc_B"].isna().all() and ucec["padj_B"].isna().all()
    # cells_ran reflects the skip (2, not 3)
    assert (ucec["cells_ran"] == 2.0).all()


def test_indication_column_and_row_count(monkeypatch):
    _patch(monkeypatch)
    stacked = d.build_stack(["COADREAD", "LUAD", "UCEC"])
    assert stacked["indication"].tolist().count("COADREAD") == 2
    assert set(stacked["indication"].unique()) == {"COADREAD", "LUAD", "UCEC"}
    assert len(stacked) == 6  # 3 indications x 2 genes


def test_cell_b_semantics_provenance_stamped(monkeypatch):
    _patch(monkeypatch)
    stacked = d.build_stack(["COADREAD", "LUAD", "UCEC"])
    by_ind = stacked.groupby("indication")["cell_b_semantics"].first().to_dict()
    assert by_ind["COADREAD"] == "design_comparison_unspecified"
    assert by_ind["UCEC"] == "cell_b_skipped"
    assert by_ind["LUAD"] == "combat_seq_tcga_tss"


def test_all_indications_map_has_27():
    assert len(d.all_indications()) == 27
    # every indication has a cell_b_semantics entry (no silent default gap for the known 27)
    for ind in d.all_indications():
        assert ind in d._INDICATION_CELL_B_SEMANTICS


def test_leading_columns_order(monkeypatch):
    _patch(monkeypatch)
    stacked = d.build_stack(["COADREAD"])
    # indication leads, cell_b_semantics trails — the stacked contract
    assert stacked.columns[0] == "indication"
    assert stacked.columns[-1] == "cell_b_semantics"


# --- RNA tumor-elevation breadth reader (Slice C-3) -------------------------------------------

def _stacked_row(ind, gene, direction="up", supporting=3.0, max_lfc=2.0, discordant=False,
                 cells_ran=3.0):
    return {"indication": ind, "gene_symbol": gene, "cells_ran": cells_ran,
            "cells_supporting": supporting, "dominant_direction": direction,
            "sig_all_cells": True, "discordant": discordant,
            "log2fc_A": max_lfc, "padj_A": 1e-6, "log2fc_B": max_lfc, "padj_B": 1e-6,
            "log2fc_C": max_lfc, "padj_C": 1e-6, "max_abs_log2fc": max_lfc,
            "cell_b_semantics": "combat_seq_tcga_tss"}


def _patch_reader(monkeypatch, rows):
    class _T:
        def __init__(self, rows): self._rows = rows
        @property
        def num_rows(self): return len(self._rows)
        def to_pandas(self): return pd.DataFrame(self._rows)

    class _FakePq:
        @staticmethod
        def read_table(path, filesystem=None, filters=None):
            target = filters[0][2]
            return _T([r for r in rows if r["gene_symbol"] == target])

    class _FakeFs:
        class S3FileSystem:  # noqa: N801
            def __init__(self, *a, **k): pass

    monkeypatch.setitem(sys.modules, "pyarrow.parquet", _FakePq)
    monkeypatch.setitem(sys.modules, "pyarrow.fs", _FakeFs)


def test_rna_breadth_broadly_elevated(monkeypatch):
    rows = [_stacked_row("BRCA", "EPCAM"), _stacked_row("LUAD", "EPCAM"),
            _stacked_row("COAD", "EPCAM", max_lfc=1.2),
            _stacked_row("OV", "EPCAM", direction="none", supporting=0.0)]
    _patch_reader(monkeypatch, rows)
    b = d.read_rna_tumor_elevation_breadth("EPCAM")
    assert b["rna_tumor_elevation_breadth_class"] == "broadly_tumor_elevated"
    assert b["n_indications_tested"] == 4 and b["n_indications_elevated"] == 3
    assert b["fraction_elevated"] == 0.75
    assert [x["indication"] for x in b["most_elevated_indications"]] == ["BRCA", "LUAD", "COAD"]


def test_rna_breadth_ignores_cell_b_vintage(monkeypatch):
    """The vintage-stable guarantee: a UCEC-style row with NO cell B (NaN log2fc_B) that is
    up-dominant + supported still counts as elevated — the predicate never touches cell B."""
    row = _stacked_row("UCEC", "KRAS", supporting=2.0, cells_ran=2.0)
    row["log2fc_B"] = float("nan"); row["padj_B"] = float("nan")
    row["cell_b_semantics"] = "cell_b_skipped"
    _patch_reader(monkeypatch, [row])
    b = d.read_rna_tumor_elevation_breadth("KRAS")
    assert b["rna_tumor_elevation_breadth_class"] == "single_tumor_elevated"
    assert b["n_indications_elevated"] == 1


def test_rna_breadth_discordant_not_elevated(monkeypatch):
    rows = [_stacked_row("BRCA", "TP53", discordant=True),
            _stacked_row("LUAD", "TP53", direction="down")]
    _patch_reader(monkeypatch, rows)
    b = d.read_rna_tumor_elevation_breadth("TP53")
    assert b["rna_tumor_elevation_breadth_class"] == "not_tumor_elevated"
    assert b["n_indications_elevated"] == 0
    assert b["median_max_log2fc_across_elevated"] is None


def test_rna_breadth_absent_target_data_unavailable(monkeypatch):
    _patch_reader(monkeypatch, [_stacked_row("BRCA", "EPCAM")])
    b = d.read_rna_tumor_elevation_breadth("GHOST")
    assert b["rna_tumor_elevation_breadth_class"] == "data_unavailable"
    assert b["n_indications_tested"] == 0 and b["indications_tested"] == []
