"""Annotate a symbol-keyed dge_deseq2 product with the stable authority gene_id.

The four-cell dge_deseq2 products are keyed on `gene_symbol` and never carry the
Ensembl gene id (the loaders collapse counts to symbol; `gene_id` lives only in
the R loader's rowdata, not in the emitted parquet). So a cross-substrate
comparison — the S3c concordance QC, analysis-methods#732 — cannot join on the
stable identity without first resolving each product row's symbol back to the
authority gene_id.

This module does exactly that resolution, in the ONE tested place the authority
lives, WITHOUT touching the R loaders (they keep their byte-identity). It exploits
the fact that each substrate's collapse key IS one of the authority's symbol
columns:

  * recount3 collapses to the Ensembl-116 HGNC symbol == authority `symbol_hgnc`
  * Xena/Toil collapses to the v23 probemap `gene` == authority `symbol_gencode_v23`

so a product symbol can be resolved to the authority gene_id(s) that carry that
symbol IN THAT SUBSTRATE'S OWN NAMESPACE. The resolution is HONEST about the two
ways a symbol row has no single stable identity:

  * a symbol carried by >1 authority gene in the substrate's namespace is a
    genuine COLLAPSE (the loader summed those genes into one row — e.g. a
    PAR_Y pair). There is no single gene_id, so `gene_id` is NA and
    `ensg_ambiguous` is True — NEVER a fabricated first-seen id that would give
    #732 a false-precise join key.
  * a symbol absent from the authority's substrate namespace is `mapped` False.

It is FAIL-LOUD: a product that resolves to fewer than `min_mapped` genes (wrong
substrate, an id-keyed frame passed as symbol-keyed, an empty product) RAISES
rather than returning a silently unmapped frame that reads downstream as "these
substrates share nothing."
"""

from __future__ import annotations

import pandas as pd

# Each substrate's symbol-collapse namespace == one authority symbol column.
SUBSTRATE_SYMBOL_COLUMN = {
    "recount3": "symbol_hgnc",
    "xena_toil": "symbol_gencode_v23",
}


def _substrate_symbol_column(substrate: str) -> str:
    try:
        return SUBSTRATE_SYMBOL_COLUMN[substrate]
    except KeyError:
        raise ValueError(
            f"unknown substrate {substrate!r}; expected one of {sorted(SUBSTRATE_SYMBOL_COLUMN)}"
        ) from None


def resolve_symbols_to_gene_ids(symbols, substrate: str, authority: pd.DataFrame) -> pd.DataFrame:
    """Resolve an iterable of product symbols onto the authority gene_id.

    Keys each symbol against the authority column for `substrate`
    (`symbol_hgnc` for recount3, `symbol_gencode_v23` for Xena/Toil) and returns
    one row per input symbol, order and duplicates preserved:

        gene_symbol           str   the input symbol, verbatim
        gene_id               str   authority key when the symbol backs exactly
                                    ONE gene in this substrate's namespace, else NA
        n_authority_genes     int   how many authority genes carry this symbol here
        mapped                bool  n_authority_genes >= 1
        ensg_ambiguous        bool  n_authority_genes > 1 (a genuine collapse; no
                                    single stable id — do NOT join on it)
        symbol_drift          bool  authority drift flag for the resolved gene (NA
                                    when unmapped/ambiguous)
        symbol_reuse_conflict bool  authority reuse flag for the resolved gene (NA
                                    when unmapped/ambiguous)
    """
    sym_col = _substrate_symbol_column(substrate)
    for required in (sym_col, "gene_id", "symbol_drift", "symbol_reuse_conflict"):
        if required not in authority.columns:
            raise ValueError(f"authority missing column {required!r}; got {list(authority.columns)}")

    sub = authority[authority[sym_col].notna()]
    sym_to_genes = sub.groupby(sym_col)["gene_id"].agg(list)
    drift = authority.set_index("gene_id")["symbol_drift"]
    reuse = authority.set_index("gene_id")["symbol_reuse_conflict"]

    syms = [str(s) for s in symbols]
    gene_id: list = []
    n_genes: list = []
    d_flag: list = []
    r_flag: list = []
    for s in syms:
        genes = sym_to_genes.get(s, [])
        n = len(genes)
        n_genes.append(n)
        if n == 1:
            g = genes[0]
            gene_id.append(g)
            d_flag.append(bool(drift.loc[g]))
            r_flag.append(bool(reuse.loc[g]))
        else:
            gene_id.append(pd.NA)
            d_flag.append(pd.NA)
            r_flag.append(pd.NA)

    return pd.DataFrame(
        {
            "gene_symbol": syms,
            "gene_id": gene_id,
            "n_authority_genes": n_genes,
            "mapped": [n >= 1 for n in n_genes],
            "ensg_ambiguous": [n > 1 for n in n_genes],
            "symbol_drift": d_flag,
            "symbol_reuse_conflict": r_flag,
        }
    )


def annotate_product_with_gene_id(
    product: pd.DataFrame,
    substrate: str,
    authority: pd.DataFrame | None = None,
    *,
    symbol_col: str = "gene_symbol",
    min_mapped: int = 1,
) -> pd.DataFrame:
    """Return `product` with the authority gene_id + resolution flags attached.

    Adds `gene_id`, `n_authority_genes`, `mapped`, `ensg_ambiguous`,
    `symbol_drift`, `symbol_reuse_conflict` (see `resolve_symbols_to_gene_ids`).
    The input rows/columns are otherwise untouched and their order preserved, so
    a caller (the #732 concordance QC) can filter to `mapped & ~ensg_ambiguous`
    and inner-join two products on `gene_id`.

    FAIL-LOUD: raises ValueError if fewer than `min_mapped` rows resolve — an
    empty product, a wrong substrate, or an id-keyed frame passed as
    symbol-keyed must not pass silently as "nothing to compare."
    """
    if authority is None:
        from .loader import load_gene_id_authority

        authority = load_gene_id_authority()
    if symbol_col not in product.columns:
        raise ValueError(f"symbol_col={symbol_col!r} not in product columns {list(product.columns)}")

    res = resolve_symbols_to_gene_ids(product[symbol_col], substrate, authority)
    n_mapped = int(res["mapped"].sum())
    if n_mapped < min_mapped:
        sym_col = _substrate_symbol_column(substrate)
        raise ValueError(
            "gene-id authority product resolution is degenerate: "
            f"{n_mapped} of {len(res)} row(s) resolved (< min_mapped={min_mapped}) "
            f"for substrate={substrate!r} keyed on authority column {sym_col!r}. "
            "Refusing to return a silently unmapped product (check the substrate / "
            f"that {symbol_col!r} carries symbols, not Ensembl ids)."
        )

    out = product.copy()
    for col in ("gene_id", "n_authority_genes", "mapped", "ensg_ambiguous", "symbol_drift", "symbol_reuse_conflict"):
        out[col] = res[col].to_numpy()
    return out
