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
# The `sv` column names the panel that assayed a sample's structural variants. GENIE ships
# per-assay coverage columns (mutations/cna/sv); a sample can be SNV-profiled but NOT
# SV-profiled, so the SV denominator must key on THIS column, not `mutations`. (In v19 the
# sv-panel id equals the mutations-panel id where both are present — same gene-list applies —
# but ~3.3k samples have a blank `sv` and must be excluded from every SV denominator.)
_SV_PANEL_COLUMN = "sv"


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


from methods.target_id_sidecar import s3_client as _boto3_client


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


@lru_cache(maxsize=4)
def _sample_panel_map_for_column(column: str, genie_prefix: str = GENIE_PREFIX) -> dict:
    """{sample_id: panel_id} from a data_gene_matrix.txt per-assay column. Samples with a
    blank panel for that assay (not profiled on it) are OMITTED — they carry no coverage for
    any gene on that assay and must not enter its denominator. Cached per column."""
    import pandas as pd
    _ensure_aws_profile()
    s3 = _boto3_client()
    key = f"{genie_prefix}/data_gene_matrix.txt" if genie_prefix != GENIE_PREFIX else GENE_MATRIX_KEY
    body = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"]
    df = pd.read_csv(body, sep="\t", dtype=str)
    if column not in df.columns:
        return {}
    df = df[["SAMPLE_ID", column]].dropna(subset=[column])
    df = df[df[column].str.strip() != ""]
    return dict(zip(df["SAMPLE_ID"], df[column]))


def load_sample_panel_map(genie_prefix: str = GENIE_PREFIX) -> dict:
    """{sample_id: panel_id} from data_gene_matrix.txt `mutations` column — the panel that
    assayed each sample's SNVs. Samples with a blank mutations-panel (not SNV-profiled) are
    OMITTED. Cached once."""
    return _sample_panel_map_for_column(_MUTATIONS_PANEL_COLUMN, genie_prefix)


def load_sv_sample_panel_map(genie_prefix: str = GENIE_PREFIX) -> dict:
    """{sample_id: panel_id} from data_gene_matrix.txt `sv` column — the panel that assayed
    each sample's STRUCTURAL VARIANTS. Samples with a blank sv-panel (not SV-profiled) are
    OMITTED from every SV denominator (absent SV ≠ not-sequenced-for-SV). The panel gene-sets
    are shared with the mutation side (`load_panel_gene_sets`), since a panel's gene-list is
    the same regardless of which alteration class it was queried for."""
    return _sample_panel_map_for_column(_SV_PANEL_COLUMN, genie_prefix)


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
