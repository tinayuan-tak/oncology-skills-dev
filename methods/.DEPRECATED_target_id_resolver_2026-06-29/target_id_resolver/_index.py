"""_index.py — in-memory cross-reference indices over the four reference snapshots.

Built once at SnapshotIndex.__init__ (eager: HGNC + Ensembl + UniProt) and
lazily extended on first NCBI-specific query (NCBI gene_info parses ~4 min
on the full human-filter pass; deferring keeps the resolver's cold-start
under 30 seconds for the common case).

Lookup contract — given any input identifier, return the canonical HGNCRecord
(or None if unmappable). All cross-references for a Target object can be
derived from the HGNC record + its companion Ensembl/UniProt records, joined
by hgnc_id.

Case-insensitive matching for symbols, aliases, and previous symbols.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .load import (
    HGNCRecord,
    EnsemblRecord,
    UniProtRecord,
    NCBIRecord,
    load_hgnc_tsv,
    load_ensembl_id_map_tsv,
    load_uniprot_xml,
    load_ncbi_gene_info,
)


@dataclass
class SnapshotPaths:
    """Local paths to pinned snapshot files. Resolver code consumes these
    paths; downloading from S3 to local cache is the caller's responsibility
    (orchestrator setup, fixture, test, etc.)."""

    hgnc_tsv: Path
    ensembl_id_map_tsv: Path
    uniprot_xml: Path
    ncbi_gene_info_gz: Optional[Path] = None  # optional: only needed for some queries


class SnapshotIndex:
    """In-memory cross-reference index built from pinned snapshots.

    Construction is eager for HGNC/Ensembl/UniProt and lazy for NCBI:
        idx = SnapshotIndex(paths)              # ~10s
        idx.lookup_by_hgnc_id("HGNC:6407")      # immediate
        idx.lookup_by_entrez_id("3845")         # immediate (HGNC carries entrez)
        idx.lookup_by_entrez_id("999999")       # triggers lazy NCBI load on first miss
    """

    def __init__(self, paths: SnapshotPaths) -> None:
        self._paths = paths

        # --- Eager loads ---
        self._hgnc: dict[str, HGNCRecord] = load_hgnc_tsv(paths.hgnc_tsv)
        self._ensembl: dict[str, EnsemblRecord] = load_ensembl_id_map_tsv(paths.ensembl_id_map_tsv)
        self._uniprot: dict[str, UniProtRecord] = load_uniprot_xml(paths.uniprot_xml)

        # --- Lazy ---
        self._ncbi: Optional[dict[str, NCBIRecord]] = None

        # --- Derived indices over HGNC ---
        # Symbol/alias/prev → hgnc_id, all case-folded for case-insensitive lookup.
        self._symbol_to_hgnc: dict[str, str] = {}
        self._alias_to_hgnc: dict[str, list[str]] = {}     # alias may map to multiple HGNCs
        self._prev_to_hgnc: dict[str, list[str]] = {}      # prev_symbol may map to multiple HGNCs (rare)
        self._entrez_to_hgnc: dict[str, str] = {}
        self._ensembl_to_hgnc: dict[str, str] = {}
        self._uniprot_to_hgnc: dict[str, str] = {}

        for hgnc_id, rec in self._hgnc.items():
            if rec.symbol:
                self._symbol_to_hgnc[rec.symbol.upper()] = hgnc_id
            for a in rec.aliases:
                self._alias_to_hgnc.setdefault(a.upper(), []).append(hgnc_id)
            for p in rec.prev_symbols:
                self._prev_to_hgnc.setdefault(p.upper(), []).append(hgnc_id)
            if rec.entrez_id:
                self._entrez_to_hgnc[rec.entrez_id] = hgnc_id
            if rec.ensembl_gene_id:
                self._ensembl_to_hgnc[rec.ensembl_gene_id] = hgnc_id
            for u in rec.uniprot_ids:
                self._uniprot_to_hgnc[u] = hgnc_id

    # ------------------------------------------------------------------
    # Lazy NCBI
    # ------------------------------------------------------------------

    def _ensure_ncbi_loaded(self) -> None:
        """Trigger NCBI gene_info parse on first edge-case query. ~4 min on
        full file; one-shot per process. Most resolver queries never hit this."""
        if self._ncbi is not None:
            return
        if self._paths.ncbi_gene_info_gz is None:
            self._ncbi = {}
            return
        self._ncbi = load_ncbi_gene_info(self._paths.ncbi_gene_info_gz)

    # ------------------------------------------------------------------
    # Public lookups — return canonical HGNCRecord (or None)
    # ------------------------------------------------------------------

    def lookup_by_hgnc_id(self, hgnc_id: str) -> Optional[HGNCRecord]:
        return self._hgnc.get(hgnc_id)

    def lookup_by_symbol(self, symbol: str) -> Optional[HGNCRecord]:
        """Exact (case-insensitive) match on HGNC primary symbol."""
        hgnc_id = self._symbol_to_hgnc.get(symbol.upper())
        return self._hgnc.get(hgnc_id) if hgnc_id else None

    def lookup_by_alias(self, alias: str) -> list[HGNCRecord]:
        """Case-insensitive match on alias_symbol or prev_symbol. Returns
        ALL matches — caller decides ambiguity policy."""
        key = alias.upper()
        hgnc_ids: list[str] = []
        hgnc_ids.extend(self._alias_to_hgnc.get(key, []))
        for h in self._prev_to_hgnc.get(key, []):
            if h not in hgnc_ids:
                hgnc_ids.append(h)
        return [self._hgnc[h] for h in hgnc_ids if h in self._hgnc]

    def lookup_by_ensembl_gene_id(self, ensembl_gene_id: str) -> Optional[HGNCRecord]:
        """Look up by Ensembl gene ID (versioned or unversioned)."""
        # Strip version suffix if present
        unversioned = ensembl_gene_id.split(".", 1)[0]
        hgnc_id = self._ensembl_to_hgnc.get(unversioned)
        return self._hgnc.get(hgnc_id) if hgnc_id else None

    def lookup_by_uniprot_accession(self, accession: str) -> Optional[HGNCRecord]:
        hgnc_id = self._uniprot_to_hgnc.get(accession)
        return self._hgnc.get(hgnc_id) if hgnc_id else None

    def lookup_by_entrez_id(self, entrez_id: str) -> Optional[HGNCRecord]:
        """Try HGNC's entrez xref first; fall through to NCBI gene_info on miss."""
        hgnc_id = self._entrez_to_hgnc.get(entrez_id)
        if hgnc_id:
            return self._hgnc.get(hgnc_id)
        # Fall through: NCBI gene_info may have a record HGNC doesn't xref.
        self._ensure_ncbi_loaded()
        ncbi_rec = self._ncbi.get(entrez_id) if self._ncbi else None
        if ncbi_rec and ncbi_rec.hgnc_id:
            return self._hgnc.get(ncbi_rec.hgnc_id)
        return None

    # ------------------------------------------------------------------
    # Companion record fetchers (used to populate Target sub-blocks)
    # ------------------------------------------------------------------

    def ensembl_record_for(self, hgnc_record: HGNCRecord) -> Optional[EnsemblRecord]:
        """Look up the Ensembl record for an HGNC record (using HGNC's
        ensembl_gene_id xref). Returns None if HGNC doesn't carry an Ensembl
        ID OR Ensembl's mirror doesn't have the gene_id."""
        if not hgnc_record.ensembl_gene_id:
            return None
        return self._ensembl.get(hgnc_record.ensembl_gene_id)

    def uniprot_record_for(self, hgnc_record: HGNCRecord) -> Optional[UniProtRecord]:
        """First UniProt accession from HGNC's uniprot_ids list; None if
        HGNC has no UniProt xref OR the accession isn't in the human Swiss-Prot
        mirror (e.g., HGNC sometimes lists TrEMBL accessions for less-curated
        genes)."""
        for acc in hgnc_record.uniprot_ids:
            rec = self._uniprot.get(acc)
            if rec is not None:
                return rec
        return None

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, int]:
        return {
            "hgnc_records": len(self._hgnc),
            "ensembl_records": len(self._ensembl),
            "uniprot_records": len(self._uniprot),
            "ncbi_records": len(self._ncbi) if self._ncbi is not None else 0,
            "symbol_index": len(self._symbol_to_hgnc),
            "alias_index": len(self._alias_to_hgnc),
            "prev_symbol_index": len(self._prev_to_hgnc),
            "entrez_index": len(self._entrez_to_hgnc),
            "ensembl_index": len(self._ensembl_to_hgnc),
            "uniprot_index": len(self._uniprot_to_hgnc),
        }
