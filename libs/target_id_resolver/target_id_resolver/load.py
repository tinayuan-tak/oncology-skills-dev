"""load.py — parse pinned reference snapshots into in-memory records.

Four parsers, each consuming the artifact mirrored by a Phase A pull script:

  load_hgnc_tsv(path)            -> dict[hgnc_id, HGNCRecord]
  load_uniprot_xml(path)         -> dict[accession, UniProtRecord]
  load_ensembl_id_map_tsv(path)  -> dict[ensembl_gene_id, EnsemblRecord]
  load_ncbi_gene_info(path)      -> dict[entrez_id, NCBIRecord]

Each parser returns a dict keyed on its source's primary key. The four dicts
are composed by _index.py into the cross-reference indices the resolver
queries at lookup time.

Performance:
  HGNC TSV parses in ~1s for ~45K rows.
  Ensembl BioMart TSV parses in ~0.5s for 86K rows.
  NCBI gene_info filtered to human (tax_id=9606) parses in ~3s; full file is
    ~50M rows, but gz streaming + early continue keeps memory flat.
  UniProt XML is the most expensive: streamed iterparse over ~600MB
    decompressed, takes ~30s for ~21K human entries. We only extract the
    fields the resolver actually needs (accession, name, gene_name) so the
    parser stays lean.

Files are read as gzip-compressed where their path ends in '.gz', otherwise
plain text.
"""

from __future__ import annotations

import csv
import gzip
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator
import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# Record types — flat dataclasses for cheap allocation. Field names match
# the underlying source columns so a reader can verify against the upstream
# without translation.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HGNCRecord:
    hgnc_id: str                    # 'HGNC:11998'
    symbol: str                     # 'TP53'
    name: str                       # 'tumor protein p53'
    locus_group: str                # 'protein-coding gene'
    location: str                   # '17p13.1'
    aliases: tuple[str, ...]        # ('P53', 'BCC7', 'LFS1', ...)  — current aliases
    prev_symbols: tuple[str, ...]   # ()                            — previous symbols
    entrez_id: str | None           # '7157' or None
    ensembl_gene_id: str | None     # 'ENSG00000141510' or None
    refseq_accession: str | None    # 'NM_000546' or None
    uniprot_ids: tuple[str, ...]    # ('P04637',)                   — pipe-separated upstream


@dataclass(frozen=True)
class UniProtRecord:
    accession: str                  # canonical accession 'P04637'
    name: str                       # entry name 'P53_HUMAN'
    reviewed: bool                  # True for Swiss-Prot (always True for our mirror)
    gene_name: str | None           # primary gene name 'TP53' (from <gene><name type="primary">)
    full_protein_name: str | None   # 'Cellular tumor antigen p53'


@dataclass(frozen=True)
class EnsemblRecord:
    gene_id: str                    # 'ENSG00000141510'
    version: str                    # '18'
    full: str                       # 'ENSG00000141510.18'
    hgnc_id: str | None             # 'HGNC:11998' or None
    hgnc_symbol: str | None         # 'TP53' or None


@dataclass(frozen=True)
class NCBIRecord:
    entrez_id: str                  # '7157'
    symbol: str                     # 'TP53'
    synonyms: tuple[str, ...]       # ('P53', 'BCC7', ...)
    hgnc_id: str | None             # 'HGNC:11998' or None (parsed from dbXrefs)
    ensembl_gene_id: str | None     # 'ENSG00000141510' or None (parsed from dbXrefs)
    type_of_gene: str               # 'protein-coding'
    description: str                # 'tumor protein p53'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open(path: str | Path, mode: str = "rt") -> io.TextIOBase:
    """Open as text, transparently gz-decompressing when path ends in '.gz'."""
    p = Path(path)
    if p.suffix == ".gz":
        return gzip.open(p, mode, encoding="utf-8", errors="replace")
    return open(p, mode, encoding="utf-8", errors="replace")


def _split_pipe(field_value: str) -> tuple[str, ...]:
    """Split an HGNC/NCBI pipe-separated alias field. Strip surrounding
    quotes (HGNC quotes fields containing pipes). Empty -> ()."""
    if not field_value:
        return ()
    s = field_value.strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    if not s or s == "-":
        return ()
    return tuple(part.strip() for part in s.split("|") if part.strip())


# ---------------------------------------------------------------------------
# HGNC complete-set TSV
# ---------------------------------------------------------------------------


# Column indices in the HGNC complete set TSV. Verified against the
# 2026-Q2 quarterly snapshot header row at parse time; a mismatch
# triggers an explicit error so silent column drift doesn't corrupt
# downstream resolution.
HGNC_REQUIRED_COLUMNS = (
    "hgnc_id",
    "symbol",
    "name",
    "locus_group",
    "location",
    "alias_symbol",
    "prev_symbol",
    "entrez_id",
    "ensembl_gene_id",
    "refseq_accession",
    "uniprot_ids",
)


def load_hgnc_tsv(path: str | Path) -> dict[str, HGNCRecord]:
    """Parse HGNC complete-set TSV and return {hgnc_id: HGNCRecord}.

    The TSV has 54 columns and a header row. We reach for fields by name,
    not index, so HGNC adding columns in the future doesn't break parsing.
    """
    out: dict[str, HGNCRecord] = {}
    with _open(path) as fh:
        reader = csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
        missing = [c for c in HGNC_REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                f"HGNC TSV missing required columns: {missing}. "
                f"Got header: {reader.fieldnames}"
            )
        for row in reader:
            hgnc_id = row["hgnc_id"]
            if not hgnc_id:
                continue
            out[hgnc_id] = HGNCRecord(
                hgnc_id=hgnc_id,
                symbol=row["symbol"],
                name=row["name"],
                locus_group=row["locus_group"],
                location=row["location"],
                aliases=_split_pipe(row["alias_symbol"]),
                prev_symbols=_split_pipe(row["prev_symbol"]),
                entrez_id=row["entrez_id"] or None,
                ensembl_gene_id=row["ensembl_gene_id"] or None,
                refseq_accession=row["refseq_accession"] or None,
                uniprot_ids=_split_pipe(row["uniprot_ids"]),
            )
    return out


# ---------------------------------------------------------------------------
# UniProt Swiss-Prot human XML
# ---------------------------------------------------------------------------


# UniProt's current XML namespace is HTTPS (verified against
# uniprot_sprot_human.xml.gz from current_release on 2026-06-18).
# Earlier docs cited http://uniprot.org/uniprot — don't trust those.
_UNIPROT_NS = "{https://uniprot.org/uniprot}"


def _iter_uniprot_entries(path: str | Path) -> Iterator[ET.Element]:
    """Stream UniProt XML entries via iterparse, clearing each as we go to
    keep memory flat. Handles gz-compressed input transparently."""
    p = Path(path)
    fh: io.IOBase
    if p.suffix == ".gz":
        fh = gzip.open(p, "rb")
    else:
        fh = open(p, "rb")
    try:
        for event, elem in ET.iterparse(fh, events=("end",)):
            if elem.tag == f"{_UNIPROT_NS}entry":
                yield elem
                elem.clear()
    finally:
        fh.close()


def load_uniprot_xml(path: str | Path) -> dict[str, UniProtRecord]:
    """Parse UniProt Swiss-Prot human XML and return {accession: UniProtRecord}.

    Streams via iterparse so memory stays flat regardless of file size.
    Indexes ALL accessions (canonical + secondary) to the canonical record,
    so a query by either form resolves the same UniProtRecord.
    """
    out: dict[str, UniProtRecord] = {}
    for entry in _iter_uniprot_entries(path):
        # <accession> elements; first is canonical, rest are secondary.
        accessions = [a.text for a in entry.findall(f"{_UNIPROT_NS}accession") if a.text]
        if not accessions:
            continue
        canonical = accessions[0]

        # Entry name e.g. P53_HUMAN.
        name_el = entry.find(f"{_UNIPROT_NS}name")
        entry_name = name_el.text if name_el is not None else canonical

        # Primary gene name from <gene><name type="primary">.
        gene_name: str | None = None
        for g in entry.findall(f"{_UNIPROT_NS}gene"):
            for n in g.findall(f"{_UNIPROT_NS}name"):
                if n.get("type") == "primary":
                    gene_name = n.text
                    break
            if gene_name:
                break

        # Recommended full protein name from <protein><recommendedName><fullName>.
        full_protein_name: str | None = None
        prot = entry.find(f"{_UNIPROT_NS}protein")
        if prot is not None:
            rec = prot.find(f"{_UNIPROT_NS}recommendedName")
            if rec is not None:
                fn = rec.find(f"{_UNIPROT_NS}fullName")
                if fn is not None:
                    full_protein_name = fn.text

        record = UniProtRecord(
            accession=canonical,
            name=entry_name or canonical,
            reviewed=True,
            gene_name=gene_name,
            full_protein_name=full_protein_name,
        )
        # Index ALL accessions to the same record so secondary accessions
        # resolve correctly (e.g., P04637-1 isoform queries fall through;
        # we don't index isoforms in v1.0.0 but secondary accessions are
        # different from isoforms — they're alternate canonicals).
        for acc in accessions:
            out[acc] = record
    return out


# ---------------------------------------------------------------------------
# Ensembl BioMart ID-mapping TSV
# ---------------------------------------------------------------------------


# BioMart's TSV header. Verified at parse time.
ENSEMBL_REQUIRED_COLUMNS = (
    "Gene stable ID",
    "Gene stable ID version",
    "HGNC ID",
    "HGNC symbol",
)


def load_ensembl_id_map_tsv(path: str | Path) -> dict[str, EnsemblRecord]:
    """Parse Ensembl BioMart ID-mapping TSV and return {gene_id: EnsemblRecord}.

    Many rows have empty hgnc_id (pseudogenes, non-coding RNAs, novel genes).
    The resolver tolerates these via no_hgnc_mapping resolution status; we
    keep them in the index so an Ensembl-ID input still resolves to a
    Target with the gene_id and version, just without HGNC cross-reference.
    """
    out: dict[str, EnsemblRecord] = {}
    with _open(path) as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        missing = [c for c in ENSEMBL_REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                f"Ensembl BioMart TSV missing required columns: {missing}. "
                f"Got header: {reader.fieldnames}"
            )
        for row in reader:
            gene_id = row["Gene stable ID"]
            full = row["Gene stable ID version"]
            if not gene_id or not full:
                continue
            # full looks like 'ENSG00000141510.18'; extract version.
            if "." not in full:
                continue
            _, version = full.rsplit(".", 1)
            out[gene_id] = EnsemblRecord(
                gene_id=gene_id,
                version=version,
                full=full,
                hgnc_id=row["HGNC ID"] or None,
                hgnc_symbol=row["HGNC symbol"] or None,
            )
    return out


# ---------------------------------------------------------------------------
# NCBI gene_info.gz
# ---------------------------------------------------------------------------


# gene_info column order. The first column has a leading '#' character.
NCBI_REQUIRED_COLUMNS = (
    "#tax_id",
    "GeneID",
    "Symbol",
    "Synonyms",
    "dbXrefs",
    "type_of_gene",
    "description",
)

# Filter to human only (tax_id 9606).
HUMAN_TAX_ID = "9606"


def _parse_ncbi_dbxrefs(dbxrefs: str) -> tuple[str | None, str | None]:
    """Parse the dbXrefs column (pipe-separated key:value pairs) and return
    (hgnc_id, ensembl_gene_id). Format example:
      'MIM:190070|HGNC:HGNC:6407|Ensembl:ENSG00000133703|AllianceGenome:HGNC:6407'
    Note HGNC's value is itself 'HGNC:6407' so the full token is 'HGNC:HGNC:6407'.
    """
    if not dbxrefs or dbxrefs == "-":
        return None, None
    hgnc: str | None = None
    ensembl: str | None = None
    for token in dbxrefs.split("|"):
        # Tokens: 'KEY:VALUE' but VALUE may itself contain ':'. So split on first ':' only.
        if ":" not in token:
            continue
        key, _, value = token.partition(":")
        if key == "HGNC" and value.startswith("HGNC:") and hgnc is None:
            hgnc = value
        elif key == "Ensembl" and value.startswith("ENSG") and ensembl is None:
            ensembl = value
    return hgnc, ensembl


def load_ncbi_gene_info(path: str | Path, tax_id: str = HUMAN_TAX_ID) -> dict[str, NCBIRecord]:
    """Parse NCBI gene_info.gz, filtered to one tax_id, and return
    {entrez_id: NCBIRecord}.

    Default tax_id 9606 (human). The full upstream file covers all species
    (~50M rows, ~12 GB decompressed); filtering at parse time keeps memory
    flat — only ~80K human rows survive."""
    out: dict[str, NCBIRecord] = {}
    with _open(path) as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        missing = [c for c in NCBI_REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                f"NCBI gene_info missing required columns: {missing}. "
                f"Got header: {reader.fieldnames}"
            )
        for row in reader:
            if row["#tax_id"] != tax_id:
                continue
            entrez_id = row["GeneID"]
            if not entrez_id:
                continue
            hgnc_id, ensembl_gene_id = _parse_ncbi_dbxrefs(row.get("dbXrefs", ""))
            out[entrez_id] = NCBIRecord(
                entrez_id=entrez_id,
                symbol=row["Symbol"],
                synonyms=_split_pipe(row["Synonyms"]),
                hgnc_id=hgnc_id,
                ensembl_gene_id=ensembl_gene_id,
                type_of_gene=row["type_of_gene"],
                description=row["description"],
            )
    return out
