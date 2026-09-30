"""Resolve substrate-native Ensembl IDs onto the gene-ID authority and join two
substrates on the stable identity instead of the symbol string.

This is the capability the S3c cross-substrate concordance QC (#732) consumes.
The load-bearing contract is FAIL-LOUD: a join that resolves to zero shared
genes (a version-mismatch, a wrong id column, an empty frame) RAISES rather
than silently returning an empty result that reads downstream as "the two
substrates agree on nothing" or, worse, "there is nothing to compare."
"""

from __future__ import annotations

import pandas as pd


def _strip_version(ensembl_id: str) -> str:
    return str(ensembl_id).split(".", 1)[0]


def resolve_to_authority(ids, authority: pd.DataFrame) -> pd.DataFrame:
    """Map an iterable of native Ensembl IDs (versioned or unversioned) onto the
    authority.

    Returns a DataFrame with one row per input id:
        native_id  str   the input id, verbatim
        gene_id    str   unversioned authority key (NA if not in the authority)
        mapped     bool  whether the id resolved to an authority row

    Order and duplicates in `ids` are preserved.
    """
    valid = set(authority["gene_id"])
    native = list(ids)
    stems = [_strip_version(x) for x in native]
    gene_id = [s if s in valid else pd.NA for s in stems]
    return pd.DataFrame(
        {
            "native_id": native,
            "gene_id": gene_id,
            "mapped": [g is not pd.NA for g in gene_id],
        }
    )


def coverage(ids, authority: pd.DataFrame) -> dict:
    """Per-substrate coverage denominators for a native id list.

    Returns n_total / n_mapped / n_dropped and the dropped ids (up to a sample),
    so a caller can report "n mapped / n dropped" honestly.
    """
    res = resolve_to_authority(ids, authority)
    dropped = res.loc[~res["mapped"], "native_id"].tolist()
    return {
        "n_total": int(len(res)),
        "n_mapped": int(res["mapped"].sum()),
        "n_dropped": int((~res["mapped"]).sum()),
        "dropped_sample": dropped[:20],
    }


def join_on_authority(
    left: pd.DataFrame,
    right: pd.DataFrame,
    authority: pd.DataFrame,
    *,
    left_on: str,
    right_on: str,
    suffixes: tuple[str, str] = ("_left", "_right"),
    min_shared: int = 1,
) -> pd.DataFrame:
    """Inner-join two substrate frames on the authority gene_id.

    Each frame's id column (`left_on` / `right_on`, native versioned or
    unversioned Ensembl IDs) is resolved to the unversioned authority key, then
    the two frames are inner-merged on that key.

    FAIL-LOUD: raises ValueError if fewer than `min_shared` genes resolve and
    join. An empty or degenerate join is a defect (version mismatch, wrong id
    column, empty input) and must never pass silently as "0 rows".

    Returns the merged frame with an added `gene_id` (authority key) column and
    the authority's `symbol_canonical` attached for legibility.
    """
    if left_on not in left.columns:
        raise ValueError(f"left_on={left_on!r} not in left columns {list(left.columns)}")
    if right_on not in right.columns:
        raise ValueError(f"right_on={right_on!r} not in right columns {list(right.columns)}")

    lres = resolve_to_authority(left[left_on], authority)
    rres = resolve_to_authority(right[right_on], authority)

    left2 = left.copy()
    right2 = right.copy()
    left2["gene_id"] = lres["gene_id"].to_numpy()
    right2["gene_id"] = rres["gene_id"].to_numpy()
    left2 = left2[left2["gene_id"].notna()]
    right2 = right2[right2["gene_id"].notna()]

    merged = left2.merge(right2, on="gene_id", how="inner", suffixes=suffixes)

    if len(merged) < min_shared:
        raise ValueError(
            "gene-id authority join is degenerate: "
            f"{len(merged)} shared gene(s) < min_shared={min_shared}. "
            f"left mapped {int(lres['mapped'].sum())}/{len(lres)}, "
            f"right mapped {int(rres['mapped'].sum())}/{len(rres)}. "
            "Refusing to return a silently empty join (check id columns / "
            "release versions)."
        )

    sym = authority.set_index("gene_id")["symbol_canonical"]
    merged["symbol_canonical"] = merged["gene_id"].map(sym)
    return merged
