"""Build a shared, version-stripped Ensembl gene-ID authority across the two
dge_deseq2 count substrates.

WHY THIS EXISTS (analysis-methods#699)
--------------------------------------
The four-cell dge_deseq2 pipeline draws counts from two substrates that were
annotated against DIFFERENT GENCODE releases:

  * recount3 tcga-gtex-2023-01-04  — GENCODE v26; the loader maps its native
    Ensembl gene IDs to HGNC symbols via the Ensembl release-116 id-mapping
    (data-catalog source `ensembl-id-mapping-release-116-snapshot-2026-06-18`).
  * Xena/Toil TcgaTargetGtex          — GENCODE v23; the loader maps its native
    Ensembl gene IDs to symbols via the v23 probemap
    (`gencode.v23.annotation.gene.probemap`, in the xena-toil source release).

Both loaders then COLLAPSE counts to HGNC symbol and key their products by
`gene_symbol`. Any cross-substrate comparison (the S3c concordance QC, #732)
therefore joins the two products on the SYMBOL STRING. That join is silently
wrong in two ways, both real in this data:

  * SYMBOL DRIFT — the same stable Ensembl gene has a different symbol in v23
    vs v116 (e.g. ENSG00000244646 is XKRY2 in v23, XKRYP7 in v116). A symbol
    join silently DROPS the gene: it looks absent from one arm.
  * SYMBOL REUSE — a symbol string is reassigned to a DIFFERENT Ensembl gene
    between releases (e.g. MEG8, UGT1A5). A symbol join silently MIS-MAPS:
    it fuses counts from two different genes.

The fix is to join on the stable, release-invariant identity: the UNVERSIONED
Ensembl gene ID. This module builds an authority table keyed on that id,
carrying each release's symbol so drift/reuse are explicit and auditable
rather than silent.

SCOPE (capability-first slice of #699)
--------------------------------------
This builds the authority table + audit + coverage capability. It does NOT
repoint the live R loaders' symbol collapse onto the authority — that rewire is
verdict-affecting and sequenced separately. `harmonize.py` provides the
fail-loud join the concordance QC (#732) consumes.

Output schema (one row per unversioned Ensembl gene ID in the UNION of the two
sources):

    gene_id               str   unversioned Ensembl gene ID (ENSG00000...).
                                 The authority join key. Release-invariant.
    symbol_hgnc           str   HGNC symbol from Ensembl-116 (canonical). NA
                                 when the gene has no HGNC symbol at v116.
    hgnc_id               str   HGNC:NNNN accession from Ensembl-116. NA if none.
    gene_name_ensembl     str   Ensembl-116 "Gene name" (legibility tiebreaker).
    symbol_gencode_v23    str   Symbol carried by the GENCODE v23 probemap. NA
                                 when the gene is absent from v23.
    symbol_canonical      str   symbol_hgnc if present else symbol_gencode_v23.
                                 Never NA (union guarantees >=1 source symbol).
    in_ensembl116         bool  gene_id appears in the Ensembl-116 id-mapping.
    in_gencode_v23        bool  gene_id appears in the v23 probemap.
    symbol_drift          bool  present in BOTH sources with DIFFERING symbols.
    symbol_reuse_conflict bool  symbol_canonical is carried by >1 gene_id across
                                the union (a symbol-string join is ambiguous
                                for this gene).

Usage:
    python -m onc_methods.gene_id_authority.build \\
        --ensembl116-tsv hsapiens_gene_id_map_release-116.tsv \\
        --gencode-v23-probemap gencode.v23.annotation.gene.probemap \\
        --out-parquet gene_id_authority_v23_v116.parquet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Ensembl-116 id-mapping columns (see the source manifest description).
_ENS_ID_COL = "Gene stable ID"
_ENS_SYMBOL_COL = "HGNC symbol"
_ENS_HGNC_ID_COL = "HGNC ID"
_ENS_GENE_NAME_COL = "Gene name"

# GENCODE v23 probemap columns (id is the versioned Ensembl gene ID).
_V23_ID_COL = "id"
_V23_SYMBOL_COL = "gene"


def _strip_version(ensembl_id: str) -> str:
    """ENSG00000141510.11 -> ENSG00000141510. Idempotent on unversioned ids."""
    return ensembl_id.split(".", 1)[0]


def _read_ensembl116(path: Path) -> pd.DataFrame:
    """Ensembl-116 id-mapping -> DataFrame[gene_id, symbol_hgnc, hgnc_id, gene_name_ensembl].

    Keeps every row that has an unversioned gene id (rows with no HGNC symbol are
    retained — the gene still exists in the release, it just has no HGNC name).
    Collapses the rare duplicate gene_id (the release ships 2) preferring a row
    that carries an HGNC symbol, so the authority never silently loses a name.
    """
    df = pd.read_csv(path, sep="\t", dtype=str)
    missing = {_ENS_ID_COL, _ENS_SYMBOL_COL} - set(df.columns)
    if missing:
        raise ValueError(f"Ensembl-116 TSV missing expected columns {sorted(missing)}; got {list(df.columns)}")
    df = df.rename(
        columns={
            _ENS_ID_COL: "gene_id",
            _ENS_SYMBOL_COL: "symbol_hgnc",
            _ENS_HGNC_ID_COL: "hgnc_id",
            _ENS_GENE_NAME_COL: "gene_name_ensembl",
        }
    )
    df["gene_id"] = df["gene_id"].str.strip()
    df = df[df["gene_id"].notna() & (df["gene_id"] != "")]
    for col in ("symbol_hgnc", "hgnc_id", "gene_name_ensembl"):
        if col not in df.columns:
            df[col] = pd.NA
    # Normalise empty strings to NA so downstream "present" tests are clean.
    for col in ("symbol_hgnc", "hgnc_id", "gene_name_ensembl"):
        df[col] = df[col].where(df[col].notna() & (df[col].astype(str).str.strip() != ""), pd.NA)
    # Collapse duplicate gene_id: prefer the row with an HGNC symbol.
    df = df.assign(_has_sym=df["symbol_hgnc"].notna())
    df = (
        df.sort_values(["gene_id", "_has_sym"], ascending=[True, False], kind="stable")
        .drop_duplicates("gene_id", keep="first")
        .drop(columns="_has_sym")
    )
    return df[["gene_id", "symbol_hgnc", "hgnc_id", "gene_name_ensembl"]].reset_index(drop=True)


def _read_gencode_v23(path: Path) -> pd.DataFrame:
    """v23 probemap -> DataFrame[gene_id, symbol_gencode_v23] (unversioned key)."""
    df = pd.read_csv(path, sep="\t", dtype=str)
    missing = {_V23_ID_COL, _V23_SYMBOL_COL} - set(df.columns)
    if missing:
        raise ValueError(f"v23 probemap missing expected columns {sorted(missing)}; got {list(df.columns)}")
    df = df.rename(columns={_V23_ID_COL: "gene_id_versioned", _V23_SYMBOL_COL: "symbol_gencode_v23"})
    df["gene_id"] = df["gene_id_versioned"].map(_strip_version)
    df["symbol_gencode_v23"] = df["symbol_gencode_v23"].where(
        df["symbol_gencode_v23"].notna() & (df["symbol_gencode_v23"].astype(str).str.strip() != ""), pd.NA
    )
    # Probemap ids are unique after version-strip in the real data; guard anyway.
    df = df.drop_duplicates("gene_id", keep="first")
    return df[["gene_id", "symbol_gencode_v23"]].reset_index(drop=True)


def build_authority(ensembl116_tsv: Path, gencode_v23_probemap: Path) -> pd.DataFrame:
    """Build the gene-ID authority DataFrame from the two source files.

    Row key is the UNION of unversioned Ensembl gene IDs across both sources.
    See the module docstring for the emitted schema.
    """
    ens = _read_ensembl116(Path(ensembl116_tsv))
    v23 = _read_gencode_v23(Path(gencode_v23_probemap))

    auth = ens.merge(v23, on="gene_id", how="outer")

    auth["in_ensembl116"] = auth["gene_id"].isin(set(ens["gene_id"]))
    auth["in_gencode_v23"] = auth["gene_id"].isin(set(v23["gene_id"]))

    # Canonical symbol: HGNC (v116) wins; fall back to the v23 symbol.
    auth["symbol_canonical"] = auth["symbol_hgnc"].where(auth["symbol_hgnc"].notna(), auth["symbol_gencode_v23"])

    # Restrict to the JOIN-RELEVANT universe: a gene must carry a symbol in at
    # least one source to appear in either dge_deseq2 product (recount3 keeps
    # only HGNC-mappable genes; Toil keeps only v23 genes). Ensembl-116 rows with
    # no HGNC symbol AND absent from v23 (non-coding ids with no HGNC name, not
    # in the Toil substrate) can never surface in a product, so they are inert
    # for harmonization and dropped — keeping symbol_canonical non-null for every
    # authority row.
    auth = auth[auth["symbol_canonical"].notna()].reset_index(drop=True)

    both = auth["symbol_hgnc"].notna() & auth["symbol_gencode_v23"].notna()
    auth["symbol_drift"] = both & (auth["symbol_hgnc"] != auth["symbol_gencode_v23"])

    # Reuse: the CROSS-SUBSTRATE mis-map hazard. The concordance join pairs the
    # symbol Toil uses (its v23 probemap symbol) against the symbol recount3 uses
    # (its Ensembl-116 HGNC symbol). A gene is flagged when its symbol in one
    # substrate's space is ALSO carried — by a DIFFERENT gene — in the other
    # substrate's space, i.e. joining on that symbol string would fuse two
    # distinct genes (e.g. MEG8, UGT1A5 were reassigned to different Ensembl IDs
    # between v23 and v116). This is the "silent mis-map on symbol reuse" #699
    # names, and it is exactly what an unversioned-id join eliminates.
    v23_sym_to_genes = auth.loc[auth["symbol_gencode_v23"].notna()].groupby("symbol_gencode_v23")["gene_id"].agg(set)
    v116_sym_to_genes = auth.loc[auth["symbol_hgnc"].notna()].groupby("symbol_hgnc")["gene_id"].agg(set)

    def _reuse_conflict(gene_id: str, s23, s116) -> bool:
        if pd.notna(s23):
            others = v116_sym_to_genes.get(s23)
            if others is not None and (others - {gene_id}):
                return True
        if pd.notna(s116):
            others = v23_sym_to_genes.get(s116)
            if others is not None and (others - {gene_id}):
                return True
        return False

    auth["symbol_reuse_conflict"] = [
        _reuse_conflict(g, s23, s116)
        for g, s23, s116 in zip(auth["gene_id"], auth["symbol_gencode_v23"], auth["symbol_hgnc"])
    ]

    auth = auth[
        [
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
    ]
    auth = auth.sort_values("gene_id", kind="stable").reset_index(drop=True)
    return auth


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ensembl116-tsv", required=True, type=Path)
    ap.add_argument("--gencode-v23-probemap", required=True, type=Path)
    ap.add_argument("--out-parquet", required=True, type=Path)
    args = ap.parse_args()

    auth = build_authority(args.ensembl116_tsv, args.gencode_v23_probemap)

    args.out_parquet.parent.mkdir(parents=True, exist_ok=True)
    auth.to_parquet(args.out_parquet, index=False, compression="snappy")

    n = len(auth)
    print(f"[build] wrote {n:,} gene-id authority rows -> {args.out_parquet}", file=sys.stderr)
    print(f"[build]   in both sources: {(auth['in_ensembl116'] & auth['in_gencode_v23']).sum():,}", file=sys.stderr)
    print(f"[build]   Ensembl-116 only: {(auth['in_ensembl116'] & ~auth['in_gencode_v23']).sum():,}", file=sys.stderr)
    print(f"[build]   GENCODE-v23 only: {(~auth['in_ensembl116'] & auth['in_gencode_v23']).sum():,}", file=sys.stderr)
    print(f"[build]   symbol_drift: {auth['symbol_drift'].sum():,}", file=sys.stderr)
    print(f"[build]   symbol_reuse_conflict: {auth['symbol_reuse_conflict'].sum():,}", file=sys.stderr)
    print(f"[build]   size on disk: {args.out_parquet.stat().st_size:,} bytes", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
