"""ppi_interactome — per-target protein-protein interaction context (STRING + CORUM).

The INDICATION-INDEPENDENT interactome view of a target: how connected is this protein, and is it a
member of any stable protein complex. Two biologically-distinct signals:
  - STRING functional interaction NETWORK: n high-confidence interactors (combined_score >= 700) +
    top partners. "How many proteins does it functionally interact with."
  - CORUM stable COMPLEX membership: which named complexes (proteasome, mediator, BAF, ...) the target
    belongs to. A distinct, stronger signal — complex members carry functional identity + are often
    harder to drug in isolation.

Target-intrinsic (cancer-independent). Consumed by the target-intrinsic dossier. Descriptive, no verdict.

Substrate (pre-catalogued on S3):
  - string-v12-human-snapshot-2026-06-30: 9606.protein.links.v12.0.txt.gz (scored edges, ENSP ids) +
    9606.protein.info.v12.0.txt.gz (string_protein_id <-> preferred_name; SELF-CONTAINED symbol map).
  - corum-5.3: corum_uniprot.txt (UniProtKB_accession -> corum_id) + corum_complete.txt (corum_id ->
    complex name). Target symbol -> UniProt AC via a resolver sidecar.

BioGRID physical-interaction detail is a documented v2 enrichment (180MB tab3, no resolver sidecar).

Runtime: STRING info map is lru-cached (small); the 83MB links file is STREAM-FILTERED for the target's
ENSP edges only (not fully loaded); CORUM maps lru-cached. License: STRING CC-BY-4.0; CORUM CC-BY-NC-4.0.
"""
from __future__ import annotations

import gzip
import io
import os
from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import bucket_key_for, bucket_prefix_for, sidecar_bucket_key_for

METHOD_VERSION = "1.1.0"   # 1.1.0 (2026-08-05): + BioGRID experimental-physical leg
DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
STRING_MANIFEST_ID = "string-v12-human-snapshot-2026-06-30"
CORUM_MANIFEST_ID = "corum-5-3"
BIOGRID_MANIFEST_ID = "biogrid-physical-interactions-per-gene-v1"
# source-dir prefixes resolved from the manifests (single source of truth); rstrip('/')
# keeps the existing f"{PREFIX}/file" idiom byte-identical.
_STRING_PREFIX = bucket_prefix_for(STRING_MANIFEST_ID)[1].rstrip("/")
STRING_LINKS_KEY = f"{_STRING_PREFIX}/9606.protein.links.v12.0.txt.gz"
STRING_INFO_KEY = f"{_STRING_PREFIX}/9606.protein.info.v12.0.txt.gz"
_CORUM_PREFIX = bucket_prefix_for(CORUM_MANIFEST_ID)[1].rstrip("/")
CORUM_UNIPROT_KEY = f"{_CORUM_PREFIX}/corum_uniprot.txt"
CORUM_COMPLETE_KEY = f"{_CORUM_PREFIX}/corum_complete.txt"
# Reuse an existing UniProt symbol->AC resolver sidecar (CORUM's own resolution was deferred at
# ingest). CROSS-MANIFEST BORROW: this is reactome-v96's target_resolution sidecar, resolved from
# that manifest (not CORUM/STRING) — the borrow is intentional and now explicit via the manifest_id.
_UNIPROT_SIDECAR_SOURCE_MANIFEST_ID = "reactome-v96"
_, UNIPROT_SIDECAR_KEY = sidecar_bucket_key_for(_UNIPROT_SIDECAR_SOURCE_MANIFEST_ID)

STRING_HIGH_CONFIDENCE = 700   # STRING's canonical "high confidence" combined_score cutoff (0-999)

# Gene-sorted derived product (perf, 2026-08-05): pre-resolved symbol-keyed high-confidence edges,
# physically sorted by gene_symbol so a pushdown read fetches one gene's row-group(s) instead of
# streaming the 83MB links gz (~6.6s → sub-second, measured). Byte-identical output. See derive.py.
STRING_HC_PRODUCT_MANIFEST_ID = "uniprot-string-hc-edges-per-gene-v1"
_, STRING_HC_PRODUCT_KEY = bucket_key_for(STRING_HC_PRODUCT_MANIFEST_ID)

# BioGRID experimental-PHYSICAL edges product (2026-08-05): gene-sorted human physical interactions
# with per-pair distinct-publication counts. The complement to STRING's functional score — direct
# experimental physical evidence, ranked by literature depth. Symbol-keyed pushdown on gene_symbol.
_, BIOGRID_PHYSICAL_PRODUCT_KEY = bucket_key_for(BIOGRID_MANIFEST_ID)
BIOGRID_HUB_DEGREE = 50   # >= this many physical partners → physical hub (mirrors STRING's hub cut)


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _boto3_client():
    # shared client carries an adaptive-retry Config (absorbs transient S3 throttling on batch reads)
    from methods.target_id_sidecar import s3_client
    return s3_client()


@lru_cache(maxsize=1)
def _load_string_info(info_path: Optional[str] = None) -> tuple:
    """(symbol_upper -> string_id, string_id -> symbol) from 9606.protein.info. Self-contained STRING
    identifier map — no external resolver needed for the STRING side."""
    if info_path is not None:
        raw = open(info_path, "rb").read()
    else:
        _ensure_aws_profile()
        raw = _boto3_client().get_object(Bucket=S3_BUCKET, Key=STRING_INFO_KEY)["Body"].read()
    sym_to_id: dict[str, str] = {}
    id_to_sym: dict[str, str] = {}
    with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            c = line.rstrip("\n").split("\t")
            if len(c) < 2:
                continue
            sid, name = c[0].strip(), c[1].strip()
            if sid and name:
                sym_to_id.setdefault(name.upper(), sid)
                id_to_sym[sid] = name
    return sym_to_id, id_to_sym


def _string_edges_from_product(symbol: str, product_path: Optional[str] = None) -> Optional[list]:
    """FAST path (default): predicate-pushdown read of the gene-sorted high-confidence edge product
    for one source symbol. Returns [{"partner", "combined_score"}] already symbol-resolved + HC-filtered
    (the derive did the work), or None if the product is unavailable (caller falls back to the stream).

    The product is physically sorted by gene_symbol (== filter key), so this fetches the target's
    row-group(s) — dropping the ~6.6s full-links stream to sub-second. Output is byte-identical to the
    stream path's (same partners, same scores)."""
    import pyarrow.parquet as pq
    try:
        if product_path is not None:
            tbl = pq.read_table(product_path, filters=[("gene_symbol", "==", symbol)],
                                columns=["partner_symbol", "combined_score"])
        else:
            import pyarrow.fs as fs
            tbl = pq.read_table(f"{S3_BUCKET}/{STRING_HC_PRODUCT_KEY}",
                                filesystem=fs.S3FileSystem(region="us-east-1"),
                                filters=[("gene_symbol", "==", symbol)],
                                columns=["partner_symbol", "combined_score"])
    except Exception:  # noqa: BLE001 — product missing/unreadable → signal fallback to the stream path
        return None
    d = tbl.to_pandas()
    return [{"partner": p, "combined_score": int(s)}
            for p, s in zip(d["partner_symbol"].values, d["combined_score"].values)]


def _biogrid_physical_for(symbol: str, product_path: Optional[str] = None) -> Optional[list]:
    """Predicate-pushdown read of the BioGRID physical-edge product for one source symbol. Returns
    [{"partner", "n_publications", "n_experiments"}] ranked by publication evidence, or None if the
    product is unavailable (the BioGRID leg is then simply absent — the other legs still report)."""
    import pyarrow.parquet as pq
    try:
        if product_path is not None:
            tbl = pq.read_table(product_path, filters=[("gene_symbol", "==", symbol)],
                                columns=["partner_symbol", "n_publications", "n_experiments"])
        else:
            import pyarrow.fs as fs
            tbl = pq.read_table(f"{S3_BUCKET}/{BIOGRID_PHYSICAL_PRODUCT_KEY}",
                                filesystem=fs.S3FileSystem(region="us-east-1"),
                                filters=[("gene_symbol", "==", symbol)],
                                columns=["partner_symbol", "n_publications", "n_experiments"])
    except Exception:  # noqa: BLE001 — product missing/unreadable → BioGRID leg absent
        return None
    d = tbl.to_pandas()
    out = [{"partner": p, "n_publications": int(npub), "n_experiments": int(nexp)}
           for p, npub, nexp in zip(d["partner_symbol"].values, d["n_publications"].values,
                                    d["n_experiments"].values)]
    out.sort(key=lambda e: (-e["n_publications"], -e["n_experiments"]))
    return out


def _string_edges_for(string_id: str, links_path: Optional[str] = None) -> list:
    """LEGACY stream path (fallback + test fixtures): stream-filter the STRING links gz for edges
    incident to string_id (not a full load — the file is ~83MB gz / ~12M edges). Returns
    [(partner_string_id, combined_score)] with score >= threshold."""
    if links_path is not None:
        fh_bytes = open(links_path, "rb").read()
    else:
        _ensure_aws_profile()
        fh_bytes = _boto3_client().get_object(Bucket=S3_BUCKET, Key=STRING_LINKS_KEY)["Body"].read()
    prefix = string_id + " "
    out = []
    with gzip.open(io.BytesIO(fh_bytes), "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            # links are symmetric + sorted by protein1; only need lines where protein1 == target
            if not line.startswith(prefix):
                continue
            p1, p2, score = line.rstrip("\n").split(" ")
            s = int(score)
            if s >= STRING_HIGH_CONFIDENCE:
                out.append((p2, s))
    return out


@lru_cache(maxsize=1)
def _load_corum(uniprot_path: Optional[str] = None, complete_path: Optional[str] = None) -> tuple:
    """(uniprot_ac -> set(corum_id), corum_id -> complex_name)."""
    if uniprot_path is not None:
        u_raw = open(uniprot_path, "rb").read()
    else:
        _ensure_aws_profile()
        u_raw = _boto3_client().get_object(Bucket=S3_BUCKET, Key=CORUM_UNIPROT_KEY)["Body"].read()
    ac_to_complexes: dict[str, set] = {}
    for i, line in enumerate(io.StringIO(u_raw.decode("utf-8", "replace"))):
        if i == 0 and "corum_id" in line:
            continue
        c = line.rstrip("\n").split("\t")
        if len(c) < 2:
            continue
        ac, cid = c[0].strip(), c[1].strip()
        if ac and cid:
            ac_to_complexes.setdefault(ac, set()).add(cid)
    # complex id -> name from corum_complete.txt (find the name column)
    if complete_path is not None:
        comp_raw = open(complete_path, "rb").read()
    else:
        comp_raw = _boto3_client().get_object(Bucket=S3_BUCKET, Key=CORUM_COMPLETE_KEY)["Body"].read()
    cid_to_name: dict[str, str] = {}
    lines = io.StringIO(comp_raw.decode("utf-8", "replace"))
    header = lines.readline().rstrip("\n").split("\t")
    try:
        id_i = header.index("complex_id") if "complex_id" in header else header.index("corum_id")
    except ValueError:
        id_i = 0
    name_i = header.index("complex_name") if "complex_name" in header else (1 if len(header) > 1 else 0)
    for line in lines:
        c = line.rstrip("\n").split("\t")
        if len(c) > max(id_i, name_i):
            cid_to_name[c[id_i].strip()] = c[name_i].strip()
    return ac_to_complexes, cid_to_name


@lru_cache(maxsize=1)
def _load_uniprot_sidecar(sidecar_path: Optional[str] = None) -> dict:
    """HGNC symbol (UPPER) -> UniProt AC, from a resolver sidecar (for the CORUM UniProt-keyed lookup).
    Delegates to the shared resolver-sidecar loader (RAISES on read failure — an empty crosswalk would
    silently fail every CORUM lookup); the caller's CORUM block records a non-fatal note on failure so
    the STRING + BioGRID signals are unaffected."""
    from methods.target_id_sidecar import read_resolver_sidecar_map
    _ensure_aws_profile()
    return read_resolver_sidecar_map(
        S3_BUCKET, UNIPROT_SIDECAR_KEY, "hgnc_primary_symbol_at_resolution", "uniprot_canonical",
        local_path=sidecar_path)


def read_target_summary(target: str, indication: str = None,
                        info_path: Optional[str] = None, links_path: Optional[str] = None,
                        corum_uniprot_path: Optional[str] = None, corum_complete_path: Optional[str] = None,
                        sidecar_path: Optional[str] = None, biogrid_path: Optional[str] = None) -> dict:
    """Per-target PPI summary — THREE distinct signals (multi_provider_policy surface_discordance:
    reported alongside, never merged): STRING functional network + CORUM complex membership +
    BioGRID experimental-PHYSICAL interactions. `indication` unused (interactome is target-intrinsic)."""
    sym = target.strip().upper()

    # --- STRING functional network (high-confidence interactors) ---
    # FAST default: pushdown-read the gene-sorted product (symbol-keyed, pre-resolved, HC-filtered) —
    # no info-map load, no 83MB stream. Falls back to the legacy info-map + links-stream path ONLY when
    # the product is unavailable OR a links_path override is passed (test fixtures). Output identical.
    n_hc, top_interactors = 0, []
    string_id = None   # provenance (ENSP) only set on the legacy stream path; None on the product path
    product_edges = None if links_path is not None else _string_edges_from_product(sym)
    string_resolved = product_edges is not None  # product covers the STRING side even if this gene has 0 edges
    if product_edges is not None:
        product_edges.sort(key=lambda e: -e["combined_score"])
        n_hc = len(product_edges)
        top_interactors = product_edges[:15]
    else:
        # legacy stream fallback (product missing, or test fixture links_path/info_path given)
        try:
            sym_to_id, id_to_sym = _load_string_info(info_path)
            string_id = sym_to_id.get(sym)
            string_resolved = string_id is not None
            if string_id:
                edges = _string_edges_for(string_id, links_path)
                edges.sort(key=lambda e: -e[1])
                n_hc = len(edges)
                top_interactors = [{"partner": id_to_sym.get(pid, pid), "combined_score": s}
                                   for pid, s in edges[:15]]
        except Exception:  # noqa: BLE001
            string_resolved = False

    # --- CORUM complex membership ---
    complexes = []
    corum_note = None
    try:
        ac = _load_uniprot_sidecar(sidecar_path).get(sym)
        if ac:
            ac_to_complexes, cid_to_name = _load_corum(corum_uniprot_path, corum_complete_path)
            for cid in sorted(ac_to_complexes.get(ac, [])):
                complexes.append({"corum_id": cid, "complex_name": cid_to_name.get(cid, cid)})
    except ImportError:
        raise  # broken env (missing pandas/pyarrow) — never mask; the seam surfaces _live_read_error
    except Exception as e:  # noqa: BLE001 — CORUM is 1 of 3 INDEPENDENT signals: degrade it, keep
        # STRING + BioGRID, but RECORD the reason (was a silent `pass` that reported n_corum_complexes:0
        # while looking available — a transient sidecar/CORUM S3 read now leaves an honest note here).
        corum_note = f"CORUM unavailable ({type(e).__name__})"

    # --- BioGRID experimental-physical interactions (a THIRD, distinct signal) ---
    n_physical, top_physical = 0, []
    biogrid_edges = _biogrid_physical_for(sym, biogrid_path)
    biogrid_product_readable = biogrid_edges is not None   # product reachable this run
    biogrid_has_edges = bool(biogrid_edges)                # gene actually has >=1 physical partner
    if biogrid_edges:
        n_physical = len(biogrid_edges)
        top_physical = biogrid_edges[:15]

    # data_unavailable only when the gene is absent from ALL three sources (no STRING edges, no CORUM
    # complex, no BioGRID physical edge). An empty-but-readable BioGRID product does NOT count as
    # resolved — a gene with zero physical partners is still "unknown to BioGRID", not "measured".
    if not string_resolved and not complexes and not biogrid_has_edges:
        return _empty("target_not_in_string_or_corum_or_biogrid")

    # interactome_class from the STRING high-confidence degree
    if n_hc >= 50:
        interactome_class = "hub"
    elif n_hc >= 10:
        interactome_class = "connected"
    elif n_hc >= 1:
        interactome_class = "sparse"
    else:
        interactome_class = "no_high_confidence_interactors"

    # physical_interactome_class from the BioGRID physical degree (distinct from the STRING-derived
    # interactome_class — reported alongside per surface_discordance, never merged).
    if n_physical >= BIOGRID_HUB_DEGREE:
        physical_interactome_class = "physical_hub"
    elif n_physical >= 10:
        physical_interactome_class = "physically_connected"
    elif n_physical >= 1:
        physical_interactome_class = "physically_sparse"
    elif biogrid_product_readable:
        physical_interactome_class = "no_physical_interactors"   # product read, gene has 0 physical edges
    else:
        physical_interactome_class = "data_unavailable"          # product unreachable this run

    return {
        "interactome_class": interactome_class,            # PRIMARY (STRING functional degree)
        "n_high_confidence_interactors": n_hc,             # STRING combined_score >= 700
        "top_interactors": top_interactors,                # [{partner, combined_score}]
        "n_corum_complexes": len(complexes),
        "corum_complexes": complexes[:15],                 # [{corum_id, complex_name}]
        "in_protein_complex": len(complexes) > 0,
        **({"corum_note": corum_note} if corum_note else {}),  # honest degradation flag (non-silent)
        # BioGRID experimental-PHYSICAL leg (distinct signal; direct evidence + literature depth)
        "physical_interactome_class": physical_interactome_class,
        "n_physical_interactors": n_physical,              # BioGRID distinct physical partners
        "top_physical_partners": top_physical,             # [{partner, n_publications, n_experiments}]
        "string_protein_id": string_id,
        "method_version": METHOD_VERSION,
        "_data_source": f"{STRING_MANIFEST_ID}+{CORUM_MANIFEST_ID}+{BIOGRID_MANIFEST_ID}",
    }


def _empty(note: str) -> dict:
    return {
        "interactome_class": "data_unavailable",
        "n_high_confidence_interactors": 0, "top_interactors": [],
        "n_corum_complexes": 0, "corum_complexes": [], "in_protein_complex": False,
        "physical_interactome_class": "data_unavailable",
        "n_physical_interactors": 0, "top_physical_partners": [],
        "string_protein_id": None, "method_version": METHOD_VERSION,
        "_data_source": f"{STRING_MANIFEST_ID}+{CORUM_MANIFEST_ID}+{BIOGRID_MANIFEST_ID}", "_data_note": note,
    }
