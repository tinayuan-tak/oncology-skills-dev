"""sidecar.py — emit a target-resolution sidecar Parquet for a derived artifact.

The derived artifact (DGE Parquet, MAF, dependency screen, GMT) keeps its
native row keys; the sidecar maps each unique row-key to the canonical Target
schema. Skill queries join the artifact and the sidecar on the native key,
then aggregate / compare across sources via Target.hgnc.id.

Key design points:

  - Read-only against the payload artifact. Never modifies the source Parquet.
  - Resolves UNIQUE row keys only (one HTTP request per unique value, even
    if the artifact has duplicates — though most derived artifacts already
    have unique keys per row).
  - Edge cases the spec defined are surfaced as resolution_status enum values:
      resolved
      deprecated_remapped
      ambiguous
      no_hgnc_mapping
      no_match_in_source
      aggregated_multi_ensembl  (set by callers when the artifact aggregates
                                 multiple Ensembl IDs into one symbol; the
                                 emitter doesn't infer this — pass a
                                 mapping from the artifact's pipeline)
  - Output format: Parquet with 12 well-defined columns (see SIDECAR_SCHEMA).
    Sorted by hgnc_id for predicate-pushdown joins downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pyarrow as pa
import pyarrow.parquet as pq

from .core import resolve_batch
from .errors import AmbiguousInputError, NotFoundError
from .schema import Target


@dataclass
class SidecarStats:
    """Summary of a sidecar emit. Logged + returned for the caller's audit
    and stored in the derived manifest's target_resolution block."""

    n_input_keys: int
    resolved: int
    deprecated_remapped: int
    ambiguous: int
    no_hgnc_mapping: int
    no_match_in_source: int
    aggregated_multi_ensembl: int

    @property
    def unmappable_count(self) -> int:
        """Rows where the resolution_status is not 'resolved' AND not an
        acceptable deprecation. Used by validate_catalog.py if we ever want
        to gate on a max-unmappable threshold."""
        return self.ambiguous + self.no_hgnc_mapping + self.no_match_in_source

    @property
    def notable_aggregations_count(self) -> int:
        return self.aggregated_multi_ensembl


# Per-row resolution_status enum values (mirrors schema.ResolutionStatus
# but kept as plain strings for Parquet storage).
RS_RESOLVED = "resolved"
RS_DEPRECATED_REMAPPED = "deprecated_remapped"
RS_AMBIGUOUS = "ambiguous"
RS_NO_HGNC_MAPPING = "no_hgnc_mapping"
RS_NO_MATCH_IN_SOURCE = "no_match_in_source"
RS_AGGREGATED_MULTI_ENSEMBL = "aggregated_multi_ensembl"


# Sidecar Parquet schema — 12 columns, matches the spec.
SIDECAR_SCHEMA = pa.schema([
    pa.field("native_row_key", pa.string()),
    pa.field("native_key_type", pa.string()),  # gene_symbol | ensembl_gene_id | entrez_id | uniprot_accession
    pa.field("hgnc_id", pa.string()),
    pa.field("hgnc_primary_symbol_at_resolution", pa.string()),
    pa.field("ensembl_gene_id", pa.string()),
    pa.field("ensembl_gene_version", pa.string()),
    pa.field("uniprot_canonical", pa.string()),
    pa.field("entrez_id", pa.string()),
    pa.field("gencode_version_source", pa.string()),
    pa.field("resolution_status", pa.string()),
    pa.field("aggregated_ensembl_ids", pa.list_(pa.string())),
    pa.field("deprecation_note", pa.string()),
    pa.field("resolver_release_pin", pa.string()),
])


def _row_for_target(
    *,
    native_row_key: str,
    native_key_type: str,
    target: Target,
    gencode_version_source: str,
    aggregated_ensembl_ids: Optional[list[str]],
) -> dict:
    """Build one sidecar row from a successfully-resolved Target."""
    if target.deprecation_warning is not None:
        status = RS_DEPRECATED_REMAPPED
        note = target.deprecation_warning.note or ""
    elif aggregated_ensembl_ids and len(aggregated_ensembl_ids) > 1:
        status = RS_AGGREGATED_MULTI_ENSEMBL
        note = (
            f"Symbol aggregates {len(aggregated_ensembl_ids)} Ensembl IDs in the source "
            f"artifact; sidecar reports the canonical Target only."
        )
    else:
        status = RS_RESOLVED
        note = ""

    return {
        "native_row_key": native_row_key,
        "native_key_type": native_key_type,
        "hgnc_id": target.hgnc.id,
        "hgnc_primary_symbol_at_resolution": target.hgnc.primary_symbol,
        "ensembl_gene_id": target.ensembl.gene_id,
        "ensembl_gene_version": target.ensembl.version,
        "uniprot_canonical": target.uniprot.canonical_accession if target.uniprot else None,
        "entrez_id": str(target.ncbi.entrez_id) if target.ncbi else None,
        "gencode_version_source": gencode_version_source,
        "resolution_status": status,
        "aggregated_ensembl_ids": aggregated_ensembl_ids or [],
        "deprecation_note": note,
        "resolver_release_pin": target.release_pins.resolver_release,
    }


def _row_for_unresolved(
    *,
    native_row_key: str,
    native_key_type: str,
    status: str,
    gencode_version_source: str,
    note: str,
    resolver_release: str,
) -> dict:
    """Build one sidecar row for a key that didn't resolve (NotFoundError,
    AmbiguousInputError) or the artifact didn't have it (caller-provided
    no_match_in_source case)."""
    return {
        "native_row_key": native_row_key,
        "native_key_type": native_key_type,
        "hgnc_id": None,
        "hgnc_primary_symbol_at_resolution": None,
        "ensembl_gene_id": None,
        "ensembl_gene_version": None,
        "uniprot_canonical": None,
        "entrez_id": None,
        "gencode_version_source": gencode_version_source,
        "resolution_status": status,
        "aggregated_ensembl_ids": [],
        "deprecation_note": note,
        "resolver_release_pin": resolver_release,
    }


def emit_sidecar(
    *,
    payload_parquet_path: str | Path,
    native_key_column: str,
    native_key_type: str,
    gencode_version_source: str,
    out_path: str | Path,
    resolver_release: str,
    aggregation_map: Optional[dict[str, list[str]]] = None,
) -> SidecarStats:
    """Emit a target-resolution sidecar Parquet next to a derived artifact.

    Args:
        payload_parquet_path: source DGE / MAF / etc. Parquet file. Read-only.
        native_key_column: column name to read as the row key (e.g., 'gene_symbol').
        native_key_type: enum string identifying the key type (one of
            'gene_symbol', 'ensembl_gene_id', 'entrez_id', 'uniprot_accession').
        gencode_version_source: annotation version the source artifact was
            built against (e.g., 'v36'). Stored on every sidecar row so a
            cross-source consumer can detect annotation-version drift.
        out_path: where to write the sidecar Parquet. Convention: same
            directory as payload, replacing '.parquet' with '.target_resolution.parquet'.
        resolver_release: which resolver-release pin to use, e.g.
            'resolver_v1.0.0'.
        aggregation_map: optional dict mapping native_row_key -> list of
            Ensembl gene IDs the source pipeline aggregated into that key.
            For COADREAD-DGE this captures the 110 PAR_Y / IG cases where
            gene_symbol-aggregation summed counts across multiple Ensembl IDs.
            Keys not present in this dict are assumed not aggregated.

    Returns:
        SidecarStats summarizing per-status counts.
    """
    # Read just the native_key_column from the payload — the rest of the
    # artifact is irrelevant to sidecar emission.
    table = pq.read_table(payload_parquet_path, columns=[native_key_column])
    native_keys: list[str] = table[native_key_column].to_pylist()
    unique_keys = list(dict.fromkeys(k for k in native_keys if k is not None))

    # Resolve in batch. resolve_batch returns aligned [Target | None].
    targets = resolve_batch(unique_keys, resolver_release=resolver_release)

    rows: list[dict] = []
    for key, target in zip(unique_keys, targets):
        agg = (aggregation_map or {}).get(key)
        if target is not None:
            rows.append(_row_for_target(
                native_row_key=key,
                native_key_type=native_key_type,
                target=target,
                gencode_version_source=gencode_version_source,
                aggregated_ensembl_ids=agg,
            ))
        else:
            # resolve_batch swallowed NotFoundError or AmbiguousInputError.
            # Without the original exception we can't tell which; the
            # convention is no_hgnc_mapping for "no resolver hit at all"
            # since pseudogenes / ncRNAs are the dominant case.
            rows.append(_row_for_unresolved(
                native_row_key=key,
                native_key_type=native_key_type,
                status=RS_NO_HGNC_MAPPING,
                gencode_version_source=gencode_version_source,
                note=f"Resolver returned no Target for {key!r} (likely pseudogene, ncRNA, or annotation drift).",
                resolver_release=resolver_release,
            ))

    # Sort by hgnc_id (None last) for predicate-pushdown joins downstream.
    rows.sort(key=lambda r: (r["hgnc_id"] is None, r["hgnc_id"] or "", r["native_row_key"]))

    # Build pyarrow Table from rows + schema and write Parquet.
    out_table = pa.Table.from_pylist(rows, schema=SIDECAR_SCHEMA)
    pq.write_table(out_table, str(out_path), compression="snappy")

    # Tally stats from rows
    tally: dict[str, int] = {}
    for r in rows:
        tally[r["resolution_status"]] = tally.get(r["resolution_status"], 0) + 1

    return SidecarStats(
        n_input_keys=len(unique_keys),
        resolved=tally.get(RS_RESOLVED, 0),
        deprecated_remapped=tally.get(RS_DEPRECATED_REMAPPED, 0),
        ambiguous=tally.get(RS_AMBIGUOUS, 0),
        no_hgnc_mapping=tally.get(RS_NO_HGNC_MAPPING, 0),
        no_match_in_source=tally.get(RS_NO_MATCH_IN_SOURCE, 0),
        aggregated_multi_ensembl=tally.get(RS_AGGREGATED_MULTI_ENSEMBL, 0),
    )
