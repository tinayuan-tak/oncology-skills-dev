"""Audit the gene-ID authority: symbol drift, symbol reuse, and per-substrate
coverage denominators.

These are the diagnostic outputs #699 asks for. They quantify exactly what the
old symbol-string cross-substrate join got wrong, so the concordance QC (#732)
can report "n recovered by joining on stable id" rather than absorbing the loss
silently.
"""

from __future__ import annotations

import argparse
import json
import sys

import pandas as pd


def _n_symbol_reassigned_disjoint(authority: pd.DataFrame) -> int:
    """Sharpest reuse subset: symbols whose v23 gene set and v116 gene set are
    both non-empty and DISJOINT — the symbol was reassigned wholesale to a
    different Ensembl gene between releases (e.g. MEG8, UGT1A5)."""
    v23 = authority.loc[authority["symbol_gencode_v23"].notna()].groupby("symbol_gencode_v23")["gene_id"].agg(set)
    v116 = authority.loc[authority["symbol_hgnc"].notna()].groupby("symbol_hgnc")["gene_id"].agg(set)
    common = set(v23.index) & set(v116.index)
    return int(sum(1 for s in common if v23[s].isdisjoint(v116[s])))


def audit_authority(authority: pd.DataFrame) -> dict:
    """Structural audit of the authority table itself."""
    both = authority["in_ensembl116"] & authority["in_gencode_v23"]
    return {
        "n_genes": int(len(authority)),
        "n_in_both_sources": int(both.sum()),
        "n_ensembl116_only": int((authority["in_ensembl116"] & ~authority["in_gencode_v23"]).sum()),
        "n_gencode_v23_only": int((~authority["in_ensembl116"] & authority["in_gencode_v23"]).sum()),
        "n_symbol_drift": int(authority["symbol_drift"].sum()),
        "n_symbol_reuse_conflict": int(authority["symbol_reuse_conflict"].sum()),
        "n_symbol_reassigned_disjoint": _n_symbol_reassigned_disjoint(authority),
        "n_no_hgnc_symbol": int(authority["symbol_hgnc"].isna().sum()),
    }


def symbol_join_loss(authority: pd.DataFrame, *, sample: int = 15) -> dict:
    """What a naive symbol-string cross-substrate join gets wrong.

    Restricted to genes present in BOTH substrates (the population a
    cross-substrate concordance would compare):

      * drift → the two arms carry different symbols for the same gene, so a
        symbol join DROPS it (looks one-arm-only).
      * reuse → the symbol is ambiguous across the union, so a symbol join risks
        MIS-MAPPING it onto a different gene.

    These are exactly the genes an authority (unversioned-id) join recovers.
    """
    both = authority[authority["in_ensembl116"] & authority["in_gencode_v23"]]
    drift = both[both["symbol_drift"]]
    reuse = both[both["symbol_reuse_conflict"]]

    # Reassignment examples: a symbol pointing at a DIFFERENT gene in each
    # release (the sharpest "mis-map" illustration), showing both gene ids.
    v23 = authority.loc[authority["symbol_gencode_v23"].notna()].groupby("symbol_gencode_v23")["gene_id"].agg(set)
    v116 = authority.loc[authority["symbol_hgnc"].notna()].groupby("symbol_hgnc")["gene_id"].agg(set)
    reassign_examples = []
    for s in sorted(set(v23.index) & set(v116.index)):
        if v23[s].isdisjoint(v116[s]):
            reassign_examples.append(
                {"symbol": s, "gencode_v23_gene_id": sorted(v23[s]), "ensembl116_gene_id": sorted(v116[s])}
            )
            if len(reassign_examples) >= sample:
                break

    return {
        "n_comparable_both_substrates": int(len(both)),
        "n_dropped_by_symbol_drift": int(len(drift)),
        "n_at_risk_symbol_reuse": int(len(reuse)),
        "drift_examples": drift[["gene_id", "symbol_gencode_v23", "symbol_hgnc"]].head(sample).to_dict("records"),
        "reassignment_examples": reassign_examples,
    }


def coverage_report(authority: pd.DataFrame) -> dict:
    """Per-substrate coverage denominators against the shared authority.

    For each substrate: how many of its native genes land on an authority row
    (all of them, by construction — the authority is the union) and, of those,
    how many carry an HGNC symbol vs would be lost / ambiguous under the legacy
    symbol join.
    """
    ens = authority[authority["in_ensembl116"]]
    v23 = authority[authority["in_gencode_v23"]]
    return {
        "ensembl116": {
            "n_native_genes": int(len(ens)),
            "n_with_hgnc_symbol": int(ens["symbol_hgnc"].notna().sum()),
            "n_shared_with_gencode_v23": int((ens["in_gencode_v23"]).sum()),
        },
        "gencode_v23": {
            "n_native_genes": int(len(v23)),
            "n_shared_with_ensembl116": int((v23["in_ensembl116"]).sum()),
            "n_absent_from_ensembl116": int((~v23["in_ensembl116"]).sum()),
        },
    }


def full_report(authority: pd.DataFrame) -> dict:
    """The complete #699 audit + coverage bundle."""
    return {
        "authority_audit": audit_authority(authority),
        "symbol_join_loss": symbol_join_loss(authority),
        "coverage": coverage_report(authority),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--parquet",
        type=str,
        default=None,
        help="Authority parquet path. Default: load via the pinned loader (S3/cache).",
    )
    ap.add_argument("--out-json", type=str, default=None, help="Write the report JSON here (else stdout).")
    args = ap.parse_args()

    if args.parquet:
        authority = pd.read_parquet(args.parquet)
    else:
        from .loader import load_gene_id_authority

        authority = load_gene_id_authority()

    report = full_report(authority)
    text = json.dumps(report, indent=2)
    if args.out_json:
        with open(args.out_json, "w") as fh:
            fh.write(text + "\n")
        print(f"[audit] wrote report -> {args.out_json}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
