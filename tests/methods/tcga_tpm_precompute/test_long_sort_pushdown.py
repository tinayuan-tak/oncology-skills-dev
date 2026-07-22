"""Regression: the long-form re-encode must sort the MELTED frame by ensembl_gene_id so per-gene
predicate-pushdown actually prunes row-groups.

Bug (chain review #3): rewrite_long sorted the WIDE frame then melted per 512-gene batch, but
pandas.melt emits SAMPLE-major rows, so within a batch every row-group spanned the whole 512-gene
range. A per-gene `ensembl_gene_id == X` filter could not prune below the batch → ~500x read
amplification (measured 7-132s/gene on the live products). The fix re-sorts the MELTED frame.

This test reproduces the melt+write step on a synthetic wide frame and asserts that each row-group's
ensembl_gene_id [min,max] span is NARROW (a single-gene filter touches few row-groups), which fails
on the pre-fix (unsorted-melt) path and passes after.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")
pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _wide(n_genes: int, n_samples: int) -> pd.DataFrame:
    genes = [f"ENSG{i:011d}" for i in range(n_genes)]
    w = pd.DataFrame({"gene_symbol": [f"G{i}" for i in range(n_genes)],
                      "ensembl_gene_id": genes})
    for s in range(n_samples):
        w[f"sample{s}"] = np.random.RandomState(s).rand(n_genes).astype("float32")
    return w


def _melt_write(wide: pd.DataFrame, out: Path, row_group_size: int, sort_melted: bool):
    key = ["gene_symbol", "ensembl_gene_id"]
    samp = [c for c in wide.columns if c.startswith("sample")]
    wide = wide.sort_values("ensembl_gene_id").reset_index(drop=True)
    melted = wide.melt(id_vars=key, value_vars=samp, var_name="sample_id", value_name="log2_tpm")
    if sort_melted:  # THE FIX
        melted = melted.sort_values("ensembl_gene_id", kind="stable").reset_index(drop=True)
    pq.write_table(pa.Table.from_pandas(melted, preserve_index=False),
                   str(out), row_group_size=row_group_size)


def _rowgroup_spans(path: Path):
    pf = pq.ParquetFile(str(path))
    ci = pf.schema_arrow.names.index("ensembl_gene_id")
    return [(pf.metadata.row_group(rg).column(ci).statistics.min,
             pf.metadata.row_group(rg).column(ci).statistics.max)
            for rg in range(pf.num_row_groups)]


def test_melted_sort_yields_narrow_rowgroup_gene_spans():
    """After sorting the MELTED frame, each row-group covers a narrow contiguous gene span, so a
    per-gene filter prunes to few row-groups."""
    wide = _wide(n_genes=50, n_samples=40)  # 2000 rows
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "long.parquet"
        _melt_write(wide, out, row_group_size=40, sort_melted=True)
        spans = _rowgroup_spans(out)
        # every row-group spans at most 1 gene (40 rows/rg == 40 samples of one gene)
        assert all(mn == mx for mn, mx in spans), \
            f"row-groups should each hold ~1 gene after melted-sort; got spans {spans[:5]}"


def test_unsorted_melt_is_the_bug_being_fixed():
    """Guard the CONTRAST: without the melted-sort, every row-group spans the full gene range —
    the exact defect. If this ever stops holding, the fix's premise changed."""
    wide = _wide(n_genes=50, n_samples=40)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "long_bug.parquet"
        _melt_write(wide, out, row_group_size=40, sort_melted=False)
        spans = _rowgroup_spans(out)
        wide_spans = [mn != mx for mn, mx in spans]
        assert all(wide_spans), "pre-fix path should span many genes per row-group (the bug)"
