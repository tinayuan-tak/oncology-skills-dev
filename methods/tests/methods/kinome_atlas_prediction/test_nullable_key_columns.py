"""kinome_atlas_prediction: a null cell in a KEY column must skip its own row, not blow up the atlas.

derive.py writes kinase_symbol and substrate_gene through `astype("string")`, and parquet round-trips
that dtype — pyarrow stores it in the file metadata and restores the extension dtype on read — so a
null cell reaches the reader as `pd.NA`, not as None and not as float nan.

`pd.NA` is the one null shape on which a plain truthiness guard does not answer False. It RAISES
`TypeError: boolean value of NA is ambiguous`. The index builder's guard was `if not k or not s`, and
_load_atlas_indexed is called inside read_target_summary's own `except Exception`, which converts any
failure into `_data_note = "atlas_load_failed: ..."`. So the blast radius of one null kinase_symbol was
not one row — it was EVERY target, because the index build is shared, and it repeated on every call
because @lru_cache does not cache exceptions (each retry re-streams the whole 2.9M-row parquet).

Inert on the shipped product at the time of writing — 0 nulls across all 9 columns / 2,872,829 rows,
read from the parquet footer statistics — and only substrate_gene is notna-filtered upstream
(derive.py:195). kinase_symbol is not. So this is inert BY CORPUS, not by contract, which is exactly
the class of thing that changes silently when the product is re-derived.

The fix is one vectorized `to_numpy(dtype=object, na_value=None)` per key column, which normalises
pd.NA / None / float nan to a single falsy None before the loop. These tests are also the guard on the
SPEED half of that change (reverting to `.values` reintroduces a 6.4x slowdown on pandas 3 alongside
the crash), because a revert cannot pass them.
"""

from __future__ import annotations

import pandas as pd
import pytest

from onc_methods.kinome_atlas_prediction import read as kin


def _atlas_frame(kinase_symbols, substrate_genes):
    """A frame with the derived product's REAL schema and dtypes (derive.py:179-191).

    The dtypes are the point: `astype("string")` is what makes a null cell pd.NA rather than None,
    so building this frame with plain object columns would produce a fixture that CANNOT express the
    failure — it would pass against the unfixed code.
    """
    n = len(kinase_symbols)
    return pd.DataFrame(
        {
            "kinase_symbol": pd.Series(kinase_symbols, dtype="string"),
            "substrate_gene": pd.Series(substrate_genes, dtype="string"),
            "substrate_ac": pd.Series(["P31749"] * n, dtype="string"),
            "phosphosite": pd.Series(["S256"] * n, dtype="string"),
            "phos_res": pd.Series(["S"] * n, dtype="string"),
            "motif_15mer": pd.Series(["RPRAATFAEQRRLSR"] * n, dtype="string"),
            "kinome": "ser_thr",
            "percentile": [99.0 - i for i in range(n)],
            "rank": pd.Series(range(1, n + 1), dtype="Int64"),
        }
    )


@pytest.fixture
def atlas(monkeypatch):
    """Feed the reader a frame instead of S3, the way test_load_atlas_absence.py does.

    INSTALLS ONLY — it deliberately does not call _load_atlas_indexed itself. Loading inside the
    fixture would make every test that exercises a null die during SETUP with a bare TypeError, so a
    regression would report "error in fixture" instead of the behaviour that broke. Each test triggers
    the load at the point it wants to make a claim about.
    """

    def _install(df):
        kin._load_atlas_indexed.cache_clear()
        monkeypatch.setattr(kin, "_get_s3fs", lambda: None)
        monkeypatch.setattr(pd, "read_parquet", lambda *a, **k: df)

    yield _install
    kin._load_atlas_indexed.cache_clear()


def test_the_fixture_can_actually_express_the_failure_pd_NA_not_None():
    """Control. If `astype("string")` ever stops producing pd.NA, every test below goes vacuous.

    Asserts the two halves of the mechanism directly: the raw cell RAISES under truthiness, and the
    conversion the fix uses turns it into a falsy None.
    """
    col = _atlas_frame(["AKT1", None], ["FOXO1", "TP53"])["kinase_symbol"]
    raw = col.values[1]
    assert type(raw).__name__ == "NAType", f"fixture no longer produces pd.NA, got {type(raw).__name__}"
    with pytest.raises(TypeError, match="ambiguous"):
        bool(not raw)

    converted = col.to_numpy(dtype=object, na_value=None)
    assert converted[1] is None
    assert not converted[1]  # falsy, so the existing `not k` guard is correct rather than fatal
    assert converted[0] == "AKT1"  # and present values are untouched


def test_a_null_kinase_symbol_skips_its_own_row_and_nothing_else(atlas):
    """The core regression: one pd.NA must not take the index build down with it."""
    atlas(_atlas_frame(["AKT1", None, "SRC"], ["FOXO1", "TP53", "MYC"]))
    df, kinase_index, substrate_index = kin._load_atlas_indexed()

    assert set(kinase_index) == {"AKT1", "SRC"}, "the null row must be skipped, and only it"
    # Row 1's SUBSTRATE is present and non-null, but its row is unusable as an edge (no kinase), so
    # it must not appear in the substrate index either — the guard is `not k OR not s`.
    assert set(substrate_index) == {"FOXO1", "MYC"}
    assert len(df) == 3, "the frame itself is returned unfiltered; only the INDEX skips the row"


def test_the_indices_stay_POSITIONAL_into_the_returned_frame(atlas):
    """Why the fix skips rather than filters.

    read_target_summary materializes edges with `df.iloc[indices]`, so an index entry is a POSITIONAL
    offset into the frame that _load_atlas_indexed returns. A fix that dropped the null rows from the
    frame instead of skipping them in the loop would shift every later row's position and silently
    mis-attribute edges — a far worse failure than the crash, because it is green.
    """
    atlas(_atlas_frame(["AKT1", None, "SRC"], ["FOXO1", "TP53", "MYC"]))
    df, kinase_index, _ = kin._load_atlas_indexed()

    (src_pos,) = kinase_index["SRC"]
    assert src_pos == 2, "SRC is the third row; skipping the null must not renumber it"
    assert df.iloc[src_pos]["kinase_symbol"] == "SRC"
    assert df.iloc[src_pos]["substrate_gene"] == "MYC"


def test_a_null_key_does_not_return_atlas_load_failed_for_an_UNRELATED_target(atlas):
    """The consequence, named. This is the test that fails loudly on the real defect.

    The crash surfaced as `_data_note = "atlas_load_failed: TypeError: boolean value of NA is
    ambiguous"` on every read_target_summary call, for every target — a whole-atlas blackout dressed
    as honest data absence, which is the disguise that makes it hard to notice.
    """
    atlas(_atlas_frame(["AKT1", None, "SRC"], ["FOXO1", "TP53", "MYC"]))
    result = kin.read_target_summary("AKT1")

    note = result.get("_data_note") or ""
    assert "atlas_load_failed" not in note, f"whole-atlas blackout from one null cell: {note!r}"
    assert result["n_downstream_effectors"] == 1, "AKT1's own edge must still be readable"
    assert result["downstream_effectors"][0]["partner_gene_symbol"] == "FOXO1"


def test_an_empty_string_key_is_still_skipped(atlas):
    """Behaviour preservation. `na_value=None` changes what happens to NULLS; the `not k` guard's
    other job — dropping empty-string keys — must be untouched, or the fix would quietly widen what
    lands in the index."""
    atlas(_atlas_frame(["AKT1", ""], ["FOXO1", "TP53"]))
    _, kinase_index, substrate_index = kin._load_atlas_indexed()

    assert set(kinase_index) == {"AKT1"}
    assert set(substrate_index) == {"FOXO1"}


def test_a_null_SUBSTRATE_gene_is_skipped_too(atlas):
    """substrate_gene is notna-filtered in derive.py, so this shape should not exist in the product —
    but the reader must not depend on a writer's filter for its own safety, and the filter only ran
    for the vintages that were derived with it."""
    atlas(_atlas_frame(["AKT1", "SRC"], ["FOXO1", None]))
    _, kinase_index, substrate_index = kin._load_atlas_indexed()

    assert set(kinase_index) == {"AKT1"}
    assert set(substrate_index) == {"FOXO1"}
