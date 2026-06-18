"""Core resolver — maps an input identifier to a canonical Target object.

Dispatches to one of two backends based on the resolver-release pin:

  pin.dispatch == "live_mygene"  ->  _backend_mygene.resolve_via_mygene()
                                     (alpha pins; runtime API; no local state)
  pin.dispatch == "snapshot"      ->  _backend_snapshot.resolve_via_snapshot()
                                     (production pins; in-memory SnapshotIndex)

Both backends produce the same Target schema; the choice is configuration.

Public API:
    resolve(input_value, resolver_release=None) -> Target
    resolve_batch(inputs, resolver_release=None) -> list[Target | None]

For dispatch=='snapshot', the SnapshotIndex is built lazily on first resolve()
call per resolver-release and cached at the module level. Cold-start cost
hits the first caller; subsequent calls are dictionary lookups.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Optional

import yaml

from . import _backend_mygene, _backend_snapshot
from ._index import SnapshotIndex, SnapshotPaths
from .errors import AmbiguousInputError, NotFoundError, ResolverPinError
from .schema import Target


DEFAULT_RESOLVER_RELEASE = "resolver_v0.1.0-alpha"

_THIS_DIR = Path(__file__).resolve().parent
_RESOLVER_RELEASES_DIR = _THIS_DIR.parent.parent.parent / "resolver-releases"

# Module-level cache: resolver_release -> SnapshotIndex. First snapshot-mode
# resolve() builds it; subsequent calls reuse.
_INDEX_CACHE: dict[str, SnapshotIndex] = {}

# Where the resolver looks for locally-cached snapshot files. Override via
# TARGET_ID_RESOLVER_CACHE_DIR. Default: $HOME/.cache/target-id-resolver/.
_DEFAULT_CACHE_DIR = Path(
    os.environ.get(
        "TARGET_ID_RESOLVER_CACHE_DIR",
        str(Path.home() / ".cache" / "target-id-resolver"),
    )
)


# ---------------------------------------------------------------------------
# Resolver-release pin loader
# ---------------------------------------------------------------------------


def _load_resolver_release(release_id: str) -> dict:
    """Load a resolver-release YAML by ID, e.g. 'resolver_v1.0.0' or
    'resolver_v0.1.0-alpha'."""
    fname = release_id
    if fname.startswith("resolver_v"):
        fname = "v" + fname[len("resolver_v"):]
    elif fname.startswith("resolver_"):
        fname = fname[len("resolver_"):]
    if not fname.endswith(".yaml"):
        fname += ".yaml"
    path = _RESOLVER_RELEASES_DIR / fname
    if not path.is_file():
        raise ResolverPinError(
            f"Resolver release pin not found: {path} (input: {release_id!r}). "
            f"Looked under {_RESOLVER_RELEASES_DIR}."
        )
    return yaml.safe_load(path.read_text())


# ---------------------------------------------------------------------------
# Input classification (identical to alpha)
# ---------------------------------------------------------------------------

_HGNC_ID_RE = re.compile(r"^HGNC:[0-9]+$")
_ENSEMBL_GENE_RE = re.compile(r"^ENSG[0-9]+(\.[0-9]+)?$")
_UNIPROT_ACC_RE = re.compile(r"^[OPQ][0-9][A-Z0-9]{3}[0-9]$|^[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2}$")
_ENTREZ_INT_RE = re.compile(r"^[0-9]+$")
_HGNC_SYMBOL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


def _classify_input(value: str) -> str:
    """Return one of: hgnc_id, ensembl_gene_id, uniprot_accession, entrez_id,
    hgnc_symbol."""
    v = value.strip()
    if _HGNC_ID_RE.match(v):
        return "hgnc_id"
    if _ENSEMBL_GENE_RE.match(v):
        return "ensembl_gene_id"
    if _ENTREZ_INT_RE.match(v):
        return "entrez_id"
    if _UNIPROT_ACC_RE.match(v) and _HGNC_SYMBOL_RE.match(v) is None:
        return "uniprot_accession"
    if _UNIPROT_ACC_RE.match(v) and any(c.isdigit() for c in v):
        return "uniprot_accession"
    return "hgnc_symbol"


# ---------------------------------------------------------------------------
# Snapshot index resolution
# ---------------------------------------------------------------------------


def _local_paths_for_pin(pin: dict) -> SnapshotPaths:
    """Build SnapshotPaths from a resolver-release pin's data_pins block,
    looking up each manifest_id under the local cache directory.

    Convention: cache dir contains {manifest_id}/{path_in_manifest} layout
    that mirrors the catalog. Tests and orchestrators pre-populate the cache
    via their own loaders; this function does NOT download from S3 itself
    (keep dependencies minimal — boto3 is only needed for cache population).
    """
    data_pins = pin.get("data_pins") or {}
    cache = _DEFAULT_CACHE_DIR

    def _local(manifest_id: str, expected_filename: str) -> Path:
        path = cache / manifest_id / expected_filename
        if not path.is_file():
            raise ResolverPinError(
                f"Snapshot file missing in local cache: {path}\n"
                f"Populate the cache by syncing s3://onc-compbio/data-catalog/sources/... "
                f"to {cache}/{{manifest_id}}/  before invoking the resolver in snapshot mode."
            )
        return path

    hgnc_id = data_pins.get("hgnc")
    ensembl_id = data_pins.get("ensembl")
    uniprot_id = data_pins.get("uniprot")
    ncbi_id = data_pins.get("ncbi_gene")
    if not all([hgnc_id, ensembl_id, uniprot_id]):
        raise ResolverPinError(
            f"Snapshot dispatch requires data_pins for hgnc, ensembl, uniprot. "
            f"Got: {data_pins}"
        )

    # File names follow each source's manifest. We hard-code the expected
    # name pattern per source.
    hgnc_path = _local(hgnc_id, _hgnc_filename(hgnc_id))
    ensembl_path = _local(ensembl_id, _ensembl_filename(ensembl_id))
    uniprot_path = _local(uniprot_id, "uniprot_sprot_human.xml.gz")
    ncbi_path: Optional[Path] = None
    if ncbi_id:
        # NCBI gene_info.gz is only loaded lazily; cache presence is optional.
        candidate = cache / ncbi_id / "gene_info.gz"
        if candidate.is_file():
            ncbi_path = candidate

    return SnapshotPaths(
        hgnc_tsv=hgnc_path,
        ensembl_id_map_tsv=ensembl_path,
        uniprot_xml=uniprot_path,
        ncbi_gene_info_gz=ncbi_path,
    )


def _hgnc_filename(manifest_id: str) -> str:
    """HGNC complete-set TSV uses date-stub naming. The manifest ID encodes
    the quarterly slug (e.g., 'hgnc-2026-q2') and the file is
    'hgnc_complete_set_{YYYY-MM-DD}.txt'. We map quarter -> day-01."""
    # manifest_id format: 'hgnc-{YYYY}-{q}'
    m = re.match(r"^hgnc-(\d{4})-q([1-4])$", manifest_id)
    if not m:
        raise ResolverPinError(f"Unrecognized HGNC manifest id: {manifest_id}")
    year = int(m.group(1))
    quarter = int(m.group(2))
    month = {1: 1, 2: 4, 3: 7, 4: 10}[quarter]
    return f"hgnc_complete_set_{year:04d}-{month:02d}-01.txt"


def _ensembl_filename(manifest_id: str) -> str:
    """Ensembl ID-map TSV file name encodes the release number. Manifest ID
    format: 'ensembl-id-mapping-release-{N}-snapshot-{YYYY-MM-DD}'."""
    m = re.match(r"^ensembl-id-mapping-release-(\d+)-snapshot-", manifest_id)
    if not m:
        raise ResolverPinError(f"Unrecognized Ensembl manifest id: {manifest_id}")
    release = m.group(1)
    return f"hsapiens_gene_id_map_release-{release}.tsv"


def _get_index(release_id: str, pin: dict) -> SnapshotIndex:
    """Build (or reuse from cache) the SnapshotIndex for this resolver release."""
    if release_id in _INDEX_CACHE:
        return _INDEX_CACHE[release_id]
    paths = _local_paths_for_pin(pin)
    index = SnapshotIndex(paths)
    _INDEX_CACHE[release_id] = index
    return index


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve(input_value: str, resolver_release: Optional[str] = None) -> Target:
    """Resolve a single identifier to a canonical Target.

    Dispatches on pin.dispatch:
      'live_mygene'  -> _backend_mygene  (no local state; HTTP per call)
      'snapshot'     -> _backend_snapshot (in-memory index; one-time load)

    Args:
        input_value: HGNC symbol, HGNC ID (HGNC:NNNN), Ensembl gene ID
            (versioned or unversioned), UniProt canonical accession, or NCBI
            Entrez gene ID (integer-string).
        resolver_release: Resolver release ID, e.g. 'resolver_v1.0.0' or
            'resolver_v0.1.0-alpha'. Defaults to DEFAULT_RESOLVER_RELEASE.

    Raises:
        NotFoundError: if no gene matches.
        AmbiguousInputError: if multiple HGNC entries match and none is
            unambiguously canonical.
        ResolverPinError: if the resolver_release pin file is missing or
            malformed, or (for snapshot dispatch) the local cache is missing
            required files.
    """
    release = resolver_release or DEFAULT_RESOLVER_RELEASE
    pin = _load_resolver_release(release)
    data_pins = pin.get("data_pins") or {}
    dispatch = pin.get("behavior", {}).get("dispatch", pin.get("dispatch"))

    kind = _classify_input(input_value)

    if dispatch == "live_mygene":
        return _backend_mygene.resolve_via_mygene(
            input_value=input_value,
            input_kind=kind,
            resolver_release=release,
            data_pins=data_pins,
        )
    elif dispatch == "snapshot":
        index = _get_index(release, pin)
        return _backend_snapshot.resolve_via_snapshot(
            input_value=input_value,
            input_kind=kind,
            resolver_release=release,
            data_pins=data_pins,
            index=index,
        )
    else:
        raise ResolverPinError(
            f"Unknown or missing dispatch mode in pin {release!r}: {dispatch!r}. "
            f"Expected 'live_mygene' or 'snapshot'."
        )


def resolve_batch(
    inputs: Iterable[str],
    resolver_release: Optional[str] = None,
) -> list[Optional[Target]]:
    """Resolve many identifiers. Returns a list aligned with `inputs`; entries
    are None for inputs that raised NotFoundError or AmbiguousInputError."""
    out: list[Optional[Target]] = []
    for v in inputs:
        try:
            out.append(resolve(v, resolver_release=resolver_release))
        except (NotFoundError, AmbiguousInputError):
            out.append(None)
    return out
