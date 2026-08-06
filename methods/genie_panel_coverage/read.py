"""genie_panel_coverage.read — the coverage-denominator lookup + producer.

Consumers (GENIE mutation-frequency readers, the LOT panorama) call:
  - load_sample_panel_map()      → {sample_id: panel_id}   (from data_gene_matrix.txt)
  - load_panel_gene_sets()       → {panel_id: frozenset(genes)}  (from 166 panel files)
  - covered(sample, gene, ...)   → bool
  - n_covered_samples(gene, sample_ids, ...) → int  (the honest denominator)
  - panel_coverage_denominator(gene, sample_ids, ...) → dict with n_covered + n_total + n_uncovered

Both maps are @lru_cache'd module-level (166 panels + 271k samples ≈ a few MB resident),
so the per-(gene, sample_set) denominator is a dict scan over the sample set — no
per-(sample,gene) materialization.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
GENIE_PREFIX = "data-catalog/sources/synapse/genie-public-v19-0"
GENE_MATRIX_KEY = f"{GENIE_PREFIX}/data_gene_matrix.txt"
PANEL_DIR_PREFIX = f"{GENIE_PREFIX}/gene_panels/"

# The gene_matrix `mutations` column names the panel that assayed a sample's SNVs.
# A blank value = the sample was not mutation-profiled → it has NO SNV coverage for
# any gene (excluded from every mutation denominator).
_MUTATIONS_PANEL_COLUMN = "mutations"


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _boto3_client():
    import boto3
    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")


def _parse_gene_panel_file(text: str) -> list[str]:
    """Parse a GENIE data_gene_panel_<ID>.txt: the `gene_list:` line carries the
    whitespace-separated HGNC symbols. (Mirrors cooccurrence_fisher_pancohort's
    01_panel_intersect._parse_gene_panel_file — kept local so this primitive has no
    cross-method step-script import.)"""
    genes: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("gene_list:"):
            genes.extend(line.split(":", 1)[1].strip().split())
    return genes


@lru_cache(maxsize=1)
def load_panel_gene_sets(genie_prefix: str = GENIE_PREFIX) -> dict:
    """{panel_id: frozenset(gene_symbol)} for all 166 GENIE panels. Cached once."""
    _ensure_aws_profile()
    s3 = _boto3_client()
    prefix = f"{genie_prefix}/gene_panels/"
    out: dict[str, frozenset] = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            if not k.endswith(".txt"):
                continue
            panel_id = Path(k).name.replace("data_gene_panel_", "").replace(".txt", "")
            text = s3.get_object(Bucket=S3_BUCKET, Key=k)["Body"].read().decode("utf-8", errors="replace")
            out[panel_id] = frozenset(_parse_gene_panel_file(text))
    return out


@lru_cache(maxsize=1)
def load_sample_panel_map(genie_prefix: str = GENIE_PREFIX) -> dict:
    """{sample_id: panel_id} from data_gene_matrix.txt `mutations` column.
    Samples with a blank mutations-panel (not SNV-profiled) are OMITTED — they carry
    no mutation coverage for any gene and must not enter a denominator. Cached once."""
    import pandas as pd
    _ensure_aws_profile()
    s3 = _boto3_client()
    body = s3.get_object(Bucket=S3_BUCKET, Key=GENE_MATRIX_KEY)["Body"]
    df = pd.read_csv(body, sep="\t", dtype=str)
    # SAMPLE_ID + mutations columns; drop rows with no mutation panel.
    df = df[["SAMPLE_ID", _MUTATIONS_PANEL_COLUMN]].dropna(subset=[_MUTATIONS_PANEL_COLUMN])
    df = df[df[_MUTATIONS_PANEL_COLUMN].str.strip() != ""]
    return dict(zip(df["SAMPLE_ID"], df[_MUTATIONS_PANEL_COLUMN]))


def covered(sample_id: str, gene: str,
            sample_panel: Optional[dict] = None,
            panel_genes: Optional[dict] = None) -> bool:
    """True iff the panel that assayed `sample_id`'s SNVs covers `gene`. A sample not
    in the gene-matrix (no mutation panel) is NOT covered (returns False)."""
    sp = sample_panel if sample_panel is not None else load_sample_panel_map()
    pg = panel_genes if panel_genes is not None else load_panel_gene_sets()
    panel = sp.get(sample_id)
    if panel is None:
        return False
    return gene in pg.get(panel, frozenset())


def n_covered_samples(gene: str, sample_ids: Iterable[str],
                      sample_panel: Optional[dict] = None,
                      panel_genes: Optional[dict] = None) -> int:
    """The HONEST denominator: how many of `sample_ids` were sequenced on a panel
    that covers `gene`. This is what a GENIE mutation frequency divides by — NOT the
    raw sample count (which conflates wild-type with not-sequenced)."""
    sp = sample_panel if sample_panel is not None else load_sample_panel_map()
    pg = panel_genes if panel_genes is not None else load_panel_gene_sets()
    return sum(1 for s in sample_ids if gene in pg.get(sp.get(s, ""), frozenset()))


def panel_coverage_denominator(gene: str, sample_ids: Iterable[str],
                               sample_panel: Optional[dict] = None,
                               panel_genes: Optional[dict] = None) -> dict:
    """Full coverage breakdown for (gene, sample_set): the honest denominator plus the
    total and the uncovered count, so a caller can emit `data_unavailable`/coverage-gap
    (gene on NO panel in the set) rather than a misleading frequency ≈ 0.

    Returns {n_total, n_covered, n_uncovered, coverage_fraction}. n_covered==0 means the
    gene is on NONE of the panels this cohort was sequenced with → coverage gap, not a real 0%.
    """
    sp = sample_panel if sample_panel is not None else load_sample_panel_map()
    pg = panel_genes if panel_genes is not None else load_panel_gene_sets()
    ids = list(sample_ids)
    n_total = len(ids)
    n_cov = sum(1 for s in ids if gene in pg.get(sp.get(s, ""), frozenset()))
    return {
        "n_total": n_total,
        "n_covered": n_cov,
        "n_uncovered": n_total - n_cov,
        "coverage_fraction": (n_cov / n_total) if n_total else None,
    }
