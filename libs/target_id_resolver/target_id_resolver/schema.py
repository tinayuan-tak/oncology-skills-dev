"""Pydantic models mirroring core-artifacts-schema/target.schema.json.

The JSON Schema is the cross-language contract; this module is the Python
binding. Field names, optionality, and patterns track the JSON Schema
faithfully — when one changes, the other must.

Design notes:
- Field aliases are used where Python identifiers can't match JSON exactly
  (only `DeprecationWarning_` here, because `DeprecationWarning` shadows the
  Python builtin).
- `model_dump(mode='json', exclude_none=True)` produces JSON that round-trips
  through the Target.schema.json validator without modification.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResolutionStatus(str, Enum):
    """Per-row status used by sidecar emission (forward-looking; not produced
    by core resolve() itself). Defined here so the enum is shared across
    library and consumers.
    """

    RESOLVED = "resolved"
    DEPRECATED_REMAPPED = "deprecated_remapped"
    AMBIGUOUS = "ambiguous"
    NO_HGNC_MAPPING = "no_hgnc_mapping"
    AGGREGATED_MULTI_ENSEMBL = "aggregated_multi_ensembl"
    NO_MATCH_IN_SOURCE = "no_match_in_source"


class HGNC(BaseModel):
    """HGNC is the master vocabulary."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^HGNC:[0-9]+$", description="HGNC accession, e.g. HGNC:11998 (TP53).")
    primary_symbol: str = Field(..., pattern=r"^[A-Za-z0-9_.-]+$")
    name: Optional[str] = None
    locus_group: Optional[str] = None
    chromosome: Optional[str] = None


class Ensembl(BaseModel):
    """Ensembl gene ID for genomic identity. Always carry version separately."""

    model_config = ConfigDict(extra="forbid")

    gene_id: str = Field(..., pattern=r"^ENSG[0-9]+$")
    version: str = Field(..., pattern=r"^[0-9]+$")
    full: Optional[str] = None

    @field_validator("full", mode="after")
    @classmethod
    def _check_full_matches(cls, v: Optional[str], info) -> Optional[str]:
        if v is None:
            return v
        gene_id = info.data.get("gene_id")
        version = info.data.get("version")
        expected = f"{gene_id}.{version}"
        if v != expected:
            raise ValueError(f"ensembl.full must equal '{gene_id}.{version}', got {v!r}")
        return v

    @classmethod
    def from_versioned(cls, versioned_id: str) -> "Ensembl":
        """Parse 'ENSG00000141510.18' into (gene_id='ENSG00000141510', version='18')."""
        m = re.match(r"^(ENSG[0-9]+)\.([0-9]+)$", versioned_id)
        if not m:
            raise ValueError(f"Not a versioned Ensembl gene ID: {versioned_id!r}")
        return cls(gene_id=m.group(1), version=m.group(2), full=versioned_id)


class UniProt(BaseModel):
    """UniProt canonical accession only in v2.0."""

    model_config = ConfigDict(extra="forbid")

    canonical_accession: str = Field(
        ...,
        # UniProt accession regex: pattern #1 [O,P,Q]N[A-Z0-9]{3}N (6 chars), or
        # pattern #2 [A-N,R-Z]N[A-Z][A-Z0-9]{2}N optionally repeated for 10-char accessions.
        pattern=r"^[OPQ][0-9][A-Z0-9]{3}[0-9]$|^[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2}$",
    )
    entry_name: Optional[str] = None
    reviewed: Optional[bool] = None


class NCBI(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entrez_id: int = Field(..., gt=0)


class DeprecationWarning_(BaseModel):
    """Underscore suffix to avoid shadowing Python's DeprecationWarning."""

    model_config = ConfigDict(extra="forbid")

    input_alias: str
    resolved_to_primary: str
    note: Optional[str] = None


class ReleasePins(BaseModel):
    """Manifest IDs that pin every authoritative source consulted."""

    model_config = ConfigDict(extra="forbid")

    resolver_release: str = Field(
        ..., pattern=r"^resolver_v[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?$"
    )
    hgnc: Optional[str] = None
    ensembl: Optional[str] = None
    uniprot: Optional[str] = None
    ncbi_gene: Optional[str] = None
    mygene_metadata: Optional[str] = None


class InputDescriptor(BaseModel):
    """The original user input, preserved for audit and round-trip."""

    model_config = ConfigDict(extra="forbid")

    value: str
    interpreted_as: str = Field(
        ...,
        # Mirrors the JSON Schema enum.
    )

    @field_validator("interpreted_as")
    @classmethod
    def _check_kind(cls, v: str) -> str:
        allowed = {"hgnc_symbol", "hgnc_id", "ensembl_gene_id", "uniprot_accession", "entrez_id"}
        if v not in allowed:
            raise ValueError(f"interpreted_as must be one of {allowed}, got {v!r}")
        return v


class Target(BaseModel):
    """Canonical, release-pinned identifier object for a drug-discovery target.

    Produced once by skills/resolve-target-id at orchestrator entry; consumed
    verbatim by every downstream dimension. v2.0 scope is gene-level (no
    isoform / transcript resolution; no orthology).
    """

    model_config = ConfigDict(extra="forbid")

    hgnc: HGNC
    ensembl: Ensembl
    uniprot: Optional[UniProt] = None
    ncbi: Optional[NCBI] = None
    aliases_at_resolution: list[str] = Field(default_factory=list)
    deprecation_warning: Optional[DeprecationWarning_] = None
    release_pins: ReleasePins
    resolver_version: str = Field(
        ..., pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(-?[a-zA-Z][a-zA-Z0-9]*)?$"
    )
    resolved_at: datetime
    input: Optional[InputDescriptor] = None

    def fingerprint(self) -> dict:
        """Determinism fingerprint: every field except resolved_at. Two Target
        objects produced by the same resolver release for the same input
        should produce equal fingerprints."""
        d = self.model_dump(mode="json", exclude_none=True)
        d.pop("resolved_at", None)
        return d
