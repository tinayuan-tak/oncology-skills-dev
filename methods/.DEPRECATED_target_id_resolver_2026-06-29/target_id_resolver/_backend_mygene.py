"""MyGene.info live-API backend (alpha pins, resolver_v0.1.0-alpha).

Resolution path: input -> MyGene /v3/query -> Target. Per-call HTTP latency,
no local state. v1.0.0 promotes from this backend to _backend_snapshot.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import requests

from ._version import __version__
from .errors import AmbiguousInputError, NotFoundError
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

MYGENE_QUERY_URL = "https://mygene.info/v3/query"
MYGENE_FIELDS = (
    "symbol,name,HGNC,ensembl.gene,uniprot.Swiss-Prot,entrezgene,alias,locus_group,map_location"
)


def _mygene_query(q: str, max_attempts: int = 4) -> list[dict]:
    last_err: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.get(
                MYGENE_QUERY_URL,
                params={"q": q, "species": "human", "fields": MYGENE_FIELDS},
                timeout=30,
            )
            r.raise_for_status()
            return r.json().get("hits") or []
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < max_attempts:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError(f"unreachable: {last_err}")


def _mygene_query_for_input(value: str, kind: str) -> list[dict]:
    if kind == "hgnc_id":
        hgnc_int = value.split(":", 1)[1]
        return _mygene_query(f"HGNC:{hgnc_int}")
    elif kind == "ensembl_gene_id":
        ensembl_unversioned = value.split(".", 1)[0]
        return _mygene_query(f"ensembl.gene:{ensembl_unversioned}")
    elif kind == "uniprot_accession":
        return _mygene_query(f'uniprot.Swiss-Prot:"{value}"')
    elif kind == "entrez_id":
        return _mygene_query(f"entrezgene:{value}")
    else:  # hgnc_symbol
        return _mygene_query(f"symbol:{value}")


def _build_target_from_hit(
    *,
    hit: dict,
    input_value: str,
    input_kind: str,
    resolver_release: str,
    data_pins: dict,
) -> Target:
    hgnc_int = hit.get("HGNC")
    if not hgnc_int:
        raise NotFoundError(input_value)
    hgnc_id = f"HGNC:{hgnc_int}"
    primary_symbol = hit["symbol"]
    aliases = list(hit.get("alias") or [])

    deprecation = None
    if input_kind == "hgnc_symbol" and input_value.upper() != primary_symbol.upper():
        alias_set = {a.upper() for a in aliases}
        if input_value.upper() in alias_set:
            deprecation = DeprecationWarning_(
                input_alias=input_value,
                resolved_to_primary=primary_symbol,
                note=(
                    f"Input symbol {input_value!r} is recorded as a previous symbol "
                    f"or alias for {primary_symbol} (HGNC ID {hgnc_id})."
                ),
            )

    # Alpha caveat: MyGene's ensembl.gene is unversioned; we set version='0' as a sentinel.
    ensembl_obj = hit.get("ensembl") or {}
    if isinstance(ensembl_obj, list):
        ensembl_obj = ensembl_obj[0] if ensembl_obj else {}
    ensembl_gene = ensembl_obj.get("gene")
    if not ensembl_gene:
        raise NotFoundError(
            f"{input_value!r} resolved to {primary_symbol} but has no Ensembl gene mapping."
        )
    ensembl_block = Ensembl(gene_id=ensembl_gene, version="0", full=f"{ensembl_gene}.0")

    uniprot_block: Optional[UniProt] = None
    uniprot_obj = hit.get("uniprot") or {}
    swiss = uniprot_obj.get("Swiss-Prot")
    if swiss:
        if isinstance(swiss, list):
            swiss = swiss[0] if swiss else None
        if swiss:
            uniprot_block = UniProt(canonical_accession=swiss, reviewed=True)

    ncbi_block: Optional[NCBI] = None
    entrez = hit.get("entrezgene")
    if entrez is not None:
        try:
            ncbi_block = NCBI(entrez_id=int(entrez))
        except (TypeError, ValueError):
            pass

    hgnc_block = HGNC(
        id=hgnc_id,
        primary_symbol=primary_symbol,
        name=hit.get("name"),
        locus_group=hit.get("locus_group"),
        chromosome=hit.get("map_location"),
    )

    release_pins = ReleasePins(
        resolver_release=resolver_release,
        hgnc=data_pins.get("hgnc"),
        mygene_metadata=data_pins.get("mygene_metadata"),
    )

    return Target(
        hgnc=hgnc_block,
        ensembl=ensembl_block,
        uniprot=uniprot_block,
        ncbi=ncbi_block,
        aliases_at_resolution=aliases,
        deprecation_warning=deprecation,
        release_pins=release_pins,
        resolver_version=__version__,
        resolved_at=datetime.now(timezone.utc),
        input=InputDescriptor(value=input_value, interpreted_as=input_kind),
    )


def resolve_via_mygene(
    *,
    input_value: str,
    input_kind: str,
    resolver_release: str,
    data_pins: dict,
) -> Target:
    """Resolve via live MyGene.info /v3/query. Public entry from core.resolve()
    when pin.dispatch == 'live_mygene'."""
    hits = _mygene_query_for_input(input_value, input_kind)

    if not hits and input_kind == "hgnc_symbol":
        hits = _mygene_query(input_value)

    if not hits:
        raise NotFoundError(input_value)

    hgnc_hits = [h for h in hits if h.get("HGNC")]
    if not hgnc_hits:
        raise NotFoundError(input_value)

    by_hgnc: dict[str, dict] = {}
    for h in hgnc_hits:
        hid = str(h["HGNC"])
        if hid not in by_hgnc:
            by_hgnc[hid] = h

    if len(by_hgnc) > 1:
        if input_kind == "hgnc_symbol":
            exact = [
                h for h in by_hgnc.values()
                if h.get("symbol", "").upper() == input_value.upper()
            ]
            if len(exact) == 1:
                return _build_target_from_hit(
                    hit=exact[0],
                    input_value=input_value,
                    input_kind=input_kind,
                    resolver_release=resolver_release,
                    data_pins=data_pins,
                )
        raise AmbiguousInputError(input_value, list(by_hgnc.values()))

    [chosen] = by_hgnc.values()
    return _build_target_from_hit(
        hit=chosen,
        input_value=input_value,
        input_kind=input_kind,
        resolver_release=resolver_release,
        data_pins=data_pins,
    )
