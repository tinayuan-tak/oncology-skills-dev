#!/usr/bin/env python3
"""progeny_pathway_activity — per-indication PROGENy pathway-activity context (Track PROGENy).

A verdict-INERT mechanism-context facet: which of the 14 PROGENy cancer-signaling pathways are
relatively ACTIVE in an indication's TCGA cohort? Upgrades the Mechanism gate from network-topology-
only (SIGNOR/OmniPath edges) to QUANTITATIVE per-indication pathway activity.

PROGENy (Schubert 2018, Apache-2.0) infers pathway activity from a downstream transcriptional
FOOTPRINT (responsive genes), scored with decoupler's MLM against the recount3/TCGA per-sample
log2(TPM+1) already in the catalog. We aggregate to a per-(pathway x indication) rollup at BUILD time
(read grain pre-aggregated → O(1) skill reads).

IMPORTANT framing (see card): PROGENy activity is interpretable RELATIVE to other cohorts, not as an
absolute per-cohort on/off. The product stores per-(pathway x indication) activity so a target's
pathway can be read as high/low RELATIVE to the pan-indication distribution (z-scored across
indications at read time), never as an absolute pathway call.
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import pandas as pd

METHOD_VERSION = "0.1.0"

TOP_GENES_PER_PATHWAY = 100  # standard PROGENy footprint size

# Resolver seam: manifest_ids resolve to their authoritative s3_uri via the data-catalog manifests
# (single source of truth), rather than hand-typed literals that can drift on a re-emit. Resolved at
# call time (not import) so build-time-only code doesn't force the resolver onto pure read/test paths.
MODEL_SOURCE_MANIFEST_ID = "progeny-saezlab-snapshot-2026-08-10"  # s3_uri is a directory → append filename
MODEL_FILENAME = "progeny_model_human.parquet"
EXPR_MANIFEST_ID = "tcga-tumor-tpm-recount3-long-v1"


def _resolve_model_uri() -> str:
    from methods.catalog_query.read import s3_uri_for

    base = s3_uri_for(MODEL_SOURCE_MANIFEST_ID)  # ends in '/' (source-release directory)
    return base + MODEL_FILENAME if base.endswith("/") else f"{base}/{MODEL_FILENAME}"


def _resolve_expr_uri() -> str:
    from methods.catalog_query.read import s3_uri_for

    return s3_uri_for(EXPR_MANIFEST_ID)


# indication → recount3 TCGA study codes (mirror tcga_gtex_expression_distribution.INDICATION_TO_TCGA_STUDIES).
INDICATION_TO_STUDIES = {
    "ACC": ["ACC"],
    "BLCA": ["BLCA"],
    "BRCA": ["BRCA"],
    "CESC": ["CESC"],
    "CHOL": ["CHOL"],
    "COAD": ["COAD"],
    "READ": ["READ"],
    "COADREAD": ["COAD", "READ"],
    "DLBC": ["DLBC"],
    "ESCA": ["ESCA"],
    "GBM": ["GBM"],
    "HNSC": ["HNSC"],
    "KICH": ["KICH"],
    "KIRC": ["KIRC"],
    "KIRP": ["KIRP"],
    "LGG": ["LGG"],
    "LIHC": ["LIHC"],
    "LUAD": ["LUAD"],
    "LUSC": ["LUSC"],
    "NSCLC": ["LUAD", "LUSC"],
    "MESO": ["MESO"],
    "OV": ["OV"],
    "PAAD": ["PAAD"],
    "PCPG": ["PCPG"],
    "PRAD": ["PRAD"],
    "SARC": ["SARC"],
    "SKCM": ["SKCM"],
    "STAD": ["STAD"],
    "GC": ["STAD"],
    "TGCT": ["TGCT"],
    "THCA": ["THCA"],
    "THYM": ["THYM"],
    "UCEC": ["UCEC"],
    "UCS": ["UCS"],
    "UVM": ["UVM"],
}
# The per-indication build set = the single-study TCGA indications (composites like COADREAD/NSCLC are
# resolved at READ time by pooling their member studies, mirroring the DDR reader's alias-pooling).
_BUILD_INDICATIONS = [k for k, v in INDICATION_TO_STUDIES.items() if len(v) == 1]


def _load_model(top_n: int = TOP_GENES_PER_PATHWAY):
    import subprocess

    raw = subprocess.run(["aws", "s3", "cp", _resolve_model_uri(), "-"], capture_output=True).stdout
    prog = pd.read_parquet(io.BytesIO(raw))
    prog["abw"] = prog["weight"].abs()
    top = prog.sort_values("abw", ascending=False).groupby("pathway").head(top_n)
    return top.rename(columns={"pathway": "source", "gene_symbol": "target"})[["source", "target", "weight"]]


def _duck():
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs;LOAD httpfs;")
    con.execute("CREATE SECRET s (TYPE s3, PROVIDER credential_chain, REGION 'us-east-1');")
    return con


def build_per_indication_table(top_n: int = TOP_GENES_PER_PATHWAY) -> pd.DataFrame:
    """Score PROGENy activity per TCGA sample, aggregate to per-(pathway x indication) MEDIAN activity.

    Returns long DataFrame [indication, pathway, n_samples, median_activity, p25_activity, p75_activity].
    Composite indications (COADREAD/NSCLC) are NOT stored — the reader pools member studies.
    """
    import decoupler as dc

    net = _load_model(top_n)
    genes = sorted(net["target"].unique())
    con = _duck()
    expr_uri = _resolve_expr_uri()
    glist = "','".join(g.replace("'", "''") for g in genes)
    rows = []
    for ind in _BUILD_INDICATIONS:
        study = INDICATION_TO_STUDIES[ind][0]
        q = (
            f"SELECT gene_symbol, sample_id, log2_tpm FROM read_parquet('{expr_uri}') "
            f"WHERE study = '{study}' AND gene_symbol IN ('{glist}')"
        )
        expr = con.execute(q).df()
        if expr.empty or expr["sample_id"].nunique() < 15:
            continue
        mat = expr.pivot_table(index="sample_id", columns="gene_symbol", values="log2_tpm", aggfunc="mean").fillna(0.0)
        acts = dc.mt.mlm(data=mat, net=net)
        sc = acts[0] if isinstance(acts, tuple) else acts
        sc = sc if isinstance(sc, pd.DataFrame) else pd.DataFrame(sc, index=mat.index)
        for pathway in sc.columns:
            col = sc[pathway].dropna()
            rows.append(
                {
                    "indication": ind,
                    "pathway": str(pathway),
                    "n_samples": int(len(col)),
                    "median_activity": round(float(col.median()), 4),
                    "p25_activity": round(float(col.quantile(0.25)), 4),
                    "p75_activity": round(float(col.quantile(0.75)), 4),
                }
            )
    df = pd.DataFrame(rows)
    # cross-indication z-score per pathway → the RELATIVE activity the card reads (honest framing).
    if not df.empty:
        df["activity_z_across_indications"] = df.groupby("pathway")["median_activity"].transform(
            lambda s: ((s - s.mean()) / s.std(ddof=0)).round(4) if s.std(ddof=0) > 0 else 0.0
        )
    return df.sort_values(["pathway", "indication"]).reset_index(drop=True)


try:
    import click

    @click.command()
    @click.option("--out", type=click.Path(path_type=Path), required=True)
    @click.option("--top-n", default=TOP_GENES_PER_PATHWAY)
    def main(out, top_n):
        """Build the per-(pathway x indication) PROGENy activity product."""
        t0 = time.time()
        tbl = build_per_indication_table(top_n)
        out.parent.mkdir(parents=True, exist_ok=True)
        tbl.to_parquet(out, index=False)
        click.echo(
            f"wrote {len(tbl)} (pathway x indication) rows, "
            f"{tbl['indication'].nunique()} indications x {tbl['pathway'].nunique()} pathways "
            f"in {time.time() - t0:.0f}s -> {out}"
        )

    if __name__ == "__main__":
        main()
except ImportError:
    pass
