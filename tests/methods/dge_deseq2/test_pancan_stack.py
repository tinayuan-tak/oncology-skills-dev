"""Pan-cancer stacked tumor-vs-normal product (Slice C-1).

derive_pancan_stack.build_stack concatenates the 27 per-indication sensitivity
parquets into one stacked frame with a leading `indication` column. The ComBat cell B
(log2fc_B/padj_B) was removed in analysis-methods#727; the stacked schema no longer carries
those columns nor the old `cell_b_semantics` provenance column. These tests pin, with S3
stubbed (pyarrow monkeypatched to synthetic per-indication tables):
  - union-schema alignment: an indication missing a `_UNION_COLUMNS` entry (e.g. cell C
    skipped) is NaN-filled, and a LEGACY product that still carries log2fc_B/padj_B has those
    dropped by the projection (the stack was NOT rebuilt by #727, so old inputs may hold B);
  - the indication column is present + correct per source;
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


@pytest.fixture(autouse=True)
def _clear_breadth_cache():
    """read_rna_tumor_elevation_breadth is @lru_cache'd (retrieval-opt #4). Clear it before each test
    so a target queried by a prior test with different synthetic data can't return a stale result."""
    d.read_rna_tumor_elevation_breadth.cache_clear()
    yield
    d.read_rna_tumor_elevation_breadth.cache_clear()


def _ac_cols(gene, cells=2.0):
    """A new-vintage (post-#727) per-indication row: cells A/C only, no cell B."""
    return {
        "gene_symbol": gene,
        "cells_ran": cells,
        "cells_supporting": cells,
        "dominant_direction": "up",
        "sig_all_cells": True,
        "discordant": False,
        "log2fc_A": 2.0,
        "padj_A": 1e-6,
        "log2fc_C": 1.8,
        "padj_C": 1e-5,
        "max_abs_log2fc": 2.0,
    }


def _legacy_b_cols(gene):
    """A LEGACY (pre-#727) product row that still carries log2fc_B/padj_B — build_stack must
    DROP these (they are not in _UNION_COLUMNS) rather than propagate them into the stack."""
    row = _ac_cols(gene, cells=3.0)
    row["log2fc_B"] = 1.9
    row["padj_B"] = 1e-5
    return row


def _missing_c_cols(gene):
    """A product where cell C was skipped: no log2fc_C/padj_C columns → union NaN-fill."""
    row = _ac_cols(gene, cells=1.0)
    del row["log2fc_C"]
    del row["padj_C"]
    return row


# synthetic per-indication tables: COADREAD is a legacy product still carrying cell B (must be
# dropped); LUAD is a new A/C product; UCEC skipped cell C (missing log2fc_C → NaN-filled).
_SYNTH = {
    "COADREAD": pd.DataFrame([_legacy_b_cols("EPCAM"), _legacy_b_cols("KRAS")]),
    "LUAD": pd.DataFrame([_ac_cols("EPCAM"), _ac_cols("KRAS")]),
    "UCEC": pd.DataFrame([_missing_c_cols("EPCAM"), _missing_c_cols("KRAS")]),
}


class _FakeTable:
    def __init__(self, df):
        self._df = df

    def to_pandas(self):
        return self._df.copy()


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
            def __init__(self, *a, **k):
                pass

    # Patch the real module ATTRIBUTES, not sys.modules. The reader does `import pyarrow.parquet
    # as pq`, and `import a.b as c` binds via getattr(a, "b") once the submodule is imported — so a
    # sys.modules[...] = fake swap is silently bypassed whenever ANOTHER test imported pyarrow.parquet
    # first (order-dependent: green locally, red in CI). setattr on the real modules intercepts every time.
    import pyarrow.fs as _fs
    import pyarrow.parquet as _pq

    monkeypatch.setattr(_pq, "read_table", _FakePq.read_table)
    monkeypatch.setattr(_fs, "S3FileSystem", _FakeFs.S3FileSystem)


def test_union_schema_drops_legacy_b_and_nanfills_missing(monkeypatch):
    _patch(monkeypatch)
    stacked = d.build_stack(["COADREAD", "LUAD", "UCEC"])
    # cell B columns are NEVER in the stacked schema, even though COADREAD's product carried them.
    assert "log2fc_B" not in stacked.columns and "padj_B" not in stacked.columns
    # UCEC skipped cell C → its log2fc_C/padj_C are union NaN-filled.
    ucec = stacked[stacked.indication == "UCEC"]
    assert ucec["log2fc_C"].isna().all() and ucec["padj_C"].isna().all()
    assert (ucec["cells_ran"] == 1.0).all()
    # the stacked schema is exactly indication + _UNION_COLUMNS.
    assert list(stacked.columns) == ["indication", *d._UNION_COLUMNS]


def test_indication_column_and_row_count(monkeypatch):
    _patch(monkeypatch)
    stacked = d.build_stack(["COADREAD", "LUAD", "UCEC"])
    assert stacked["indication"].tolist().count("COADREAD") == 2
    assert set(stacked["indication"].unique()) == {"COADREAD", "LUAD", "UCEC"}
    assert len(stacked) == 6  # 3 indications x 2 genes


def test_all_indications_roster_has_28():
    assert len(d.all_indications()) == 28  # +LAML (#734 Phase 2)
    # every stack-build indication is in the declared published roster (no silent gap).
    for ind in d.all_indications():
        assert ind in d._PUBLISHED_INDICATIONS


def test_leading_and_trailing_columns(monkeypatch):
    _patch(monkeypatch)
    stacked = d.build_stack(["COADREAD"])
    # indication leads; max_abs_log2fc trails (last of _UNION_COLUMNS) — the stacked contract.
    assert stacked.columns[0] == "indication"
    assert stacked.columns[-1] == "max_abs_log2fc"


# --- RNA tumor-elevation breadth reader (Slice C-3) -------------------------------------------


def _stacked_row(ind, gene, direction="up", supporting=2.0, max_lfc=2.0, discordant=False, cells_ran=2.0):
    """A stacked row in the post-#727 schema (no cell B, no cell_b_semantics)."""
    return {
        "indication": ind,
        "gene_symbol": gene,
        "cells_ran": cells_ran,
        "cells_supporting": supporting,
        "dominant_direction": direction,
        "sig_all_cells": True,
        "discordant": discordant,
        "log2fc_A": max_lfc,
        "padj_A": 1e-6,
        "log2fc_C": max_lfc,
        "padj_C": 1e-6,
        "max_abs_log2fc": max_lfc,
    }


def _patch_reader(monkeypatch, rows):
    class _T:
        def __init__(self, rows):
            self._rows = rows

        @property
        def num_rows(self):
            return len(self._rows)

        def to_pandas(self):
            return pd.DataFrame(self._rows)

    class _FakePq:
        @staticmethod
        def read_table(path, filesystem=None, filters=None):
            target = filters[0][2]
            return _T([r for r in rows if r["gene_symbol"] == target])

    class _FakeFs:
        class S3FileSystem:  # noqa: N801
            def __init__(self, *a, **k):
                pass

    # Patch the real module ATTRIBUTES, not sys.modules. The reader does `import pyarrow.parquet
    # as pq`, and `import a.b as c` binds via getattr(a, "b") once the submodule is imported — so a
    # sys.modules[...] = fake swap is silently bypassed whenever ANOTHER test imported pyarrow.parquet
    # first (order-dependent: green locally, red in CI). setattr on the real modules intercepts every time.
    import pyarrow.fs as _fs
    import pyarrow.parquet as _pq

    monkeypatch.setattr(_pq, "read_table", _FakePq.read_table)
    monkeypatch.setattr(_fs, "S3FileSystem", _FakeFs.S3FileSystem)


def test_rna_breadth_broadly_elevated(monkeypatch):
    rows = [
        _stacked_row("BRCA", "EPCAM"),
        _stacked_row("LUAD", "EPCAM"),
        _stacked_row("COAD", "EPCAM", max_lfc=1.2),
        _stacked_row("OV", "EPCAM", direction="none", supporting=0.0),
    ]
    _patch_reader(monkeypatch, rows)
    b = d.read_rna_tumor_elevation_breadth("EPCAM")
    assert b["rna_tumor_elevation_breadth_class"] == "broadly_tumor_elevated"
    assert b["n_indications_tested"] == 4 and b["n_indications_elevated"] == 3
    assert b["fraction_elevated"] == 0.75
    assert [x["indication"] for x in b["most_elevated_indications"]] == ["BRCA", "LUAD", "COAD"]


def test_rna_breadth_tolerates_legacy_cell_b_columns(monkeypatch):
    """The reader reads the MATERIALIZED product, which #727 did NOT rebuild — a row can still
    carry stray log2fc_B/padj_B. The predicate ignores them entirely; an up-dominant + supported
    row still counts as elevated off cells A/C."""
    row = _stacked_row("UCEC", "KRAS", supporting=2.0, cells_ran=2.0)
    row["log2fc_B"] = 3.3  # leftover from an old product; must be ignored
    row["padj_B"] = 1e-9
    _patch_reader(monkeypatch, [row])
    b = d.read_rna_tumor_elevation_breadth("KRAS")
    assert b["rna_tumor_elevation_breadth_class"] == "single_tumor_elevated"
    assert b["n_indications_elevated"] == 1


def test_rna_breadth_discordant_not_elevated(monkeypatch):
    rows = [_stacked_row("BRCA", "TP53", discordant=True), _stacked_row("LUAD", "TP53", direction="down")]
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


# --- M2 FIX: breadth magnitude gates on cells A/C ONLY, never a legacy cell-B-inflated max_abs_log2fc ---


def _ac_split_row(ind, gene, a, c, b, *, supporting=2.0, cells_ran=2.0):
    """A stacked row from a LEGACY product with independent A/B/C log2fc, and max_abs_log2fc set the
    way the old R producer built it: max(|A|,|B|,|C|) over ALL ran cells (INCLUDING cell B). Lets a
    test drive the case where a leftover cell B inflates max_abs_log2fc above the bar while A/C are
    below it — the reader must still gate on A/C only."""
    return {
        "indication": ind,
        "gene_symbol": gene,
        "cells_ran": cells_ran,
        "cells_supporting": supporting,
        "dominant_direction": "up",
        "sig_all_cells": True,
        "discordant": False,
        "log2fc_A": a,
        "padj_A": 1e-6,
        "log2fc_B": b,
        "padj_B": 1e-6,
        "log2fc_C": c,
        "padj_C": 1e-6,
        "max_abs_log2fc": max(abs(a), abs(b), abs(c)),
    }


def test_ac_max_log2fc_ignores_cell_b():
    # cell B huge, cells A/C small -> A/C magnitude reflects A/C only (the GAPDH ComBat pattern)
    row = _ac_split_row("ESCA", "PPIA", a=0.79, c=0.47, b=4.66)
    assert d._rna_ac_max_log2fc(row) == 0.79
    # NaN cell B contributes nothing; absent cells -> 0.0
    row_nan_b = _ac_split_row("UCEC", "X", a=1.2, c=0.3, b=float("nan"))
    assert d._rna_ac_max_log2fc(row_nan_b) == 1.2
    assert d._rna_ac_max_log2fc({"gene_symbol": "Y"}) == 0.0


def test_rna_breadth_gene_elevated_only_via_cell_b_is_not_counted(monkeypatch):
    """REGRESSION (M2): on a LEGACY product, a passenger elevated ONLY through an inflated ComBat
    cell B (A/C both < 1.0, B >> 1.0) must NOT count toward breadth. Pre-fix it did (max_abs_log2fc
    read cell B); post-fix the A/C-only magnitude gate drops it. Three such indications flip
    broadly -> not-elevated here."""
    rows = [
        _ac_split_row("ESCA", "PPIA", a=0.79, c=0.47, b=4.66),  # A/C < 1.0, B inflated
        _ac_split_row("KIRC", "PPIA", a=0.40, c=0.16, b=1.07),
        _ac_split_row("PRAD", "PPIA", a=0.53, c=0.81, b=1.09),
    ]
    _patch_reader(monkeypatch, rows)
    b = d.read_rna_tumor_elevation_breadth("PPIA")
    assert b["n_indications_tested"] == 3
    assert b["n_indications_elevated"] == 0
    assert b["rna_tumor_elevation_breadth_class"] == "not_tumor_elevated"


def test_rna_breadth_ac_elevated_gene_still_counted(monkeypatch):
    """A gene genuinely elevated on cells A and/or C (>= 1.0) stays counted — the fix only strips
    cell-B-only elevation, it must not introduce false-negatives on real A/C-elevated antigens."""
    rows = [
        _ac_split_row("BRCA", "EPCAM", a=2.4, c=2.1, b=0.1),  # strong on A/C, B flat
        _ac_split_row("LUAD", "EPCAM", a=0.2, c=1.6, b=0.3),  # C carries it
        _ac_split_row("OV", "EPCAM", a=1.3, c=0.4, b=0.0),
    ]  # A carries it
    _patch_reader(monkeypatch, rows)
    b = d.read_rna_tumor_elevation_breadth("EPCAM")
    assert b["n_indications_elevated"] == 3
    assert b["rna_tumor_elevation_breadth_class"] == "broadly_tumor_elevated"


# --- sweep2 Fix 4: roster drift-guard vs published sensitivity products ----------------------
# The stack roster is a static 27-key set. If a NEW sensitivity product lands on S3 but nobody
# adds it to config/indications.yaml (published: true), build_stack silently omits it and the
# breadth reader keeps reporting n_indications_tested over the stale 27 (under-counting
# fraction_elevated). The build must fail loud on drift instead.


class _FakeInfo:
    def __init__(self, base_name):
        self.base_name = base_name


def _fake_s3fs(dir_names):
    class _FS:
        def get_file_info(self, selector):
            return [_FakeInfo(n) for n in dir_names]

    return _FS()


def test_list_published_extracts_sensitivity_indications():
    fs = _fake_s3fs(
        [
            "coadread-dge-tumor-vs-normal-sensitivity-v1",
            "luad-dge-tumor-vs-normal-sensitivity-v1",
            "some-other-derived-product-v1",  # ignored (wrong suffix)
            "kinome-atlas-long-edges-v1",  # ignored
        ]
    )
    inds = d.list_published_sensitivity_indications(s3fs=fs)
    assert inds == {"COADREAD", "LUAD"}


def test_roster_matches_published_no_drift_passes():
    # published set exactly equals the declared 27-key roster → no raise
    published = set(d._PUBLISHED_INDICATIONS)
    d.assert_roster_matches_published(published=published)


def test_roster_drift_published_but_undeclared_raises():
    published = set(d._PUBLISHED_INDICATIONS) | {"NEWIND"}
    with pytest.raises(RuntimeError) as exc:
        d.assert_roster_matches_published(published=published)
    assert "NEWIND" in str(exc.value)
    assert "published-but-undeclared" in str(exc.value)


def test_roster_drift_declared_but_unpublished_raises():
    published = set(d._PUBLISHED_INDICATIONS) - {"UCEC"}
    with pytest.raises(RuntimeError) as exc:
        d.assert_roster_matches_published(published=published)
    assert "UCEC" in str(exc.value)
    assert "declared-but-unpublished" in str(exc.value)


def test_build_stack_with_explicit_subset_skips_drift_check(monkeypatch):
    """An explicit indications=[...] subset build is a deliberate partial/test build — it must NOT
    trigger the S3-listing drift check (only the full-roster build does)."""
    _patch(monkeypatch)
    called = {"n": 0}
    monkeypatch.setattr(d, "assert_roster_matches_published", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    d.build_stack(["COADREAD", "LUAD"])
    assert called["n"] == 0
