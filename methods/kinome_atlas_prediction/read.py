"""kinome_atlas_prediction.read — Johnson 2023 + Yaron-Barir 2024 substrate reader.

Returns predicted kinase-substrate edges for a target, sourced from a
Layer-3 derived parquet materialized once from the two Nature-supplementary
Excel files (see methods.kinome_atlas_prediction.derive).

When target is a KINASE, returns its predicted substrates (target-as-source).
When target is a SUBSTRATE, returns kinases predicted to phosphorylate it
(target-as-target).

Runtime discipline (v2, 2026-07-10 perf fix):
  - Read-time percentile>=RUNTIME_PERCENTILE_THRESHOLD filter via parquet
    predicate pushdown. Default is 95 (retains top-decile-of-top-decile
    PWM matches — ~1.4M edges from the ~2.9M-edge parquet's 90-band).
    Downstream synthesis was already discounting kinome-atlas edges; the
    95 threshold cuts noise without losing the "top 30 kinases per site"
    signal that governance readers actually consume.
  - Column-iteration (NOT df.to_dict) to build the substrate/kinase indices.
    to_dict(orient='records') on 2.9M rows was the profile bottleneck
    (32s out of 46s cold). Column-array iteration is ~5x faster.
  - Lazy per-target row materialization: keep the DataFrame in memory,
    materialize only the rows for a specific target at read_target_summary
    time. BRAF (~5,000 relevant rows) materializes in ~150ms instead of
    the previous full-atlas-materialize.
  - @lru_cache(maxsize=1) on load+index still applies — cold path runs
    ONCE per process.

Emitted edges carry source="kinome_atlas_prediction" so consumers can
distinguish from curated SIGNOR/CollecTri/Reactome edges and weight
accordingly. confidence_bucket is derived from the paper's percentile-rank
of the PWM log-odds score.
"""

from __future__ import annotations

import os
import threading
from functools import lru_cache

from methods.catalog_query.read import bucket_key_for
from methods.signor_mechanism_network.moa_ontology import ONTOLOGY_VERSION

DEFAULT_AWS_PROFILE = "cbg"
DERIVED_MANIFEST_ID = "kinome-atlas-long-edges-v1"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, DERIVED_S3_KEY = bucket_key_for(DERIVED_MANIFEST_ID)

# Runtime read-time percentile threshold. Parquet on S3 has percentile>=90
# edges (~2.9M rows); this constant further filters at read time. 95 =
# top-decile-of-top-decile PWM matches (~1.4M rows). Tunable if a future
# consumer wants finer or coarser filtering — override via env var
# KINOME_ATLAS_PERCENTILE_THRESHOLD.
RUNTIME_PERCENTILE_THRESHOLD = float(os.environ.get("KINOME_ATLAS_PERCENTILE_THRESHOLD", "95"))


_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton. Region is pinned to us-east-1 (the
    onc-compbio bucket) so construction skips the region-probe round-trip. pyarrow's
    S3FileSystem is safe to share across threads; build it ONCE. Mirrors dge_deseq2._get_s3fs."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as fs

                _S3FS = fs.S3FileSystem(region="us-east-1")
    return _S3FS


def _read_atlas_df():
    """Stream the derived atlas parquet directly from S3 with a percentile predicate pushdown.

    Replaces the former "download the whole 57 MB file to ~/.cache then read it" path with a
    pyarrow S3FileSystem STREAMED read (no local download): the derived product is written
    percentile-DESC (see derive.py), so the percentile>=RUNTIME_PERCENTILE_THRESHOLD predicate
    prunes the trailing row-groups instead of transferring the full atlas. Returns a
    pandas.DataFrame of the surviving rows (all schema columns, dtypes as written).

    Absence discipline: swallow ONLY a definitive object-absence (NoSuchKey / 404, or a pyarrow
    FileNotFoundError) as an honest empty frame; RE-RAISE transient / creds / broken-env failures
    so the live-read seam surfaces a real error instead of a silent data_unavailable.
    """
    import pandas as pd

    try:
        df = pd.read_parquet(
            f"{S3_BUCKET}/{DERIVED_S3_KEY}",
            filesystem=_get_s3fs(),
            # Read-time predicate pushdown: only pull rows above threshold.
            # Parquet on S3 has percentile>=90 edges (~2.9M); this drops to
            # ~1.4M at threshold=95, ~300K at threshold=99.
            filters=[("percentile", ">=", RUNTIME_PERCENTILE_THRESHOLD)],
        )
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        # A GENUINELY absent product object (NoSuchKey/404 or a pyarrow FileNotFoundError) is honest
        # absence -> empty frame (the caller's lru_cache never latches it as a poisoned negative).
        # A CORRUPT parquet / broken-env / creds / transient failure is NOT absence -> re-raise so
        # the live-read seam records the REAL cause instead of a silent empty index.
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return pd.DataFrame()
        raise
    return df


@lru_cache(maxsize=1)
def _load_atlas_indexed():
    """Load derived parquet (streamed from S3) + build kinase and substrate indices.

    Returns (df, kinase_index, substrate_index):
        - df: pandas.DataFrame with percentile>=RUNTIME_PERCENTILE_THRESHOLD
          rows. Rows are the source-of-truth; per-target dict materialization
          happens lazily at read_target_summary time via df.iloc[indices].
          Empty DataFrame if the product is genuinely absent.
        - kinase_index: dict[kinase_symbol -> list[row_index_in_df]]
        - substrate_index: dict[substrate_gene -> list[row_index_in_df]]

    The parquet is read via a streamed pyarrow S3FileSystem pushdown (see _read_atlas_df) —
    no whole-file download. Absence discipline lives in _read_atlas_df (definitive absence ->
    empty; transient/creds/broken-env -> raise), so a transient blip never latches an empty
    index into this @lru_cache.
    """
    df = _read_atlas_df()

    if df.empty:
        return df, {}, {}

    # Build indices via column-array iteration (NOT df.to_dict). Uses .values
    # for direct numpy access — ~5x faster than the previous to_dict path.
    kinase_index: dict[str, list[int]] = {}
    substrate_index: dict[str, list[int]] = {}

    kinase_col = df["kinase_symbol"].values
    substrate_col = df["substrate_gene"].values
    n_rows = len(df)
    for idx in range(n_rows):
        k = kinase_col[idx]
        s = substrate_col[idx]
        if not k or not s:
            continue
        k_up = str(k).strip().upper()
        s_up = str(s).strip().upper()
        kinase_index.setdefault(k_up, []).append(idx)
        substrate_index.setdefault(s_up, []).append(idx)

    return df, kinase_index, substrate_index


def _classify_confidence(percentile) -> str:
    if percentile is None:
        return "unranked"
    try:
        pct = float(percentile)
    except (ValueError, TypeError):
        return "unranked"
    if pct >= 99:
        return "top_percentile"
    if pct >= 95:
        return "high"
    if pct >= 90:
        return "moderate"
    return "low"


def _edge_to_downstream(edge: dict) -> dict:
    return {
        "partner_gene_symbol": str(edge.get("substrate_gene") or "").strip().upper(),
        "partner_uniprot_ac": str(edge.get("substrate_ac") or "").strip(),
        "direction": "downstream",
        "raw_mechanism": f"predicted phosphorylation ({edge.get('kinome', '')})",
        "moa_class": "downstream_predicted_phospho_readout",
        "modality_relevance": ["pd_biomarker_phospho"],
        "site_residue": str(edge.get("phos_res") or "").strip(),
        "site_position": edge.get("phosphosite"),
        "motif_15mer": str(edge.get("motif_15mer") or "").strip(),
        "pwm_percentile": edge.get("percentile"),
        "rank": edge.get("rank"),
        "confidence_bucket": _classify_confidence(edge.get("percentile")),
        "sources": ["kinome_atlas_prediction"],
        "kinome": edge.get("kinome"),
    }


def _edge_to_upstream(edge: dict) -> dict:
    return {
        "partner_gene_symbol": str(edge.get("kinase_symbol") or "").strip().upper(),
        "partner_uniprot_ac": "",  # kinase AC not stored per-edge; derivable from atlas metadata
        "direction": "upstream",
        "raw_mechanism": f"predicted phosphorylation ({edge.get('kinome', '')})",
        "moa_class": "upstream_predicted_kinase_modulation",
        "modality_relevance": ["small_molecule_kinase_inhibitor_predicted"],
        "site_residue": str(edge.get("phos_res") or "").strip(),
        "site_position": edge.get("phosphosite"),
        "motif_15mer": str(edge.get("motif_15mer") or "").strip(),
        "pwm_percentile": edge.get("percentile"),
        "rank": edge.get("rank"),
        "confidence_bucket": _classify_confidence(edge.get("percentile")),
        "sources": ["kinome_atlas_prediction"],
        "kinome": edge.get("kinome"),
    }


def _rank_key(e: dict):
    try:
        return -float(e.get("pwm_percentile") or 0)
    except (ValueError, TypeError):
        return 0


def read_target_summary(target: str, indication: str = None) -> dict:
    """Per-target kinome-atlas prediction summary.

    Args:
        target: HGNC gene symbol (kinome-atlas keys on symbol directly).
        indication: unused (atlas is context-agnostic).

    Returns:
        dict matching signor_mechanism_network.read output shape.
    """
    try:
        df, kinase_idx, substrate_idx = _load_atlas_indexed()
    except Exception as e:
        return _empty_result(f"atlas_load_failed: {type(e).__name__}: {e}")

    if df is None or df.empty:
        return _empty_result("kinome_atlas_data_unavailable")

    sym = target.upper().strip()

    # Lazy per-target row materialization. df.iloc[indices].to_dict on
    # ~1000-10000 rows is ~50-150ms — vs. materializing all 1.4M rows
    # which would be ~15s. Keeps warm path fast.
    dn_indices = kinase_idx.get(sym, [])
    up_indices = substrate_idx.get(sym, [])

    downstream_effectors = (
        [_edge_to_downstream(rec) for rec in df.iloc[dn_indices].to_dict(orient="records")] if dn_indices else []
    )
    upstream_regulators = (
        [_edge_to_upstream(rec) for rec in df.iloc[up_indices].to_dict(orient="records")] if up_indices else []
    )

    n_up = len(upstream_regulators)
    n_down = len(downstream_effectors)

    if n_up == 0 and n_down == 0:
        network_class = "data_unavailable"
    elif n_up >= 3 and n_down >= 3:
        network_class = "well_characterized"
    elif n_up + n_down <= 1:
        network_class = "sparse"
    else:
        network_class = "partial"

    moa_present = sorted({e["moa_class"] for e in upstream_regulators})
    pd_present = sorted({e["moa_class"] for e in downstream_effectors})

    upstream_regulators.sort(key=_rank_key)
    downstream_effectors.sort(key=_rank_key)

    return {
        "network_class": network_class,
        "n_upstream_regulators": n_up,
        "n_downstream_effectors": n_down,
        "upstream_regulators": upstream_regulators,
        "downstream_effectors": downstream_effectors,
        "moa_classes_present": moa_present,
        "pd_marker_classes_present": pd_present,
        "has_actionable_moa": n_up >= 1,
        "has_pd_marker": n_down >= 1,
        "moa_ontology_version": ONTOLOGY_VERSION,
        "moa_ontology_unmapped_fraction": 0.0,
        "_data_source": DERIVED_MANIFEST_ID,
        "_source_note": (
            "Kinome-atlas edges are PREDICTIONS from PWM specificity models "
            "(Johnson 2023 + Yaron-Barir 2024 Nature). Distinct from curated "
            "SIGNOR/CollecTri/Reactome edges — weight lower in Tier-3 synthesis. "
            f"Runtime filter: percentile >= {RUNTIME_PERCENTILE_THRESHOLD:.0f}."
        ),
        "_runtime_percentile_threshold": RUNTIME_PERCENTILE_THRESHOLD,
    }


def _empty_result(note: str) -> dict:
    return {
        "network_class": "data_unavailable",
        "n_upstream_regulators": 0,
        "n_downstream_effectors": 0,
        "upstream_regulators": [],
        "downstream_effectors": [],
        "moa_classes_present": [],
        "pd_marker_classes_present": [],
        "has_actionable_moa": False,
        "has_pd_marker": False,
        "moa_ontology_version": ONTOLOGY_VERSION,
        "moa_ontology_unmapped_fraction": 0.0,
        "_data_note": note,
    }
