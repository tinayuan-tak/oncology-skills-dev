"""exon_skip_carrier.read — source loaders that produce carrier sample sets.

DepMap carriers are read PRODUCT-FIRST from the gene-sorted `depmap-somatic-splice-variants-v1`
product (a cheap pushdown on gene_symbol), falling back to a streamed read of the raw
OmicsSomaticMutationsMAF.maf only when the product is absent. Both are POSITION-BEARING: the
standard derived per-model somatic parquet (methods.depmap_common.parquet) exposes only
ModelID/VariantType/VariantInfo/ProteinChange/HugoSymbol — no Chromosome/Start_Position — so it
CANNOT isolate exon 14 (splice classification alone over-calls distant MET splice sites). The
product exists precisely so consumers avoid streaming the ~738 MB raw MAF per query.

MC3 / GENIE patient carriers use the SAME classifier (classify.carriers_for_event) over the
per-sample MAF, which retains Start_Position; that wiring is a downstream follow-up (the
patient-prevalence + dependency-stratification consumers), tracked with the card/resolver work.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Iterable, Optional

from .classify import VariantObs, carriers_for_event
from .events import EXON_SKIP_EVENTS

METHOD_VERSION = "0.1.0"

DEFAULT_AWS_PROFILE = "cbg"
DEPMAP_SOURCE_MANIFEST_ID = "depmap-consortium-26q1"
PRODUCT_MANIFEST_ID = "depmap-somatic-splice-variants-v1"
_MAF_FILENAME = "OmicsSomaticMutationsMAF.maf"


def _resolve_maf_location():
    """(bucket, key) for the raw DepMap somatic MAF, resolved from the data-catalog manifest."""
    import sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
    from methods.catalog_query.read import bucket_prefix_for
    bucket, prefix = bucket_prefix_for(DEPMAP_SOURCE_MANIFEST_ID)
    return bucket, f"{prefix.rstrip('/')}/{_MAF_FILENAME}"


def _stream_maf_lines(bucket: str, key: str) -> Iterable[list]:
    """Yield tab-split rows of the raw MAF, streamed (no full-file buffering). First yielded
    row is the header. Skips leading '#'-comment lines."""
    import boto3
    s3 = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")
    body = s3.get_object(Bucket=bucket, Key=key)["Body"]
    header_sent = False
    for raw in body.iter_lines():
        line = raw.decode("utf-8", "replace")
        if not header_sent:
            if line.startswith("#") or not line.strip():
                continue
            header_sent = True
        yield line.split("\t")


def _observations_from_maf(rows: Iterable[list], gene: str) -> Iterable[VariantObs]:
    """Adapt raw-MAF rows (first row = header) into gene-filtered VariantObs."""
    it = iter(rows)
    header = next(it)
    ix = {name: i for i, name in enumerate(header)}
    gi, ci, pi, vi, si = (ix.get("Hugo_Symbol"), ix.get("Chromosome"),
                          ix.get("Start_Position"), ix.get("Variant_Classification"),
                          ix.get("ModelID"))
    if None in (gi, ci, pi, vi, si):
        missing = [n for n, i in (("Hugo_Symbol", gi), ("Chromosome", ci), ("Start_Position", pi),
                                  ("Variant_Classification", vi), ("ModelID", si)) if i is None]
        raise ValueError(f"raw MAF missing required columns: {missing}")
    for r in it:
        if len(r) <= max(gi, ci, pi, vi, si) or r[gi] != gene:
            continue
        try:
            pos = int(r[pi])
        except (ValueError, TypeError):
            pos = None
        yield VariantObs(sample_id=r[si], chrom=r[ci], pos=pos, classification=r[vi])


def _observations_from_product(gene: str) -> Optional[list]:
    """PRODUCT-first: gene-sorted pushdown over depmap-somatic-splice-variants-v1.
    Returns a list of VariantObs, or None if the product is absent (→ raw-MAF fallback).
    Broken-env/transient/creds errors are re-raised (not masked as a coverage gap)."""
    try:
        import sys as _sys
        from pathlib import Path as _P
        _sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
        from methods.catalog_query.read import bucket_key_for
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(
            f"{bucket}/{key}", filesystem=fs.S3FileSystem(),
            columns=["gene_symbol", "model_id", "chrom", "start_position", "variant_classification"],
            filters=[("gene_symbol", "=", (gene or "").strip().upper())])
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        return None
    return [VariantObs(sample_id=r["model_id"], chrom=r["chrom"], pos=r["start_position"],
                       classification=r["variant_classification"]) for r in tbl.to_pylist()]


@lru_cache(maxsize=8)
def depmap_carriers(event_id: str = "METex14", release_pin: str = "26q1") -> dict:
    """Identify DepMap cell lines (ModelID) carrying `event_id`.

    Product-first (gene-sorted pushdown over depmap-somatic-splice-variants-v1); falls back to
    a streamed read of the raw somatic MAF when the product is absent. Returns {event_id, gene,
    release_pin, carrier_samples (sorted), n_carriers, genome_build, window, _data_source}.
    carrier_samples is the primitive the dependency-stratification + prevalence consumers key on.
    """
    if event_id not in EXON_SKIP_EVENTS:
        raise KeyError(f"unknown exon-skip event: {event_id!r}")
    ev = EXON_SKIP_EVENTS[event_id]
    obs = _observations_from_product(ev.gene)
    if obs is not None:
        source = f"{PRODUCT_MANIFEST_ID}"
    else:
        bucket, key = _resolve_maf_location()
        obs = list(_observations_from_maf(_stream_maf_lines(bucket, key), ev.gene))
        source = f"{DEPMAP_SOURCE_MANIFEST_ID}:{_MAF_FILENAME} (product-absent fallback)"
    carriers = carriers_for_event(obs, event_id)
    return {
        "event_id": event_id,
        "gene": ev.gene,
        "release_pin": release_pin,
        "genome_build": ev.genome_build,
        "window": f"{ev.chrom}:{ev.window_start}-{ev.window_end}",
        "carrier_samples": sorted(carriers),
        "n_carriers": len(carriers),
        "_data_source": source,
        "method_version": METHOD_VERSION,
    }


def carriers_from_observations(observations: Iterable[VariantObs], event_id: str = "METex14") -> dict:
    """Source-agnostic wrapper: classify already-loaded observations (any MAF). Used by MC3/GENIE
    consumers and tests. See classify.carriers_for_event."""
    ev = EXON_SKIP_EVENTS[event_id]
    carriers = carriers_for_event(observations, event_id)
    return {
        "event_id": event_id, "gene": ev.gene, "genome_build": ev.genome_build,
        "window": f"{ev.chrom}:{ev.window_start}-{ev.window_end}",
        "carrier_samples": sorted(carriers), "n_carriers": len(carriers),
        "method_version": METHOD_VERSION,
    }
