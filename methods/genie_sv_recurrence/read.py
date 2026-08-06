"""genie_sv_recurrence.read — coverage-correct GENIE SV recurrence + percentile + partners.

Fuses GENIE data_sv.txt (per-sample structural variants) with:
  - the FULL indication cohort (data_clinical_sample.txt CANCER_TYPE) — the denominator universe
    of SV-profiled samples, mutated-or-not (reuses genie_panel_recurrence._indication_cohort), and
  - the SV-keyed panel-coverage denominator (genie_panel_coverage.load_sv_sample_panel_map + the
    shared panel gene-sets).

A gene's SV frequency = distinct samples with the gene at EITHER breakend / n samples whose panel
was queried for SV AND covers the gene. Emits a genie_sv_recurrence_percentile/_class (ranked against
all SV-covered genes in the indication), the coverage-gap flag, and recurrent SV partners (the SV data
uniquely names the fusion counterpart — EML4 for ALK, etc.). DISPLAY facet, verdict-inert.
"""
from __future__ import annotations

import io
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
GENIE_PREFIX = "data-catalog/sources/synapse/genie-public-v19-0"
SV_KEY = f"{GENIE_PREFIX}/data_sv.txt"
# Cutoffs mirror the MC3/GENIE driver-recurrence percentile classes.
DEFAULT_CUTOFFS = {"top_1pct": 99.0, "top_decile": 90.0, "bottom_decile": 10.0}
# A gene must be SV-covered on a MINIMUM number of samples for its frequency to be trustworthy;
# below this the percentile is emitted None (coverage too thin to rank), distinct from a gap.
_MIN_COVERED = 20
# A partner is "recurrent" once it recurs across at least this many samples (mirrors the TCGA
# fusion card's _RECURRENT_MIN_SAMPLES); GENIE depth means real partners clear it easily.
_RECURRENT_PARTNER_MIN = 3
# GENIE puts event-type annotations (not a partner gene) in the partner slot when a breakend has
# no gene counterpart — exclude these from the "recurrent PARTNER" display (they are not fusions).
_NON_GENE_PARTNER_TOKENS = frozenset({"INTERGENIC", "INTRAGENIC", "INTRACHROMOSOMAL"})

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # methods/ on path for siblings


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _boto3_client():
    import boto3
    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")


@lru_cache(maxsize=1)
def _load_sv():
    """GENIE data_sv.txt as a DataFrame of (sample_id, site1_gene, site2_gene). Quoting-aware
    parse — the free-text Comments/Annotation columns carry embedded newlines and quotes, so a
    naive line split would corrupt rows. Returns a pandas DataFrame or None."""
    import pandas as pd
    _ensure_aws_profile()
    s3 = _boto3_client()
    try:
        body = s3.get_object(Bucket=S3_BUCKET, Key=SV_KEY)["Body"].read()
    except Exception:
        return None
    df = pd.read_csv(io.BytesIO(body), sep="\t", dtype=str,
                     usecols=lambda c: c in ("Sample_Id", "Site1_Hugo_Symbol", "Site2_Hugo_Symbol"))
    df = df.rename(columns={"Sample_Id": "sample_id",
                            "Site1_Hugo_Symbol": "site1", "Site2_Hugo_Symbol": "site2"})
    return df


def _percentile(value, null_vec, cutoffs=None):
    from percentile_null import percentile_rank, classify_percentile
    pct = percentile_rank(value, null_vec)
    return pct, classify_percentile(pct, cutoffs or DEFAULT_CUTOFFS)


def _sv_samples_by_gene(indication: str):
    """{gene: set(sample_id)} — samples with the gene at EITHER breakend, restricted to the
    indication's SV-covered cohort. A sample counts for a gene iff it is in the indication cohort,
    was SV-profiled, and its panel covers the gene (else the SV is uncalled for that gene, not WT).
    Returns (gene_samples, covered_counter, n_cohort_sv_profiled)."""
    from collections import Counter, defaultdict
    from methods.genie_panel_recurrence.read import _indication_cohort
    from methods.genie_panel_coverage.read import load_sv_sample_panel_map, load_panel_gene_sets
    df = _load_sv()
    if df is None or len(df) == 0:
        return {}, Counter(), 0
    sp = load_sv_sample_panel_map()   # SV-keyed sample→panel (blank-sv samples already dropped)
    pg = load_panel_gene_sets()       # shared panel→gene-set
    cohort = set(_indication_cohort(indication)) & set(sp)   # indication ∩ SV-profiled
    if not cohort:
        return {}, Counter(), 0
    # coverage denominator per gene = cohort samples whose panel covers the gene.
    covered = Counter()
    for s in cohort:
        for g in pg.get(sp[s], ()):
            covered[g] += 1
    # numerator: samples with each gene at a breakend, gated on that sample covering the gene.
    gene_samples: dict = defaultdict(set)
    for sid, g1, g2 in df.itertuples(index=False):
        if sid not in cohort:
            continue
        panel_genes = pg.get(sp.get(sid, ""), frozenset())
        for g in (g1, g2):
            if g and isinstance(g, str) and g.strip() and g in panel_genes:
                gene_samples[g.strip()].add(sid)
    return gene_samples, covered, len(cohort)


@lru_cache(maxsize=8)
def _covered_gene_sv_frequencies(indication: str) -> tuple:
    """All-SV-covered-gene coverage-correct SV frequencies for one indication — the recurrence
    null. freq = n_sv_bearing / n_sv_covered; genes covered on < _MIN_COVERED samples are excluded
    (too thin to rank). Returns a tuple of (gene, freq, n_covered, n_sv) — hashable/cache-safe."""
    gene_samples, covered, _ = _sv_samples_by_gene(indication)
    out = []
    for gene, samples in gene_samples.items():
        n_cov = covered.get(gene, 0)
        if n_cov < _MIN_COVERED:
            continue
        out.append((gene, len(samples) / n_cov, n_cov, len(samples)))
    return tuple(out)


def _recurrent_partners(target: str, indication: str) -> list:
    """Partner genes fused to `target` across >= _RECURRENT_PARTNER_MIN distinct samples, count-desc.
    The SV feed uniquely names the counterpart of each breakend (EML4 for ALK, TMPRSS2 for ERG, …)."""
    from collections import defaultdict
    from methods.genie_panel_recurrence.read import _indication_cohort
    df = _load_sv()
    if df is None or len(df) == 0:
        return []
    cohort = set(_indication_cohort(indication))
    if not cohort:
        return []
    sym = target.upper().strip()
    partner_samples: dict = defaultdict(set)
    for sid, g1, g2 in df.itertuples(index=False):
        if sid not in cohort:
            continue
        g1s = (g1 or "").strip() if isinstance(g1, str) else ""
        g2s = (g2 or "").strip() if isinstance(g2, str) else ""
        if g1s.upper() == sym and g2s:
            partner_samples[g2s].add(sid)
        elif g2s.upper() == sym and g1s:
            partner_samples[g1s].add(sid)
    rec = sorted(((p, len(s)) for p, s in partner_samples.items()
                  if len(s) >= _RECURRENT_PARTNER_MIN and p.upper() not in _NON_GENE_PARTNER_TOKENS),
                 key=lambda x: (-x[1], x[0]))
    return [{"partner": p, "n_samples": n} for p, n in rec]


def genie_sv_recurrence_for_gene(target: str, indication: str, cutoffs: dict = None) -> dict:
    """Coverage-correct GENIE SV recurrence for one (target, indication). The GENIE (higher-N,
    pan-cohort) complement to the TCGA fusion card; a DISPLAY facet (verdict-inert).

    Returns genie_sv_frequency (n_sv_bearing/n_sv_covered), n_sv_covered, n_sv_samples,
    genie_sv_recurrence_percentile + _class, genie_sv_recurrent_partners, coverage_gap, context.
    coverage_gap=True (n_sv_covered==0 → gene on no SV panel in the cohort) → percentile None,
    class data_unavailable (NOT frequency 0). n_covered below the min → percentile None (too thin).
    """
    df = _load_sv()
    if df is None:
        return {"genie_sv_recurrence_class": "data_unavailable",
                "genie_sv_recurrence_percentile": None, "genie_sv_frequency": None,
                "n_sv_covered": None, "n_sv_samples": None, "genie_sv_recurrent_partners": [],
                "coverage_gap": None, "genie_sv_context": "no GENIE SV feed available"}

    gene_samples, covered, n_cohort = _sv_samples_by_gene(indication)
    if n_cohort == 0:
        return {"genie_sv_recurrence_class": "data_unavailable",
                "genie_sv_recurrence_percentile": None, "genie_sv_frequency": None,
                "n_sv_covered": None, "n_sv_samples": None, "genie_sv_recurrent_partners": [],
                "coverage_gap": None,
                "genie_sv_context": f"no SV-profiled GENIE cohort for {indication}"}

    sym = target.strip()
    n_cov = covered.get(sym, 0)
    n_sv = len(gene_samples.get(sym, set()))

    if n_cov == 0:
        return {"genie_sv_recurrence_class": "data_unavailable",
                "genie_sv_recurrence_percentile": None, "genie_sv_frequency": None,
                "n_sv_covered": 0, "n_sv_samples": n_sv, "genie_sv_recurrent_partners": [],
                "coverage_gap": True,
                "genie_sv_context": (
                    f"{target} on NO SV-calling GENIE panel in {indication} "
                    f"(coverage gap — not a real 0%)")}

    freq = n_sv / n_cov
    null = _covered_gene_sv_frequencies(indication)
    null_vec = tuple(f for _g, f, _nc, _ns in null)
    partners = _recurrent_partners(target, indication)
    if n_cov < _MIN_COVERED or not null_vec:
        pct, cls = None, "data_unavailable"
        note = f"{target} SV-covered on only {n_cov} GENIE {indication} samples (< {_MIN_COVERED}; too thin to rank)"
    else:
        pct, cls = _percentile(freq, null_vec, cutoffs)
        note = (f"among {len(null_vec)} SV-covered genes in {indication} "
                f"(GENIE data_sv, coverage-corrected denominator)")
    return {
        "genie_sv_frequency": freq,
        "n_sv_covered": n_cov,
        "n_sv_samples": n_sv,
        "genie_sv_recurrence_percentile": pct,
        "genie_sv_recurrence_class": cls,
        "genie_sv_recurrent_partners": partners,
        "coverage_gap": False,
        "genie_sv_context": note,
    }


def build_genie_sv_recurrence_table(indication: str):
    """Materialize the per-gene coverage-correct GENIE SV recurrence table for an indication
    (for a registered derived product). One row per SV-covered+SV-bearing gene."""
    import pyarrow as pa
    null = _covered_gene_sv_frequencies(indication)
    if not null:
        return pa.Table.from_pylist([], schema=_schema())
    null_vec = tuple(f for _g, f, _nc, _ns in null)
    rows = []
    for gene, freq, n_cov, n_sv in null:
        pct, cls = _percentile(freq, null_vec)
        rows.append({"indication": indication, "gene_symbol": gene,
                     "n_sv_covered": n_cov, "n_sv_samples": n_sv,
                     "genie_sv_frequency": freq,
                     "genie_sv_recurrence_percentile": pct,
                     "genie_sv_recurrence_class": cls})
    rows.sort(key=lambda r: (r["gene_symbol"],))
    return pa.Table.from_pylist(rows, schema=_schema())


def _schema():
    import pyarrow as pa
    return pa.schema([
        pa.field("indication", pa.string()), pa.field("gene_symbol", pa.string()),
        pa.field("n_sv_covered", pa.int64()), pa.field("n_sv_samples", pa.int64()),
        pa.field("genie_sv_frequency", pa.float64()),
        pa.field("genie_sv_recurrence_percentile", pa.float64()),
        pa.field("genie_sv_recurrence_class", pa.string()),
    ])
