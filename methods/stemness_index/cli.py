#!/usr/bin/env python3
"""stemness_index — per-indication mRNAsi tumor-stemness context (Malta 2018, REIMPLEMENTED).

A verdict-INERT cohort-context facet: how stem-like / dedifferentiated is an indication's TCGA cohort?
High stemness (mRNAsi) tracks dedifferentiation, and is associated with aggressiveness/worse outcome —
a prognostic/aggressiveness cohort prior.

REIMPLEMENTATION NOTE (important, carried into the card): Malta et al. 2018 do NOT distribute the
per-sample mRNAsi scores as a file (confirmed via the GDC PanCan-Stemness open manifest — only the
signature WEIGHTS + PSEA enrichment ship). So we REIMPLEMENT their one-class scoring: per sample,
Spearman correlation between the sample's expression profile and the mRNAsi signature weights (the
12,945-gene RNA-expression stemness signature), then min-max scaled to [0,1] PAN-CANCER (across all
TCGA samples together — NOT per-cohort, so cross-indication comparison is meaningful). This is the
Malta method applied to recount3/TCGA; the values are a faithful reimplementation, NOT the exact
published per-sample table.

BUILD: score all single-study TCGA indications together, pan-cancer min-max once, roll up to
per-(indication) median + quartiles + a stemness class relative to the pan-cancer distribution.
"""
from __future__ import annotations

import io
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

METHOD_VERSION = "0.1.0"

_SIG_S3 = ("s3://onc-compbio/data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27/"
           "DNAmethylation_and_RNAexpression_Stemness_Signatures.xlsx")
_EXPR_S3 = "s3://onc-compbio/data-catalog/derived/tcga-tumor-tpm-recount3-long-v1/tcga_tpm_long.parquet"

# indication → single TCGA study (composites pooled at read time), mirror the other methods.
INDICATION_TO_STUDIES = {
    "ACC": ["ACC"], "BLCA": ["BLCA"], "BRCA": ["BRCA"], "CESC": ["CESC"], "CHOL": ["CHOL"],
    "COAD": ["COAD"], "READ": ["READ"], "DLBC": ["DLBC"], "ESCA": ["ESCA"], "GBM": ["GBM"],
    "HNSC": ["HNSC"], "KICH": ["KICH"], "KIRC": ["KIRC"], "KIRP": ["KIRP"], "LGG": ["LGG"],
    "LIHC": ["LIHC"], "LUAD": ["LUAD"], "LUSC": ["LUSC"], "MESO": ["MESO"], "OV": ["OV"],
    "PAAD": ["PAAD"], "PCPG": ["PCPG"], "PRAD": ["PRAD"], "SARC": ["SARC"], "SKCM": ["SKCM"],
    "STAD": ["STAD"], "TGCT": ["TGCT"], "THCA": ["THCA"], "THYM": ["THYM"], "UCEC": ["UCEC"],
    "UCS": ["UCS"], "UVM": ["UVM"],
    # composites resolved at READ time
    "COADREAD": ["COAD", "READ"], "NSCLC": ["LUAD", "LUSC"], "GC": ["STAD"], "PDAC": ["PAAD"],
}
_BUILD_INDICATIONS = [k for k, v in INDICATION_TO_STUDIES.items() if len(v) == 1]
MIN_COHORT_N = 15


def _load_mrnasi_signature() -> pd.Series:
    """{gene_symbol -> weight} for the mRNAsi RNA-expression stemness signature (Malta 2018)."""
    raw = subprocess.run(["aws", "s3", "cp", _SIG_S3, "-"], capture_output=True).stdout
    sig = pd.read_excel(io.BytesIO(raw), sheet_name="mRNAsi", header=0)
    sig.columns = ["ensembl", "hugo", "weight"][: sig.shape[1]]
    sig["weight"] = pd.to_numeric(sig["weight"], errors="coerce")
    sig = sig.dropna(subset=["weight", "hugo"])
    return sig.set_index("hugo")["weight"]


def _duck():
    import duckdb
    con = duckdb.connect()
    con.execute("INSTALL httpfs;LOAD httpfs;")
    con.execute("CREATE SECRET s (TYPE s3, PROVIDER credential_chain, REGION 'us-east-1');")
    return con


def build_per_indication_table() -> pd.DataFrame:
    """Score mRNAsi per sample (Spearman corr vs signature), PAN-CANCER min-max, roll up per-indication.

    Returns [indication, n_samples, median_mrnasi, p25_mrnasi, p75_mrnasi, stemness_class].
    """
    from scipy.stats import spearmanr
    w = _load_mrnasi_signature()
    genes = sorted(w.index.unique())
    con = _duck()
    gl = "','".join(g.replace("'", "''") for g in genes)
    studies = [INDICATION_TO_STUDIES[i][0] for i in _BUILD_INDICATIONS]
    sl = "','".join(studies)
    q = (f"SELECT study, gene_symbol, sample_id, log2_tpm FROM read_parquet('{_EXPR_S3}') "
         f"WHERE study IN ('{sl}') AND gene_symbol IN ('{gl}')")
    expr = con.execute(q).df()
    # per-sample Spearman corr(expression, weight) over shared genes
    per_sample = []  # (study, sample_id, raw_corr)
    for (study, sid), g in expr.groupby(["study", "sample_id"]):
        shared = g[g["gene_symbol"].isin(w.index)]
        if len(shared) < 100:
            continue
        rho, _ = spearmanr(shared["log2_tpm"].values, w[shared["gene_symbol"]].values, nan_policy="omit")
        if rho == rho:  # not NaN
            per_sample.append((study, sid, float(rho)))
    ps = pd.DataFrame(per_sample, columns=["study", "sample_id", "raw_corr"])
    if ps.empty:
        return pd.DataFrame()
    # PAN-CANCER min-max → mRNAsi in [0,1] (cross-indication comparable)
    lo, hi = ps["raw_corr"].min(), ps["raw_corr"].max()
    ps["mrnasi"] = (ps["raw_corr"] - lo) / (hi - lo) if hi > lo else 0.5
    pan_median = ps["mrnasi"].median()
    pan_q3 = ps["mrnasi"].quantile(0.75)
    rows = []
    for study, g in ps.groupby("study"):
        if len(g) < MIN_COHORT_N:
            continue
        med = float(g["mrnasi"].median())
        rows.append({
            "indication": study, "n_samples": int(len(g)),
            "median_mrnasi": round(med, 4),
            "p25_mrnasi": round(float(g["mrnasi"].quantile(0.25)), 4),
            "p75_mrnasi": round(float(g["mrnasi"].quantile(0.75)), 4),
            # class RELATIVE to the pan-cancer distribution (cross-cohort meaningful)
            "stemness_class": ("stem_high" if med >= pan_q3
                               else "stem_low" if med < pan_median else "stem_intermediate"),
        })
    df = pd.DataFrame(rows)
    df["pan_cancer_median_mrnasi"] = round(float(pan_median), 4)
    df["pan_cancer_q3_mrnasi"] = round(float(pan_q3), 4)
    return df.sort_values("indication").reset_index(drop=True)


try:
    import click

    @click.command()
    @click.option("--out", type=click.Path(path_type=Path), required=True)
    def main(out):
        tbl = build_per_indication_table()
        out.parent.mkdir(parents=True, exist_ok=True)
        tbl.to_parquet(out, index=False)
        click.echo(f"wrote {len(tbl)} indications -> {out}")

    if __name__ == "__main__":
        main()
except ImportError:
    pass
