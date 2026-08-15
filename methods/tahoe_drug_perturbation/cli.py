"""tahoe_drug_perturbation.cli — S3 pushdown + per-target aggregation for the Tahoe facet.

Reads the gene-keyed derived product tahoe-drug-perturbation-per-gene-v1 (Tahoe-100M single-cell
drug-perturbation atlas; 192.5M significant DE rows across 48,681 genes x 379 drugs x 50 cancer
cell lines, padj<0.25). For a target gene, returns: which small molecules most strongly MOVE the
gene's expression (up and down), in how many cancer lines, with what significance — a MECHANISM /
MoA / pharmacodynamic-response facet (VERDICT-INERT; perturbation != dependency).

Pushdown on gene_name (the product sort key) touches only matching row-groups — a per-target read is
a few MB, never the 5.3 GB product. NO scanpy/anndata; pyarrow + the cbg S3 profile only.
"""
from __future__ import annotations

import os
from typing import Optional

PRODUCT_MANIFEST_ID = "tahoe-drug-perturbation-per-gene-v1"
METHOD_VERSION = "0.1.0"

DEFAULT_AWS_PROFILE = "cbg"

# Card-side thresholds. The product is pre-filtered to padj<0.25 (discovery FDR); the card applies a
# stricter significance gate and an effect-size floor for the "strong mover" summary.
PADJ_STRICT = 0.05
STRONG_ABS_LFC = 1.0     # |log2FC| >= 1 (2-fold) = a strong transcriptional move
TOP_N = 15


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    body = uri[len("s3://"):]
    bucket, _, key = body.partition("/")
    return bucket, key


def fetch_gene_rows(target: str):
    """Pushdown-read all Tahoe DE rows for one gene_name. Returns a pandas DataFrame (possibly
    empty) or None on read failure."""
    import pyarrow.parquet as pq
    import pyarrow.fs as pafs
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
        from methods.catalog_query.read import bucket_key_for
        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=pafs.S3FileSystem(),
                            filters=[("gene_name", "=", (target or "").strip())])
    except Exception:  # absence-discipline: exempt -- None → compute_summary emits _live_read_error breadcrumb (tahoe_drug_perturbation_read_failed), not a silent dead axis
        return None
    return tbl.to_pandas()


def compute_summary(df, target: str) -> dict:
    """Aggregate per-gene Tahoe DE rows into a per-target MoA facet summary.

    df: pandas DataFrame of rows for ONE gene (cols: drug, Cell_ID_DepMap, concentration,
        log2FoldChange, padj, stat, baseMean, ...). None => read failure. Empty => gene absent.
    """
    import numpy as np
    import pandas as pd

    if df is None:
        return {
            "tahoe_perturbation_class": "data_unavailable",
            "_live_read_error": "tahoe_drug_perturbation_read_failed",
            "method_version": METHOD_VERSION,
            "_data_source": PRODUCT_MANIFEST_ID,
        }
    if len(df) == 0:
        return {
            "tahoe_perturbation_class": "not_measured",
            "n_perturbing_drugs": 0,
            "n_cancer_lines": 0,
            "top_suppressing_drugs": [],
            "top_inducing_drugs": [],
            "perturbation_context": (f"{target}: not present in the Tahoe drug-perturbation product "
                                     f"(no significant DE row at padj<0.25; may be an ncRNA/"
                                     f"pseudogene absent from the resolved set, or genuinely "
                                     f"unmoved). A coverage/measurement gap, not a mechanism claim."),
            "method_version": METHOD_VERSION,
            "_data_source": PRODUCT_MANIFEST_ID,
        }

    # per-drug aggregate across all lines/doses: median log2FC + how many (line,dose) groups, and
    # how many are strictly significant.
    df = df.copy()
    df["_sig"] = df["padj"] < PADJ_STRICT
    grp = df.groupby("drug").agg(
        median_l2fc=("log2FoldChange", "median"),
        n_obs=("log2FoldChange", "size"),
        n_lines=("Cell_ID_DepMap", "nunique"),
        n_sig=("_sig", "sum"),
    ).reset_index()

    n_drugs = int(grp.shape[0])
    n_lines = int(df["Cell_ID_DepMap"].nunique())

    def _records(sub, sign):
        out = []
        for _, r in sub.iterrows():
            out.append({
                "drug": r["drug"],
                "median_log2FoldChange": round(float(r["median_l2fc"]), 4),
                "n_observations": int(r["n_obs"]),
                "n_cancer_lines": int(r["n_lines"]),
                "n_significant_strict": int(r["n_sig"]),
                "direction": "suppresses" if sign < 0 else "induces",
            })
        return out

    suppressors = grp[grp["median_l2fc"] <= -STRONG_ABS_LFC].sort_values("median_l2fc").head(TOP_N)
    inducers = grp[grp["median_l2fc"] >= STRONG_ABS_LFC].sort_values("median_l2fc", ascending=False).head(TOP_N)

    n_strong = int(suppressors.shape[0] + inducers.shape[0])
    if n_strong == 0:
        klass = "weakly_perturbed"        # measured, but no drug moves it >=2-fold (median)
    elif suppressors.shape[0] and inducers.shape[0]:
        klass = "bidirectionally_perturbed"
    elif suppressors.shape[0]:
        klass = "drug_suppressed"
    else:
        klass = "drug_induced"

    top_supp = _records(suppressors, -1)
    top_ind = _records(inducers, +1)
    strongest = None
    if top_supp or top_ind:
        cand = (top_supp[:1] + top_ind[:1])
        strongest = min(cand, key=lambda r: r["median_log2FoldChange"]) if top_supp else cand[0]

    ctx = _context(target, klass, strongest, n_drugs, n_lines, top_supp, top_ind)
    return {
        "tahoe_perturbation_class": klass,
        "n_perturbing_drugs": n_drugs,
        "n_cancer_lines": n_lines,
        "n_strong_movers": n_strong,
        "strongest_mover_drug": (strongest or {}).get("drug"),
        "strongest_mover_log2fc": (strongest or {}).get("median_log2FoldChange"),
        "top_suppressing_drugs": top_supp,
        "top_inducing_drugs": top_ind,
        "perturbation_context": ctx,
        "method_version": METHOD_VERSION,
        "_data_source": PRODUCT_MANIFEST_ID,
    }


def _context(target, klass, strongest, n_drugs, n_lines, top_supp, top_ind) -> str:
    if klass == "weakly_perturbed":
        return (f"{target}: measured in Tahoe across {n_drugs} drugs / {n_lines} cancer lines, but no "
                f"drug moves its expression >=2-fold (median). Transcriptionally stable under the "
                f"screened perturbations.")
    head = f"{target}: perturbed by {n_drugs} drugs across {n_lines} cancer lines (Tahoe single-cell)."
    if top_supp:
        s = top_supp[0]
        head += (f" Most SUPPRESSED by {s['drug']} (median log2FC {s['median_log2FoldChange']}, "
                 f"{s['n_cancer_lines']} lines).")
    if top_ind:
        i = top_ind[0]
        head += (f" Most INDUCED by {i['drug']} (median log2FC {i['median_log2FoldChange']}, "
                 f"{i['n_cancer_lines']} lines).")
    head += " MECHANISM / MoA facet (verdict-inert) — a transcriptional-response signal, NOT dependency."
    return head


def build_summary(target: str, indication: Optional[str] = None) -> dict:
    """Public entry — per-target Tahoe drug-perturbation MoA facet. `indication` accepted for the
    CARD_DISPATCHERS contract but NOT consumed (the product is gene-keyed / pan-cancer)."""
    _ensure_aws_profile()
    df = fetch_gene_rows(target)
    return compute_summary(df, (target or "").strip())
