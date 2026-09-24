"""dge_deseq2.concordance — cross-substrate REPRODUCIBILITY concordance QC (S3c, #732).

The four-cell DESeq2 pipeline runs on two count substrates for the same tumor
cohort: the primary **recount3** (GENCODE v26, the verdict substrate) and the
secondary/diagnostic **Xena/Toil** (GENCODE v23, S1b #694). This module measures
how well the per-gene effect sizes agree BETWEEN the two substrates for the same
contrast cell — cell A (tumor vs paired-adjacent) and cell C (tumor vs GTEx).

⚠️ **REPRODUCIBILITY-ONLY, NOT biological validation.** The two substrates are
reprocessed from largely the SAME raw TCGA/GTEx reads, so agreement measures
*pipeline stability* (aligner / gene model / quantifier / normalisation), NOT
that the biology is true. High concordance means the recount3 verdict is
reproducible under a different processing pipeline; it does not corroborate it.
Every emitted row carries ``reproducibility_only=True`` to keep that framing
attached to the number.

**The join is on the stable authority gene_id, never on the HGNC symbol.** The
products are keyed on ``gene_symbol`` and the two substrates collapse counts to
DIFFERENT symbol vocabularies (Ensembl-116 HGNC for recount3, GENCODE-v23
probemap for Xena/Toil). A symbol-string join across those vocabularies silently
drops drifted symbols and mis-maps reused ones (gene_id_authority #699 quantified
8,221 drift + 441 reuse genes) — that annotation-skew artifact is exactly what
this QC exists to catch, so joining on the symbol would confound the measurement
it reports. Instead each product is resolved back to the authority gene_id via
:func:`methods.gene_id_authority.product.annotate_product_with_gene_id` (read
time — the products' bytes are untouched), keying each substrate's collapse
symbol against ITS OWN authority namespace, and only genes that resolve to
exactly ONE authority gene in both substrates (``mapped & ~ensg_ambiguous``)
enter the join.

**FAIL-LOUD.** An empty or degenerate shared-gene join is the failure mode this
QC exists to expose — a silently empty comparison reads downstream as "the two
substrates share nothing / agree on nothing," which is false and dangerous. So a
join below ``min_shared`` genes, or a gated (significant-in-both) set below
``min_gated`` genes, RAISES :class:`ConcordanceError` rather than emitting a
NaN/None concordance. The discovery layer likewise raises when zero substrate
pairs are declared, and reconciles declared-but-uncatalogued pairs.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

# Only cells A and C are cross-substrate comparable: cell B (ComBat-seq on the
# TCGA-TSS batch structure) is not run on Xena/Toil, and the AG diagnostic cell
# is normal-vs-normal, not a tumor contrast.
CELLS: tuple[str, ...] = ("A", "C")

DEFAULT_PADJ_MAX = 0.05
DEFAULT_MIN_ABS_LFC = 1.0
# A recount3-vs-Xena COADREAD contrast shares ~20k measured genes; a shared set
# in the low hundreds already signals a broken/mismatched join. A significant-in
# -both gated set below a few dozen makes a Spearman meaningless. Both floors are
# deliberately conservative — they must RED on a degenerate join, not on a real
# (merely small) one.
DEFAULT_MIN_SHARED = 100
DEFAULT_MIN_GATED = 25


class ConcordanceError(ValueError):
    """A cross-substrate concordance join is empty or degenerate."""


# --------------------------------------------------------------------------- #
# coverage denominators (per substrate)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CoverageDenominators:
    """Per-substrate gene-id resolution accounting, so the shared-gene denominator
    is auditable: every product row lands in exactly one of mapped-usable /
    ambiguous-dropped / unmapped-dropped."""

    substrate: str
    n_product_rows: int  # rows in the product (== symbols)
    n_mapped: int  # symbols backing >= 1 authority gene in this substrate's namespace
    n_unmapped_dropped: int  # symbols absent from the authority namespace (mapped == False)
    n_ambiguous_dropped: int  # symbols backing > 1 authority gene (collapse; no single stable id)
    n_usable_gene_id: int  # distinct gene_id after mapped & ~ambiguous (the join-eligible universe)


def coverage_denominators(resolved: pd.DataFrame, substrate: str) -> CoverageDenominators:
    """Account for every row of a gene-id-annotated product (see
    :func:`resolve_products`) against the mapped / ambiguous / unmapped buckets."""
    for col in ("mapped", "ensg_ambiguous", "gene_id"):
        if col not in resolved.columns:
            raise ValueError(f"resolved product missing {col!r}; run annotate_product_with_gene_id first")
    mapped = resolved["mapped"].fillna(False).astype(bool)
    ambiguous = resolved["ensg_ambiguous"].fillna(False).astype(bool)
    usable = mapped & ~ambiguous & resolved["gene_id"].notna()
    return CoverageDenominators(
        substrate=substrate,
        n_product_rows=int(len(resolved)),
        n_mapped=int(mapped.sum()),
        n_unmapped_dropped=int((~mapped).sum()),
        n_ambiguous_dropped=int((mapped & ambiguous).sum()),
        n_usable_gene_id=int(resolved.loc[usable, "gene_id"].nunique()),
    )


# --------------------------------------------------------------------------- #
# per-cell concordance
# --------------------------------------------------------------------------- #
@dataclass
class CellConcordance:
    indication: str
    cell: str
    reproducibility_only: bool
    coverage: dict  # substrate -> CoverageDenominators-as-dict
    gate: dict  # {padj_max, min_abs_lfc}
    n_shared_gene_id: int  # inner join on gene_id, measured (log2fc non-NaN) in both substrates
    n_gated: int  # shared AND significant (padj < padj_max) in both — the Spearman set
    n_sign_discordant: int  # gated genes whose log2fc sign disagrees across substrates
    n_effect_gated: int  # gated genes ALSO passing |log2fc| >= min_abs_lfc in both substrates
    spearman_rho: float  # Spearman rho of log2fc over the gated set
    spearman_p: float  # its two-sided p-value
    spearman_rho_all_shared: float  # rho over all shared (ungated) genes — context, not the headline


def _cell_frame(resolved: pd.DataFrame, cell: str) -> pd.DataFrame:
    """Reduce a resolved product to one row per usable gene_id measured in `cell`.

    Keeps only mapped & unambiguous rows that carry a non-NaN log2fc for the cell
    (a gene dropped by independent filtering in this contrast is not "measured"),
    returning columns ``gene_id / log2fc / padj``. De-duplicates on gene_id
    defensively — a substrate namespace maps each symbol to one gene, so this is a
    no-op in practice, but a duplicate gene_id would corrupt the inner join.
    """
    lfc_col, padj_col = f"log2fc_{cell}", f"padj_{cell}"
    for col in (lfc_col, padj_col):
        if col not in resolved.columns:
            raise ValueError(f"product missing {col!r}; got {list(resolved.columns)}")
    mapped = resolved["mapped"].fillna(False).astype(bool)
    ambiguous = resolved["ensg_ambiguous"].fillna(False).astype(bool)
    usable = mapped & ~ambiguous & resolved["gene_id"].notna() & resolved[lfc_col].notna()
    out = resolved.loc[usable, ["gene_id", lfc_col, padj_col]].rename(columns={lfc_col: "log2fc", padj_col: "padj"})
    return out.drop_duplicates(subset="gene_id", keep="first").reset_index(drop=True)


def concordance_for_cell(
    recount3_resolved: pd.DataFrame,
    xenatoil_resolved: pd.DataFrame,
    cell: str,
    indication: str,
    *,
    padj_max: float = DEFAULT_PADJ_MAX,
    min_abs_lfc: float = DEFAULT_MIN_ABS_LFC,
    min_shared: int = DEFAULT_MIN_SHARED,
    min_gated: int = DEFAULT_MIN_GATED,
) -> CellConcordance:
    """Cross-substrate concordance for one contrast cell.

    Both inputs must already be gene-id-annotated (see :func:`resolve_products`).
    Joins on the authority gene_id, gates to genes significant (padj < padj_max)
    in BOTH substrates, and reports the Spearman rho of their log2fc.

    Raises :class:`ConcordanceError` when the shared join is below ``min_shared``
    or the gated set below ``min_gated`` — a degenerate comparison must not emit a
    NaN concordance that reads as a real (weak) one.
    """
    from scipy.stats import spearmanr

    r = _cell_frame(recount3_resolved, cell)
    x = _cell_frame(xenatoil_resolved, cell)
    merged = r.merge(x, on="gene_id", how="inner", suffixes=("_recount3", "_xena_toil"))
    n_shared = int(len(merged))
    if n_shared < min_shared:
        raise ConcordanceError(
            f"{indication} cell {cell}: shared-gene join is degenerate — {n_shared} gene(s) "
            f"resolve to a single authority gene_id and are measured in BOTH substrates "
            f"(< min_shared={min_shared}). Refusing to emit a concordance over an empty/degenerate "
            "join (check the substrate keys / that both products resolved against the authority)."
        )

    sig_both = (merged["padj_recount3"] < padj_max) & (merged["padj_xena_toil"] < padj_max)
    gated = merged.loc[sig_both]
    n_gated = int(len(gated))
    if n_gated < min_gated:
        raise ConcordanceError(
            f"{indication} cell {cell}: only {n_gated} of {n_shared} shared genes are significant "
            f"(padj < {padj_max}) in BOTH substrates (< min_gated={min_gated}). A Spearman over so "
            "few genes is not a meaningful concordance — failing loud rather than emitting it."
        )

    rho, pval = spearmanr(gated["log2fc_recount3"], gated["log2fc_xena_toil"])
    rho_all, _ = spearmanr(merged["log2fc_recount3"], merged["log2fc_xena_toil"])

    sign_r = gated["log2fc_recount3"] > 0
    sign_x = gated["log2fc_xena_toil"] > 0
    n_sign_discordant = int((sign_r != sign_x).sum())
    effect_both = (gated["log2fc_recount3"].abs() >= min_abs_lfc) & (gated["log2fc_xena_toil"].abs() >= min_abs_lfc)

    return CellConcordance(
        indication=indication,
        cell=cell,
        reproducibility_only=True,
        coverage={
            "recount3": asdict(coverage_denominators(recount3_resolved, "recount3")),
            "xena_toil": asdict(coverage_denominators(xenatoil_resolved, "xena_toil")),
        },
        gate={"padj_max": padj_max, "min_abs_lfc": min_abs_lfc},
        n_shared_gene_id=n_shared,
        n_gated=n_gated,
        n_sign_discordant=n_sign_discordant,
        n_effect_gated=int(effect_both.sum()),
        spearman_rho=float(rho),
        spearman_p=float(pval),
        spearman_rho_all_shared=float(rho_all),
    )


def resolve_products(
    recount3_product: pd.DataFrame,
    xenatoil_product: pd.DataFrame,
    authority: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Annotate both products with the authority gene_id in ONE authority load.

    Each substrate is keyed against its OWN authority symbol namespace
    (recount3 -> symbol_hgnc, xena_toil -> symbol_gencode_v23). Fail-loud
    (via :func:`annotate_product_with_gene_id`) if either resolves to zero genes.
    """
    from methods.gene_id_authority.product import annotate_product_with_gene_id

    if authority is None:
        from methods.gene_id_authority.loader import load_gene_id_authority

        authority = load_gene_id_authority()
    r = annotate_product_with_gene_id(recount3_product, "recount3", authority)
    x = annotate_product_with_gene_id(xenatoil_product, "xena_toil", authority)
    return r, x


def concordance_for_pair(
    recount3_product: pd.DataFrame,
    xenatoil_product: pd.DataFrame,
    indication: str,
    *,
    authority: pd.DataFrame | None = None,
    cells: tuple[str, ...] = CELLS,
    **kwargs,
) -> list[CellConcordance]:
    """Resolve both products once and compute concordance for each cell (A, C)."""
    r, x = resolve_products(recount3_product, xenatoil_product, authority)
    return [concordance_for_cell(r, x, cell, indication, **kwargs) for cell in cells]


# --------------------------------------------------------------------------- #
# discovery — which indications have BOTH substrates, from config intent
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ConcordancePair:
    indication: str
    recount3_id: str
    xenatoil_id: str


def declared_concordance_pairs(intent: dict | None = None) -> list[ConcordancePair]:
    """Every indication whose sensitivity products are declared on BOTH substrates.

    The authoritative declaration is ``config.run_ledger_intent()['sensitivity']``
    (the same roster S5's ledger reconciles), so a concordance pair appears the day
    an indication gains a Xena/Toil sibling — no second list to keep in sync.

    Fail-loud on an EMPTY set: with no declared pair there is nothing to measure and
    the QC would pass vacuously (green-on-empty) — exactly the failure mode #732's
    acceptance forbids.
    """
    from .build_run_ledger import _sensitivity_id

    if intent is None:
        from .config import run_ledger_intent

        intent = run_ledger_intent()
    sens = intent.get("sensitivity", {})
    recount3 = {i.upper() for i in sens.get("recount3", [])}
    xena = {i.upper() for i in sens.get("xena_toil", [])}
    both = sorted(recount3 & xena)
    if not both:
        raise ConcordanceError(
            "no indication declares sensitivity products on BOTH recount3 and xena_toil in "
            "run_ledger_intent — there is nothing to compare. Refusing a vacuous (green-on-empty) "
            "concordance QC."
        )
    return [ConcordancePair(ind, _sensitivity_id(ind, "recount3"), _sensitivity_id(ind, "xena_toil")) for ind in both]


# --------------------------------------------------------------------------- #
# live layer — read products from the catalogued S3 parquet
# --------------------------------------------------------------------------- #
def _real_product_reader(manifest_id: str) -> pd.DataFrame:
    """Read a catalogued sensitivity.parquet into a DataFrame (mirrors build_run_ledger)."""
    import pyarrow.parquet as pq

    from .read import _get_s3fs, _load_manifest, _s3_uri_to_path, ensure_aws_profile

    ensure_aws_profile()
    manifest = _load_manifest(manifest_id)
    s3_uri = manifest.get("s3_uri")
    if not s3_uri:
        raise FileNotFoundError(f"manifest {manifest_id!r} has no s3_uri")
    table = pq.read_table(_s3_uri_to_path(s3_uri), filesystem=_get_s3fs())
    return table.to_pandas()


def _manifest_exists(catalog_root: Path, manifest_id: str) -> bool:
    return (Path(catalog_root) / "manifests" / "derived" / f"{manifest_id}.yaml").exists()


def build_concordance(
    catalog_root: Path,
    *,
    reader=_real_product_reader,
    authority: pd.DataFrame | None = None,
    intent: dict | None = None,
    **kwargs,
) -> tuple[list[CellConcordance], list[str]]:
    """Build concordance rows for every declared substrate pair + reconcile.

    Returns ``(rows, divergences)``. A declared pair whose recount3 OR xenatoil
    manifest is absent from the catalog is a divergence (declared-without-manifest)
    and is skipped for computation — a missing product must SURFACE, not silently
    shrink the comparison set. ``reader(manifest_id) -> DataFrame`` is injectable so
    the pure path is testable offline.
    """
    pairs = declared_concordance_pairs(intent)
    if authority is None:
        from methods.gene_id_authority.loader import load_gene_id_authority

        authority = load_gene_id_authority()

    rows: list[CellConcordance] = []
    divergences: list[str] = []
    for pair in pairs:
        missing = [mid for mid in (pair.recount3_id, pair.xenatoil_id) if not _manifest_exists(catalog_root, mid)]
        if missing:
            divergences.append(f"{pair.indication}: declared concordance pair missing manifest(s) {missing}")
            continue
        r_product = reader(pair.recount3_id)
        x_product = reader(pair.xenatoil_id)
        rows.extend(concordance_for_pair(r_product, x_product, pair.indication, authority=authority, **kwargs))
    return rows, divergences


def _write_report(rows: list[CellConcordance], divergences: list[str], out: Path) -> None:
    payload = {
        "schema_version": "1",
        "reproducibility_only": True,
        "note": (
            "Cross-substrate (recount3 vs Xena/Toil) reproducibility concordance. Measures pipeline "
            "stability on shared raw reads, NOT biological validation. Joined on the stable gene_id "
            "authority, never on HGNC symbol."
        ),
        "n_rows": len(rows),
        "n_divergences": len(divergences),
        "divergences": divergences,
        "rows": [asdict(r) for r in rows],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    from .read import DATA_CATALOG

    ap = argparse.ArgumentParser(description="Build the dge_deseq2 cross-substrate reproducibility concordance QC.")
    ap.add_argument("--out", type=Path, default=Path("concordance.json"), help="Where to write concordance.json.")
    ap.add_argument(
        "--catalog-root",
        type=Path,
        default=DATA_CATALOG,
        help="data-catalog clone root (default: DATA_CATALOG_ROOT env or portable sibling).",
    )
    ap.add_argument(
        "--self-check",
        action="store_true",
        help="Exit non-zero if any declared concordance pair is missing a manifest (reconciliation red).",
    )
    args = ap.parse_args(argv)

    rows, divergences = build_concordance(args.catalog_root)
    _write_report(rows, divergences, args.out)
    print(f"[concordance] wrote {args.out}: {len(rows)} row(s) over {len({r.indication for r in rows})} indication(s)")
    for r in rows:
        print(
            f"  - {r.indication} cell {r.cell}: spearman_rho={r.spearman_rho:.3f} "
            f"(n_gated={r.n_gated}/{r.n_shared_gene_id} shared; {r.n_sign_discordant} sign-discordant)"
        )
    if divergences:
        print(f"[concordance] {len(divergences)} DIVERGENCE(S):", file=sys.stderr)
        for m in divergences:
            print(f"  - {m}", file=sys.stderr)
        if args.self_check:
            return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
