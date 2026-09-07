"""signor_mechanism_network — read + aggregate SIGNOR mechanism network per target.

Consumer: signaling-network-mechanism evidence card (Phase D) via
mechanism-and-pharmacology skill.

Hybrid cache-then-compute pattern:
  1. Try to load pre-computed derived parquet from S3
     (s3://onc-compbio/data-catalog/derived/signor-mechanism-network-per-gene-v1/)
  2. If not found, run compute inline from the direct SIGNOR quarterly release
     (s3://onc-compbio/data-catalog/sources/signor/jul2026/SIGNOR_Jul2026_release.txt)
     ~21 MB TSV; ~10 sec to stream + filter + classify a per-target subset
  3. Cache result to local ~/.cache/framework-signor/ for subsequent invocations
  4. Return per-target aggregated summary matching the card's summary_fields shape

SIGNOR direct source (not OmniPath's SIGNOR-tagged subset) chosen because:
  - Canonical SIGNOR curation without OmniPath aggregation drift
  - Full 27-column schema preserves ENTITYA/B gene symbols + EFFECT + MECHANISM
    + PMID + verbatim SENTENCE — the OmniPath TSV catalogued has only 8 stripped
    columns (UniProt-AC + directionality flags only, no gene symbols or
    mechanism strings)
  - CC-BY-SA 4.0 license: cite Licata et al 2020 NAR + Perfetto et al 2016 NAR

Row-level parquet schema (from cli.py):
    target_uniprot_ac, target_gene_symbol, partner_uniprot_ac,
    partner_gene_symbol, direction ('upstream'|'downstream'),
    raw_mechanism, moa_class, modality_relevance, is_stimulation,
    is_inhibition, consensus_direction, references, moa_ontology_version

read_target_summary aggregates to per-target categorical:
    network_class ('well_characterized'|'partial'|'sparse'|'data_unavailable')
    n_upstream_regulators, n_downstream_effectors
    upstream_regulators, downstream_effectors (list<struct>)
    moa_classes_present, pd_marker_classes_present (list<str>)
    has_actionable_moa, has_pd_marker (bool)
    moa_ontology_version, moa_ontology_unmapped_fraction
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import threading

from .moa_ontology import classify_edge, ONTOLOGY_VERSION
from methods.catalog_query.read import bucket_prefix_for, bucket_key_for

DEFAULT_AWS_PROFILE = "cbg"
SIGNOR_SOURCE_MANIFEST_ID = "signor-jul2026"
# source key resolved from the manifest (single source of truth).
S3_BUCKET, _SIGNOR_PREFIX = bucket_prefix_for(SIGNOR_SOURCE_MANIFEST_ID)
SIGNOR_S3_KEY = f"{_SIGNOR_PREFIX}SIGNOR_Jul2026_release.txt"

# The derived per-gene product (re-materialised 2026-08-22, direct-signor-jul2026 emit). Resolved
# from the catalog manifest — the PRIMARY read streams it via pushdown; on any absence/failure the
# reader falls back to the inline SIGNOR-TSV compose (read_target_summary Path 2).
DERIVED_MANIFEST_ID = "signor-mechanism-network-per-gene-v1"

# Human tax-id — SIGNOR includes some cross-species rows; filter to Homo sapiens
HUMAN_TAX_ID = "9606"

CACHE_DIR = Path.home() / ".cache" / "framework-signor"
CACHE_TSV = CACHE_DIR / "SIGNOR_Jul2026_release.txt"


from methods.target_id_sidecar import s3_client as _boto3_client

_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton (region us-east-1). Mirrors dge_deseq2._get_s3fs."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as pafs

                _S3FS = pafs.S3FileSystem(region="us-east-1")
    return _S3FS


def _ensure_signor_source_cached() -> Path:
    """Ensure the SIGNOR release TSV is available locally. Downloads from S3
    on first call; subsequent calls hit the local cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_TSV.exists() and CACHE_TSV.stat().st_size > 0:
        return CACHE_TSV
    s3 = _boto3_client()
    s3.download_file(S3_BUCKET, SIGNOR_S3_KEY, str(CACHE_TSV))
    return CACHE_TSV


from functools import lru_cache


@lru_cache(maxsize=1)
def _load_signor_rows_indexed() -> tuple[list[dict], dict]:
    """Parse the SIGNOR TSV ONCE and cache in-memory. Returns (all_rows,
    entity_to_row_indexes) where entity_to_row_indexes maps entity name
    (from ENTITYA or ENTITYB) → list of row indexes involving that entity.

    Filters to Homo sapiens (TAX_ID=9606) at parse time.

    Runtime discipline: the previous per-target read
    re-streamed + re-parsed all 130k rows on every call, giving ~0.78s/call
    at warm-cache. This function caches the parse; per-target reads then
    become O(k) where k = rows-involving-target (~10-100). New warm-call
    latency: ~10ms per target.
    """
    path = _ensure_signor_source_cached()
    rows: list[dict] = []
    entity_index: dict[str, list[int]] = {}
    with path.open("r", encoding="utf-8") as f:
        header_line = f.readline().rstrip("\n").rstrip("\r")
        header = header_line.split("\t")
        for line in f:
            parts = line.rstrip("\n").rstrip("\r").split("\t")
            if len(parts) < len(header):
                parts += [""] * (len(header) - len(parts))
            row = dict(zip(header, parts))
            if row.get("TAX_ID", "").strip() != HUMAN_TAX_ID:
                continue
            idx = len(rows)
            rows.append(row)
            # Index BOTH ENTITYA and ENTITYB so a per-target filter is O(k)
            for col in ("ENTITYA", "ENTITYB"):
                entity = row.get(col, "").strip()
                if entity:
                    entity_index.setdefault(entity, []).append(idx)
    return rows, entity_index


def _stream_signor_rows():
    """Legacy per-target iteration path. Kept for API-compat but now
    delegates to the cached parse — no more per-call TSV re-reading.
    """
    rows, _ = _load_signor_rows_indexed()
    yield from rows


def _iter_signor_rows_for_target(target: str):
    """O(k) iteration over the SIGNOR rows that involve the target,
    where k = rows-in-index[target]. Uses the parsed + indexed cache.
    """
    _, entity_index = _load_signor_rows_indexed()
    row_indexes = entity_index.get(target, [])
    if not row_indexes:
        return
    all_rows, _ = _load_signor_rows_indexed()  # same cached tuple
    for idx in row_indexes:
        yield all_rows[idx]


def _compute_edges_for_target(target: str) -> tuple[list[dict], int, int]:
    """Filter SIGNOR to edges involving `target` (by ENTITYA or ENTITYB gene
    symbol), classify each edge via MoA ontology, return (edges, total, unmapped).

    Only protein entities are emitted (SIGNOR types: protein, TYPEA/B == 'protein').
    Complexes (SIGNOR-PF, SIGNOR-C) are skipped; downstream mechanism
    reasoning is easier with atomic gene-symbol partners.
    """
    edges: list[dict] = []
    unmapped = 0
    total = 0

    # Fast path: use the pre-indexed target lookup
    # rather than scanning all 130k rows on every call.
    for row in _iter_signor_rows_for_target(target):
        entity_a = row.get("ENTITYA", "").strip()
        entity_b = row.get("ENTITYB", "").strip()
        # Defensive: entity_index should guarantee target ∈ (a, b), but
        # verify to preserve correctness under future index-cache changes.
        if target not in (entity_a, entity_b):
            continue

        type_a = row.get("TYPEA", "").strip().lower()
        type_b = row.get("TYPEB", "").strip().lower()
        if "protein" not in type_a or "protein" not in type_b:
            # skip complex-involved edges
            continue

        id_a = row.get("IDA", "").strip()
        id_b = row.get("IDB", "").strip()
        effect = row.get("EFFECT", "").strip().strip('"')
        # SIGNOR sometimes ships MECHANISM values wrapped in literal double-
        # quotes (e.g. '"guanine nucleotide exchange factor"'). Strip them
        # so the case-insensitive exact-match lookup in moa_ontology.py hits.
        mechanism = row.get("MECHANISM", "").strip().strip('"')
        pmid = row.get("PMID", "").strip()
        direct_flag = row.get("DIRECT", "").strip().lower() in ("t", "true", "1", "yes")

        # Directionality: SIGNOR is A → B (A affects B).
        # If target == ENTITYA → partner is B, direction is "downstream"
        # If target == ENTITYB → partner is A, direction is "upstream"
        if target == entity_a:
            partner_symbol = entity_b
            partner_uniprot = id_b
            direction = "downstream"
        else:
            partner_symbol = entity_a
            partner_uniprot = id_a
            direction = "upstream"

        # SIGNOR EFFECT column encodes direction of regulation (up/down);
        # our is_stimulation / is_inhibition heuristic maps that
        effect_lower = effect.lower()
        is_stim = "up-regulates" in effect_lower or "up regulates" in effect_lower
        is_inh = "down-regulates" in effect_lower or "down regulates" in effect_lower

        # Derive a mechanism string for the MoA classifier. Prefer explicit
        # SIGNOR MECHANISM; fall back to EFFECT-derived if empty.
        if mechanism:
            mech_str = mechanism.lower()
        elif is_inh:
            mech_str = "inhibition"
        elif is_stim:
            mech_str = "stimulation"
        else:
            mech_str = "binding"

        cls = classify_edge(mech_str, direction)
        total += 1
        if cls is None:
            unmapped += 1
            moa_class = "unmapped"
            modality_relevance: tuple = ()
        else:
            moa_class = cls.moa_class
            modality_relevance = cls.modality_relevance

        edges.append(
            {
                "partner_uniprot_ac": partner_uniprot,
                "partner_gene_symbol": partner_symbol,
                "direction": direction,
                "raw_mechanism": mechanism,
                "raw_effect": effect,
                "moa_class": moa_class,
                "modality_relevance": list(modality_relevance),
                "is_stimulation": is_stim,
                "is_inhibition": is_inh,
                "direct_flag": direct_flag,
                "references": pmid,
            }
        )

    return edges, total, unmapped


def _aggregate_edges_to_summary(
    edges: list[dict],
    total: int,
    unmapped: int,
    data_source: str = SIGNOR_SOURCE_MANIFEST_ID,
) -> dict:
    """Aggregate per-edge records → per-target card summary dict.

    `data_source` stamps the provenance HONESTLY per read path: the derived-parquet
    path passes DERIVED_MANIFEST_ID; the compute-from-source path (the live path —
    the derived product was reverted and has no catalog manifest) leaves the default
    SIGNOR_SOURCE_MANIFEST_ID. The prior code hard-stamped DERIVED_MANIFEST_ID on BOTH
    paths, so a source-composed read falsely advertised a nonexistent derived product."""
    upstream = [e for e in edges if e["direction"] == "upstream"]
    downstream = [e for e in edges if e["direction"] == "downstream"]
    n_up = len(upstream)
    n_down = len(downstream)

    if n_up == 0 and n_down == 0:
        network_class = "data_unavailable"
    elif n_up >= 3 and n_down >= 3:
        network_class = "well_characterized"
    elif n_up + n_down <= 1:
        network_class = "sparse"
    else:
        network_class = "partial"

    moa_classes_present = sorted({e["moa_class"] for e in upstream})
    pd_marker_classes_present = sorted({e["moa_class"] for e in downstream})

    unmapped_frac = (unmapped / total) if total > 0 else 0.0

    return {
        "network_class": network_class,
        "n_upstream_regulators": n_up,
        "n_downstream_effectors": n_down,
        "upstream_regulators": upstream,
        "downstream_effectors": downstream,
        "moa_classes_present": moa_classes_present,
        "pd_marker_classes_present": pd_marker_classes_present,
        "has_actionable_moa": n_up >= 1,
        "has_pd_marker": n_down >= 1,
        "moa_ontology_version": ONTOLOGY_VERSION,
        "moa_ontology_unmapped_fraction": unmapped_frac,
        "_data_source": data_source,
        "_data_source_upstream": SIGNOR_SOURCE_MANIFEST_ID,
    }


# Module-level negative cache: once we know the derived parquet is
# unavailable in this Python process, don't re-hit S3 on every call.
# (Boto3 GetObject for a non-existent key costs ~200-500ms per attempt.)
_DERIVED_PARQUET_STATUS: Optional[bool] = None  # None = unchecked; False = confirmed absent; True = available


def _read_from_derived_parquet(target: str) -> Optional[dict]:
    """Satisfy the request from the derived per-gene product via STREAMED pushdown (pyarrow
    S3FileSystem, filters on target_gene_symbol) — no whole-file download. Returns None when the
    product is absent (→ caller falls back to the inline SIGNOR-TSV compose) or the target has no
    edges. Module-level negative cache latches a CONFIRMED-absent product so we don't re-probe S3
    every call; a transient failure does NOT latch (retries next call, still falling back this call)."""
    global _DERIVED_PARQUET_STATUS
    if _DERIVED_PARQUET_STATUS is False:
        return None  # confirmed absent; skip S3 retry, use inline fallback
    try:
        import pyarrow.parquet as pq

        bucket, key = bucket_key_for(DERIVED_MANIFEST_ID)
        table = pq.read_table(f"{bucket}/{key}", filesystem=_get_s3fs(), filters=[("target_gene_symbol", "=", target)])
        _DERIVED_PARQUET_STATUS = True
    except Exception as e:  # absence-discipline: exempt -- product-absent/transient → benign fallback to the inline SIGNOR-TSV compute (Path 2), never a dead axis
        from methods.target_id_sidecar import is_definitively_absent

        # A genuinely-absent product (no manifest yet / NoSuchKey / 404) latches so we stop probing;
        # a transient/creds error does NOT latch (retry next call). Either way, fall back to inline.
        if isinstance(e, FileNotFoundError) or is_definitively_absent(e):
            _DERIVED_PARQUET_STATUS = False
        return None
    if table.num_rows == 0:
        return None
    stripped = [
        {k: v for k, v in row.items() if k not in {"target_uniprot_ac", "target_gene_symbol"}}
        for row in table.to_pylist()
    ]
    total = len(stripped)
    unmapped = sum(1 for e in stripped if e.get("moa_class") == "unmapped")
    # read from the derived product → stamp it as the source (honest per-path provenance)
    return _aggregate_edges_to_summary(stripped, total, unmapped, data_source=DERIVED_MANIFEST_ID)


def read_target_summary(target: str, indication: str = None) -> dict:
    """Per-target SIGNOR mechanism-network summary. Hybrid cache-then-compute.

    Args:
        target: HGNC gene symbol (e.g., 'KRAS'). SIGNOR's ENTITYA/ENTITYB
            columns carry gene symbols directly.
        indication: unused (SIGNOR is indication-agnostic); accepted for
            dispatcher signature consistency across cards.

    Returns:
        dict matching signaling-network-mechanism card's summary_fields shape.
        Never raises on target-not-found — returns network_class='data_unavailable'.
    """
    # Path 1: try pre-computed derived parquet
    from_parquet = _read_from_derived_parquet(target)
    if from_parquet is not None:
        return from_parquet

    # Path 2: inline compute from SIGNOR TSV (streams ~35k human rows in ~5-10 sec)
    try:
        edges, total, unmapped = _compute_edges_for_target(target)
        return _aggregate_edges_to_summary(edges, total, unmapped)
    except Exception as e:
        # Path 3: fail gracefully
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
            "_data_note": f"compute_failed: {type(e).__name__}: {e}",
        }
