"""genie_panel_recurrence.read — coverage-correct GENIE recurrence + percentile.

Fuses the GENIE per-sample MAF (genie-registry-per-sample-maf-v1) with the genie_panel_coverage
denominator. The load-bearing correctness point: GENIE is panel-seq, so per-gene frequency is
mutated_covered / n_covered (samples whose panel covers the gene), NEVER mutated / n_total.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

DEFAULT_AWS_PROFILE = "cbg"
GENIE_MAF_MANIFEST = "genie-registry-per-sample-maf-v1"
GENIE_MAF_LOCAL = Path.home() / ".cache" / "framework-genie-public-v19"  # {ind}-genie-maf.parquet
# The clinical-sample table gives the FULL indication cohort (mutated + wild-type). The MAF lists
# only MUTATED samples, so it CANNOT supply the denominator — a coverage denominator drawn from the
# MAF would under-count to only-mutated samples (inflating frequency). The honest cohort is every
# GENIE sample of the indication's CANCER_TYPE, mutated or not.
GENIE_CLINICAL_KEY = "data-catalog/sources/synapse/genie-public-v19-0/data_clinical_sample.txt"
# Framework indication → GENIE CANCER_TYPE (same map the MAF builder uses; coarser than TCGA).
GENIE_CANCER_TYPE = {
    "COADREAD": "Colorectal Cancer", "NSCLC": "Non-Small Cell Lung Cancer",
    "PAAD": "Pancreatic Cancer", "PDAC": "Pancreatic Cancer", "GC": "Esophagogastric Cancer",
}
# Cutoffs mirror the MC3 driver-recurrence + tumor-presence allgene percentile classes.
DEFAULT_CUTOFFS = {"top_1pct": 99.0, "top_decile": 90.0, "bottom_decile": 10.0}
# A gene must be covered on a MINIMUM number of samples for its frequency to be trustworthy;
# below this the percentile is emitted None (coverage too thin to rank), distinct from a gap.
_MIN_COVERED = 20

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # methods/ on path for siblings


from methods.target_id_sidecar import ensure_aws_profile


@lru_cache(maxsize=8)
def _load_genie_maf(indication: str):
    """The GENIE per-sample MAF for one indication (sample_id, gene_symbol[, protein_change]).
    Local-cache-first ({ind}-genie-maf.parquet) then the registered pan-indication product
    (filter indication). Returns a pandas DataFrame or None."""
    import pandas as pd
    ensure_aws_profile()
    local = GENIE_MAF_LOCAL / f"{indication.lower()}-genie-maf.parquet"
    if local.exists():
        df = pd.read_parquet(local, columns=["sample_id", "gene_symbol"])
        return df
    # S3 fallback: the pan-indication product, filtered to this indication.
    from methods.catalog_query.read import bucket_key_for  # resolver helper (Stage-1 adoption)
    try:
        bucket, key = bucket_key_for(GENIE_MAF_MANIFEST)
    except Exception as e:
        # A genuinely-missing manifest → None (data_unavailable). A broken resolver / broken env must
        # NOT be masked as a coverage gap — re-raise so the seam surfaces _live_read_error. (The pq
        # read below is already hardened with its own discriminant.)
        from methods.target_id_sidecar import is_definitively_absent
        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        return None
    import pyarrow.parquet as pq
    import pyarrow.fs as fs
    try:
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=fs.S3FileSystem(),
                            filters=[("indication", "=", indication)],
                            columns=["sample_id", "gene_symbol"])
        return tbl.to_pandas()
    except Exception as e:  # noqa: BLE001
        # DEFINITIVE absence (object not there) → None (caller renders data_unavailable). A
        # TRANSIENT/AUTH failure must NOT be masked as a coverage gap (bare-except-masks-broken-env);
        # re-raise it. Mirrors tcga_fusion_consensus/read.py's discriminant.
        code = str(getattr(e, "response", {}).get("Error", {}).get("Code", "")) if hasattr(e, "response") else ""
        if code in ("404", "NoSuchKey", "NoSuchBucket") or e.__class__.__name__ in ("NoSuchKey", "FileNotFoundError"):
            return None
        raise


@lru_cache(maxsize=8)
def _indication_cohort(indication: str) -> tuple:
    """The FULL GENIE sample cohort for an indication (mutated + wild-type) from
    data_clinical_sample.txt filtered to the indication's CANCER_TYPE. This is the denominator
    universe — NOT the MAF (which lists only mutated samples). Returns a tuple of sample_ids."""
    import pandas as pd
    ensure_aws_profile()
    cancer_type = GENIE_CANCER_TYPE.get(indication)
    if cancer_type is None:
        return tuple()
    import boto3
    s3 = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")
    import io
    body = s3.get_object(Bucket="onc-compbio", Key=GENIE_CLINICAL_KEY)["Body"].read()
    # cBioPortal clinical files have 4 '#'-prefixed header lines then the real header row.
    df = pd.read_csv(io.BytesIO(body), sep="\t", comment="#", dtype=str)
    if "CANCER_TYPE" not in df.columns or "SAMPLE_ID" not in df.columns:
        return tuple()
    sel = df[df["CANCER_TYPE"] == cancer_type]["SAMPLE_ID"].dropna().unique()
    return tuple(sel)


def _percentile(value, null_vec, cutoffs=None):
    from methods.percentile_null import percentile_rank, classify_percentile
    pct = percentile_rank(value, null_vec)
    return pct, classify_percentile(pct, cutoffs or DEFAULT_CUTOFFS)


@lru_cache(maxsize=8)
def _covered_gene_frequencies(indication: str) -> tuple:
    """All-covered-gene coverage-correct frequencies for one indication — the recurrence
    null. For each gene mutated in the GENIE MAF: freq = n_mutated / n_covered, where
    n_covered = samples in this indication whose panel covers the gene (genie_panel_coverage).
    Genes with n_covered < _MIN_COVERED are excluded from the null (too thin to rank).
    Returns a tuple of (gene, freq, n_covered, n_mutated) — hashable/cache-safe."""
    from methods.genie_panel_coverage.read import load_sample_panel_map, load_panel_gene_sets
    df = _load_genie_maf(indication)
    if df is None or len(df) == 0:
        return tuple()
    sp = load_sample_panel_map()
    pg = load_panel_gene_sets()
    # DENOMINATOR universe = the FULL indication cohort (mutated + wild-type) from clinical, NOT the
    # MAF's mutated-only samples. n_covered per gene = full-cohort samples whose panel covers it.
    cohort = [s for s in _indication_cohort(indication) if s in sp]
    from collections import Counter
    covered = Counter()
    for s in cohort:
        for g in pg.get(sp[s], ()):
            covered[g] += 1
    # NUMERATOR = mutated cases per gene (dedup sample_id) from the MAF.
    mut = df.groupby("gene_symbol")["sample_id"].nunique().to_dict()
    out = []
    for gene, n_mut in mut.items():
        n_cov = covered.get(gene, 0)
        if n_cov < _MIN_COVERED:
            continue
        out.append((gene, n_mut / n_cov, n_cov, n_mut))
    return tuple(out)


def genie_recurrence_for_gene(target: str, indication: str, cutoffs: dict = None) -> dict:
    """Coverage-correct GENIE recurrence for one (target, indication). The GENIE (higher-N)
    complement to MC3's driver_recurrence_*; a DISPLAY facet (verdict-inert).

    Returns genie_mutation_frequency (n_mut/n_covered), n_covered, n_mutated,
    genie_driver_recurrence_percentile + _class, coverage_gap, and a context string.
    coverage_gap=True (n_covered==0 → gene on no panel) → percentile None, class data_unavailable
    (NOT frequency 0). n_covered below the min → percentile None (too thin to rank), freq still emitted.
    """
    from methods.genie_panel_coverage.read import load_sample_panel_map, load_panel_gene_sets
    df = _load_genie_maf(indication)
    if df is None:
        return {"genie_driver_recurrence_class": "data_unavailable",
                "genie_driver_recurrence_percentile": None, "genie_mutation_frequency": None,
                "n_covered": None, "n_mutated": None, "coverage_gap": None,
                "genie_recurrence_context": f"no GENIE MAF for {indication}"}
    sp = load_sample_panel_map()
    pg = load_panel_gene_sets()
    # n_cov over the FULL indication cohort (clinical), NOT the mutated-only MAF samples.
    cohort = [s for s in _indication_cohort(indication) if s in sp]
    n_cov = sum(1 for s in cohort if target in pg.get(sp[s], frozenset()))
    n_mut = int(df[df["gene_symbol"] == target]["sample_id"].nunique())

    if n_cov == 0:
        return {"genie_driver_recurrence_class": "data_unavailable",
                "genie_driver_recurrence_percentile": None, "genie_mutation_frequency": None,
                "n_covered": 0, "n_mutated": n_mut, "coverage_gap": True,
                "genie_recurrence_context": (
                    f"{target} on NO GENIE panel in {indication} (coverage gap — not a real 0%)")}

    freq = n_mut / n_cov
    null = _covered_gene_frequencies(indication)
    null_vec = tuple(f for _g, f, _nc, _nm in null)
    if n_cov < _MIN_COVERED or not null_vec:
        pct, cls = None, "data_unavailable"
        note = f"{target} covered on only {n_cov} GENIE {indication} samples (< {_MIN_COVERED}; too thin to rank)"
    else:
        pct, cls = _percentile(freq, null_vec, cutoffs)
        note = (f"among {len(null_vec)} panel-covered genes in {indication} "
                f"(GENIE registry, coverage-corrected denominator)")
    return {
        "genie_mutation_frequency": freq,
        "n_covered": n_cov,
        "n_mutated": n_mut,
        "genie_driver_recurrence_percentile": pct,
        "genie_driver_recurrence_class": cls,
        "coverage_gap": False,
        "genie_recurrence_context": note,
    }


def build_genie_recurrence_table(indication: str):
    """Materialize the per-gene coverage-correct GENIE recurrence table for an indication
    (for a registered derived product). One row per covered+mutated gene."""
    import pyarrow as pa
    null = _covered_gene_frequencies(indication)
    if not null:
        return pa.Table.from_pylist([], schema=_schema())
    null_vec = tuple(f for _g, f, _nc, _nm in null)
    rows = []
    for gene, freq, n_cov, n_mut in null:
        pct, cls = _percentile(freq, null_vec)
        rows.append({"indication": indication, "gene_symbol": gene,
                     "n_covered": n_cov, "n_mutated": n_mut,
                     "genie_mutation_frequency": freq,
                     "genie_driver_recurrence_percentile": pct,
                     "genie_driver_recurrence_class": cls})
    rows.sort(key=lambda r: (r["gene_symbol"],))
    return pa.Table.from_pylist(rows, schema=_schema())


def _schema():
    import pyarrow as pa
    return pa.schema([
        pa.field("indication", pa.string()), pa.field("gene_symbol", pa.string()),
        pa.field("n_covered", pa.int64()), pa.field("n_mutated", pa.int64()),
        pa.field("genie_mutation_frequency", pa.float64()),
        pa.field("genie_driver_recurrence_percentile", pa.float64()),
        pa.field("genie_driver_recurrence_class", pa.string()),
    ])
