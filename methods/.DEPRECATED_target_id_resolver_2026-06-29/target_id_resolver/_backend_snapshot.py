"""Pinned-snapshot backend (production pins, resolver_v1.0.0+).

Resolution path: input -> SnapshotIndex (in-memory) -> Target. No HTTP at
resolution time; one-time index build at process startup. Same Target
schema as the MyGene backend; only the data plumbing differs.

Snapshot file paths are resolved by reading the resolver-release pin
and looking up each manifest_id in the data-catalog repo's
manifests/sources/ directory, then downloading (or using a local cache
of) the s3_uri payload. The current implementation defers S3 I/O to the
caller — they pass a SnapshotPaths with locally-cached files.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ._index import SnapshotIndex
from ._version import __version__
from .errors import NotFoundError
from .schema import (
    HGNC,
    NCBI,
    DeprecationWarning_,
    Ensembl,
    InputDescriptor,
    ReleasePins,
    Target,
    UniProt,
)


def resolve_via_snapshot(
    *,
    input_value: str,
    input_kind: str,
    resolver_release: str,
    data_pins: dict,
    index: SnapshotIndex,
) -> Target:
    """Resolve via in-memory SnapshotIndex. Public entry from core.resolve()
    when pin.dispatch == 'snapshot'."""

    hgnc_record = None
    deprecation = None
    aliases_at_resolution: list[str] = []

    if input_kind == "hgnc_id":
        hgnc_record = index.lookup_by_hgnc_id(input_value)
    elif input_kind == "ensembl_gene_id":
        hgnc_record = index.lookup_by_ensembl_gene_id(input_value)
    elif input_kind == "uniprot_accession":
        hgnc_record = index.lookup_by_uniprot_accession(input_value)
    elif input_kind == "entrez_id":
        hgnc_record = index.lookup_by_entrez_id(input_value)
    else:  # hgnc_symbol
        hgnc_record = index.lookup_by_symbol(input_value)
        if hgnc_record is None:
            # Try alias / previous symbol
            alias_hits = index.lookup_by_alias(input_value)
            if len(alias_hits) == 1:
                hgnc_record = alias_hits[0]
                deprecation = DeprecationWarning_(
                    input_alias=input_value,
                    resolved_to_primary=hgnc_record.symbol,
                    note=(
                        f"Input symbol {input_value!r} is recorded as a previous symbol "
                        f"or alias for {hgnc_record.symbol} (HGNC ID {hgnc_record.hgnc_id})."
                    ),
                )
            elif len(alias_hits) > 1:
                from .errors import AmbiguousInputError
                raise AmbiguousInputError(
                    input_value,
                    [{"symbol": r.symbol, "hgnc_id": r.hgnc_id} for r in alias_hits],
                )

    if hgnc_record is None:
        raise NotFoundError(input_value)

    # Companion records — Ensembl version + UniProt accession come from the mirrors.
    ensembl_record = index.ensembl_record_for(hgnc_record)
    uniprot_record = index.uniprot_record_for(hgnc_record)

    # Build Ensembl block. Every Target requires an Ensembl gene_id.
    if ensembl_record is None:
        # HGNC didn't xref to Ensembl, OR Ensembl mirror lacked the gene_id.
        # Fall back to HGNC's own ensembl_gene_id with no version.
        if not hgnc_record.ensembl_gene_id:
            raise NotFoundError(
                f"{input_value!r} resolved to {hgnc_record.symbol} but has no Ensembl gene mapping."
            )
        ensembl_block = Ensembl(
            gene_id=hgnc_record.ensembl_gene_id,
            version="0",
            full=f"{hgnc_record.ensembl_gene_id}.0",
        )
    else:
        ensembl_block = Ensembl(
            gene_id=ensembl_record.gene_id,
            version=ensembl_record.version,
            full=ensembl_record.full,
        )

    # Build UniProt block (optional).
    uniprot_block: Optional[UniProt] = None
    if uniprot_record is not None:
        uniprot_block = UniProt(
            canonical_accession=uniprot_record.accession,
            entry_name=uniprot_record.name,
            reviewed=uniprot_record.reviewed,
        )

    # Build NCBI block.
    ncbi_block: Optional[NCBI] = None
    if hgnc_record.entrez_id:
        try:
            ncbi_block = NCBI(entrez_id=int(hgnc_record.entrez_id))
        except (TypeError, ValueError):
            pass

    # Build HGNC block.
    hgnc_block = HGNC(
        id=hgnc_record.hgnc_id,
        primary_symbol=hgnc_record.symbol,
        name=hgnc_record.name,
        locus_group=hgnc_record.locus_group,
        chromosome=hgnc_record.location,
    )

    # Aliases at resolution time: HGNC's aliases + prev_symbols (deduplicated).
    seen: set[str] = set()
    aliases_at_resolution = []
    for a in list(hgnc_record.aliases) + list(hgnc_record.prev_symbols):
        if a and a not in seen:
            seen.add(a)
            aliases_at_resolution.append(a)

    release_pins = ReleasePins(
        resolver_release=resolver_release,
        hgnc=data_pins.get("hgnc"),
        ensembl=data_pins.get("ensembl"),
        uniprot=data_pins.get("uniprot"),
        ncbi_gene=data_pins.get("ncbi_gene"),
        mygene_metadata=data_pins.get("mygene_metadata"),
    )

    return Target(
        hgnc=hgnc_block,
        ensembl=ensembl_block,
        uniprot=uniprot_block,
        ncbi=ncbi_block,
        aliases_at_resolution=aliases_at_resolution,
        deprecation_warning=deprecation,
        release_pins=release_pins,
        resolver_version=__version__,
        resolved_at=datetime.now(timezone.utc),
        input=InputDescriptor(value=input_value, interpreted_as=input_kind),
    )
