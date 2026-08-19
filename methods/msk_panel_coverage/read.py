"""msk_panel_coverage.read — coverage-correct MSK-CHORD recurrence inputs.

The MSK-CHORD analog of genie_panel_coverage + genie_panel_recurrence's coverage half. MSK-CHORD is
panel-seq (MSK-IMPACT), so per-gene frequency is mutated_covered / n_covered — NEVER mutated / n_total.

Reuses:
  - the MSK-IMPACT panel GENE-LISTS from the GENIE source (genie_panel_coverage.load_panel_gene_sets;
    the GENIE gene_panels/ dir ships data_gene_panel_MSK-IMPACT{341,410,468,505}.txt). The MSK-CHORD
    matrix uses BARE ids (IMPACT468) → normalized to the GENIE MSK-IMPACT468 filename id.
  - the framework % percentile machinery (percentile_null).
The numerator MAF is the derived product msk-chord-per-sample-maf-v1.
"""
from __future__ import annotations

import io
import os
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Optional

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
MSK_PREFIX = "data-catalog/sources/cbioportal/msk_chord_2024"
MSK_CLINICAL_KEY = f"{MSK_PREFIX}/data_clinical_sample.txt"
MSK_PANEL_MATRIX_KEY = f"{MSK_PREFIX}/data_gene_panel_matrix.txt"
MSK_MAF_MANIFEST = "msk-chord-per-sample-maf-v1"
MSK_MAF_LOCAL = Path.home() / ".cache" / "framework-msk-chord-2024"  # {ind}-msk-maf.parquet
_MIN_COVERED = 20

# Framework indication → MSK-CHORD CANCER_TYPE. MSK-CHORD is a 5-tumour cohort (no GC/STAD), so GC is
# deliberately absent — the pool simply omits MSK for indications MSK-CHORD does not carry.
MSK_CANCER_TYPE = {
    "COADREAD": "Colorectal Cancer", "COAD": "Colorectal Cancer", "READ": "Colorectal Cancer",
    "NSCLC": "Non-Small Cell Lung Cancer", "LUAD": "Non-Small Cell Lung Cancer",
    "LUSC": "Non-Small Cell Lung Cancer",
    "PAAD": "Pancreatic Cancer", "PDAC": "Pancreatic Cancer",
    "BRCA": "Breast Cancer", "PRAD": "Prostate Cancer",
}

from methods.target_id_sidecar import ensure_aws_profile


def _s3():
    import boto3
    ensure_aws_profile()
    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")


def _normalize_panel_id(raw: str) -> str:
    """MSK-CHORD matrix uses BARE ids (IMPACT468); the GENIE gene-panel files are MSK-IMPACT468.
    Normalize the bare id to the GENIE filename id so the shared gene-set lookup resolves."""
    p = str(raw).strip()
    if not p:
        return ""
    return p if p.upper().startswith("MSK-") else f"MSK-{p}"


@lru_cache(maxsize=1)
def load_msk_sample_panel_map() -> dict:
    """{SAMPLE_ID: MSK-IMPACT panel id} from data_gene_panel_matrix.txt (the `mutations` assay column).
    Blank = not mutation-profiled → excluded (mirrors genie_panel_coverage). Panel ids normalized."""
    import pandas as pd
    body = _s3().get_object(Bucket=S3_BUCKET, Key=MSK_PANEL_MATRIX_KEY)["Body"].read()
    df = pd.read_csv(io.BytesIO(body), sep="\t", dtype=str)  # plain TSV, no comment lines
    if "SAMPLE_ID" not in df.columns or "mutations" not in df.columns:
        return {}
    out = {}
    for sid, panel in zip(df["SAMPLE_ID"], df["mutations"]):
        norm = _normalize_panel_id(panel) if panel is not None else ""
        if sid and norm:
            out[str(sid)] = norm
    return out


@lru_cache(maxsize=8)
def msk_indication_cohort(indication: str) -> tuple:
    """FULL MSK-CHORD sample cohort (mutated + wild-type) for an indication, from data_clinical_sample.txt
    filtered to the indication's CANCER_TYPE. The denominator universe (NOT the mutated-only MAF)."""
    import pandas as pd
    cancer_type = MSK_CANCER_TYPE.get(str(indication).upper())
    if cancer_type is None:
        return tuple()
    body = _s3().get_object(Bucket=S3_BUCKET, Key=MSK_CLINICAL_KEY)["Body"].read()
    df = pd.read_csv(io.BytesIO(body), sep="\t", comment="#", dtype=str)  # 4 '#' lines then header
    if "CANCER_TYPE" not in df.columns or "SAMPLE_ID" not in df.columns:
        return tuple()
    sel = df[df["CANCER_TYPE"] == cancer_type]["SAMPLE_ID"].dropna().unique()
    return tuple(sel)


@lru_cache(maxsize=8)
def _load_msk_maf(indication: str):
    """MSK-CHORD per-sample MAF for one indication (sample_id, gene_symbol). Local-cache-first then the
    registered product (indication filter). Returns a DataFrame or None (data_unavailable)."""
    import pandas as pd
    ensure_aws_profile()
    local = MSK_MAF_LOCAL / f"{indication.lower()}-msk-maf.parquet"
    if local.exists():
        return pd.read_parquet(local, columns=["sample_id", "gene_symbol"])
    from methods.catalog_query.read import bucket_key_for
    from methods.target_id_sidecar import is_definitively_absent
    try:
        bucket, key = bucket_key_for(MSK_MAF_MANIFEST)
    except Exception as e:  # noqa: BLE001
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise
    import pyarrow.parquet as pq
    import pyarrow.fs as fs
    try:
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=fs.S3FileSystem(),
                            filters=[("indication", "=", indication)],
                            columns=["sample_id", "gene_symbol"])
        return tbl.to_pandas()
    except Exception as e:  # noqa: BLE001
        code = str(getattr(e, "response", {}).get("Error", {}).get("Code", "")) if hasattr(e, "response") else ""
        if code in ("404", "NoSuchKey", "NoSuchBucket") or e.__class__.__name__ in ("NoSuchKey", "FileNotFoundError"):
            return None
        raise


@lru_cache(maxsize=8)
def msk_covered_gene_frequencies(indication: str) -> tuple:
    """Per-gene coverage-correct MSK-CHORD (gene, n_mut, n_cov) for one indication — the MSK analog of
    genie_panel_recurrence._covered_gene_frequencies. n_cov = full-cohort samples whose panel covers the
    gene; n_mut = distinct mutated samples. Empty tuple when MSK does not carry the indication or the MAF
    is unavailable. Genes below _MIN_COVERED are KEPT here (the pooled null decides the floor jointly)."""
    df = _load_msk_maf(indication)
    if df is None or len(df) == 0:
        return tuple()
    from methods.genie_panel_coverage.read import load_panel_gene_sets
    sp = load_msk_sample_panel_map()
    pg = load_panel_gene_sets()
    cohort = [s for s in msk_indication_cohort(indication) if s in sp]
    covered: Counter = Counter()
    for s in cohort:
        for g in pg.get(sp[s], ()):
            covered[g] += 1
    mut = df.groupby("gene_symbol")["sample_id"].nunique().to_dict()
    out = []
    for gene, n_mut in mut.items():
        n_cov = covered.get(gene, 0)
        if n_cov > 0:
            out.append((gene, int(n_mut), int(n_cov)))
    return tuple(out)
