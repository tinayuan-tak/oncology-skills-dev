"""uniprot_protein_features.read — per-target domain architecture + protein class (UniProt-curated).

The INDICATION-INDEPENDENT domain/class view of a target: its curated domain architecture (FT DOMAIN)
and its molecular protein class(es) (mapped from UniProt keywords). Target-intrinsic; consumed by the
target-intrinsic dossier. Descriptive, no verdict.

CONSUMES the derived product uniprot-protein-features-v1 (payload + resolver sidecar), NOT the DAT.
Symbol→AC via the sidecar (never a source symbol column). A target absent from the payload has no
curated domain AND no class-bearing keyword → data_unavailable (coverage/annotation gap, not a claim).
"""
from __future__ import annotations

import io
import os
from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import bucket_prefix_for, sidecar_bucket_key_for

METHOD_VERSION = "1.1.0"   # 1.1.0 (2026-08-05): + additive InterPro domain layer (coverage-broadening)
S3_BUCKET = "onc-compbio"
DERIVED_MANIFEST_ID = "uniprot-protein-features-v1"
_PREFIX = f"data-catalog/derived/{DERIVED_MANIFEST_ID}"
PAYLOAD_KEY = f"{_PREFIX}/uniprot_protein_features_v1.parquet"
SIDECAR_KEY = f"{_PREFIX}/uniprot_protein_features_v1.target_resolution.parquet"
DEFAULT_AWS_PROFILE = "cbg"

# InterPro domain-hit product (data-catalog interpro-109-0-snapshot-2026-08-05). ADDITIVE source:
# the CURATED FT DOMAIN fields above stay authoritative + byte-stable; InterPro BROADENS domain
# coverage from 8,768 (curated) to ~15,019 domain-annotated proteins (6,445 proteins have an
# InterPro domain but NO curated FT DOMAIN). AC-keyed; pushdown on uniprot_accession.
INTERPRO_MANIFEST_ID = "interpro-109-0-snapshot-2026-08-05"
INTERPRO_KEY = (f"{bucket_prefix_for(INTERPRO_MANIFEST_ID)[1]}"
                "interpro_human_domain_hits.parquet")
# InterPro resolver sidecar resolved from the manifest's target_resolution.sidecar_s3_uri.
_, INTERPRO_SIDECAR_KEY = sidecar_bucket_key_for(INTERPRO_MANIFEST_ID)


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _read_parquet(path_or_none, bucket, key):
    import pandas as pd
    if path_or_none is not None:
        return pd.read_parquet(path_or_none)
    _ensure_aws_profile()
    # shared client: AWS_PROFILE=cbg + adaptive-retry Config (absorbs transient S3 throttling on
    # batch reads — the failure mode that silently dropped protein-domains-class on a dossier run)
    from methods.target_id_sidecar import s3_client
    body = s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


@lru_cache(maxsize=1)
def _load_indexed(payload_path: Optional[str] = None, sidecar_path: Optional[str] = None):
    """(payload_by_ac, symbol_to_ac). None if payload unavailable."""
    try:
        payload = _read_parquet(payload_path, S3_BUCKET, PAYLOAD_KEY)
    except Exception as e:  # noqa: BLE001
        # genuine absence (NoSuchKey) → honest data_unavailable (None). A broken env (missing
        # pandas/pyarrow), transient S3 (throttle/timeout), or creds error must NOT be masked as a
        # data gap — re-raise so the live-read seam surfaces _live_read_error instead of a dead axis.
        from methods.target_id_sidecar import is_definitively_absent
        if not is_definitively_absent(e):
            raise
        return None
    by_ac = {}
    for rec in payload.to_dict("records"):
        ac = str(rec.get("uniprot_ac", "")).strip()
        if ac:
            by_ac[ac] = rec
    # primary symbol→AC crosswalk (the InterPro sidecar is a SUPERSET fallback tried by the caller).
    from methods.target_id_sidecar import read_resolver_sidecar_map
    try:
        symbol_to_ac = read_resolver_sidecar_map(
            S3_BUCKET, SIDECAR_KEY, "hgnc_primary_symbol_at_resolution", "native_row_key",
            local_path=sidecar_path)
    except ImportError:
        raise                              # broken env — never mask
    except Exception:  # noqa: BLE001 — S3/absence (retry-backed): degrade to the InterPro fallback
        symbol_to_ac = {}
    return by_ac, symbol_to_ac


def _as_list(v):
    # parquet round-trips list columns as numpy arrays; normalize to plain list
    if v is None:
        return []
    try:
        return list(v)
    except TypeError:
        return [v]


@lru_cache(maxsize=1)
def _load_interpro_symbol_map(sidecar_path: Optional[str] = None) -> dict:
    """symbol(UPPER) -> AC from the InterPro product's OWN resolver sidecar. The InterPro sidecar
    (19,652 symbols) is a SUPERSET of the curated-product sidecar (14,807) — used as a fallback so a
    target that InterPro covers but the curated product doesn't still gets its InterPro domains."""
    from methods.target_id_sidecar import read_resolver_sidecar_map
    try:
        return read_resolver_sidecar_map(
            S3_BUCKET, INTERPRO_SIDECAR_KEY, "hgnc_primary_symbol_at_resolution", "native_row_key",
            local_path=sidecar_path)
    except ImportError:
        raise                              # broken env — never mask
    except Exception as e:  # noqa: BLE001 — InterPro is the FALLBACK layer; degrade only on genuine absence
        # read_resolver_sidecar_map already RAISES on schema-drift / empty-crosswalk; here we swallow
        # ONLY a genuine object-absence (NoSuchKey) and re-raise transient/creds → _live_read_error.
        from methods.target_id_sidecar import is_definitively_absent
        if not is_definitively_absent(e):
            raise
        return {}


def _interpro_domains_for(ac: str, interpro_path: Optional[str] = None) -> Optional[list]:
    """Pushdown-read the InterPro product for one AC's type=domain hits. Returns a list of
    {interpro_id, interpro_name, start, end} ordered by start (the domain architecture), or None if
    the product is unreadable (caller then reports interpro coverage as unavailable, distinct from
    'this AC has no InterPro domains')."""
    import pyarrow.parquet as pq
    flt = [("uniprot_accession", "==", ac), ("interpro_type", "==", "domain")]
    cols = ["interpro_id", "interpro_name", "start", "end"]
    try:
        if interpro_path is not None:
            tbl = pq.read_table(interpro_path, filters=flt, columns=cols)
        else:
            _ensure_aws_profile()
            import pyarrow.fs as fs
            tbl = pq.read_table(f"{S3_BUCKET}/{INTERPRO_KEY}",
                                filesystem=fs.S3FileSystem(region="us-east-1"),
                                filters=flt, columns=cols)
    except Exception as e:  # noqa: BLE001
        # additive InterPro layer. Genuine object-absence → None (interpro unavailable, distinct from
        # "no domains"). Broken-env/transient/creds must surface — re-raise → _live_read_error.
        from methods.target_id_sidecar import is_definitively_absent
        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        return None
    d = tbl.to_pandas()
    # order by start (NaN/None last) so the architecture reads N→C-terminal
    d = d.sort_values("start", na_position="last")
    return [{"interpro_id": str(r["interpro_id"]), "interpro_name": str(r["interpro_name"]),
             "start": (None if r["start"] != r["start"] else int(r["start"])),
             "end": (None if r["end"] != r["end"] else int(r["end"]))}
            for _, r in d.iterrows()]


def _interpro_fields(ac: Optional[str], interpro_path: Optional[str]) -> dict:
    """The additive InterPro domain layer for an AC. Returns interpro_* fields; interpro domains are
    only looked up when we HAVE an AC (a target unresolved to an AC gets an empty InterPro layer)."""
    ip = _interpro_domains_for(ac, interpro_path) if ac else None
    if ip is None:
        # either no AC, or the product was unreadable → no InterPro layer this run
        return {"interpro_n_domains": 0, "interpro_domain_names": [],
                "interpro_domain_architecture": None}
    names = [d["interpro_name"] for d in ip]
    return {"interpro_n_domains": len(ip),
            "interpro_domain_names": names,
            "interpro_domain_architecture": ("; ".join(names) if names else None)}


def read_target_summary(target: str, indication: str = None,
                        payload_path: Optional[str] = None, sidecar_path: Optional[str] = None,
                        interpro_path: Optional[str] = None,
                        interpro_sidecar_path: Optional[str] = None) -> dict:
    """Per-target domain architecture + protein class. `indication` unused (target-intrinsic).

    CURATED FT DOMAIN + protein class are authoritative (from uniprot-protein-features-v1). An
    ADDITIVE InterPro layer (interpro-109-0) BROADENS domain coverage: a target with NO curated
    FT DOMAIN may still have InterPro domains (6,445 such proteins) — so InterPro is consulted even
    when the curated record is absent, and `domain_evidence` records the provenance
    (curated | both | interpro_only | none)."""
    idx = _load_indexed(payload_path, sidecar_path)
    if idx is None:
        return _empty("protein_features_derived_product_unavailable")
    by_ac, symbol_to_ac = idx
    key = target.strip()
    ac = key if key in by_ac else symbol_to_ac.get(key.upper())
    rec = by_ac.get(ac) if ac else None
    # AC-resolution fallback: if the curated sidecar didn't resolve the symbol, try the InterPro
    # product's own sidecar (a superset) so InterPro-only targets still get their domains. This never
    # changes the CURATED record lookup (rec stays None if not in the curated product) — it only
    # supplies an AC for the additive InterPro layer.
    if ac is None:
        ac = _load_interpro_symbol_map(interpro_sidecar_path).get(key.upper())

    ip = _interpro_fields(ac, interpro_path)
    ip_n = ip["interpro_n_domains"]

    if rec is None:
        # No curated FT DOMAIN AND no class keyword. BEFORE reporting data_unavailable, honor the
        # InterPro layer: if InterPro has domains for this AC, this is the interpro_only gap-fill —
        # a real, coverage-broadening answer, not an annotation gap.
        if ac and ip_n > 0:
            out = _empty("no curated UniProt FT DOMAIN or class keyword; InterPro domains present "
                         "(interpro_only coverage)")
            out.update(ip)
            out["uniprot_ac"] = ac
            out["domain_evidence"] = "interpro_only"
            return out
        out = _empty(f"{target!r} has no curated UniProt domain or class-bearing keyword "
                     f"(annotation gap, not 'featureless')")
        out.update(ip)
        out["uniprot_ac"] = ac
        out["domain_evidence"] = "none"
        return out

    domain_names = _as_list(rec.get("domain_names"))
    protein_class = _as_list(rec.get("protein_class"))
    n_dom = int(rec.get("n_domains") or 0)
    # a compact class for quick reads: has_domains + primary class (CURATED — unchanged vocabulary)
    features_class = ("multi_domain" if n_dom >= 2 else
                      "single_domain" if n_dom == 1 else
                      "no_curated_domain")
    # domain_evidence: provenance of the domain call (curated FT DOMAIN vs InterPro-broadened)
    if n_dom > 0 and ip_n > 0:
        domain_evidence = "both"
    elif n_dom > 0:
        domain_evidence = "curated"
    elif ip_n > 0:
        domain_evidence = "interpro_only"   # keyword-class record but no curated domain; InterPro fills it
    else:
        domain_evidence = "none"
    out = {
        "protein_features_class": features_class,   # PRIMARY (multi_domain | single_domain | no_curated_domain)
        "n_domains": n_dom,
        "domain_names": domain_names,
        "domain_architecture": rec.get("domain_architecture"),
        "protein_class": protein_class,
        "protein_class_primary": rec.get("protein_class_primary"),
        "uniprot_ac": ac,
        "domain_evidence": domain_evidence,
        "method_version": METHOD_VERSION,
        "_data_source": f"{DERIVED_MANIFEST_ID}+{INTERPRO_MANIFEST_ID}",
    }
    out.update(ip)
    return out


def _empty(note: str) -> dict:
    return {
        "protein_features_class": "data_unavailable",
        "n_domains": 0, "domain_names": [], "domain_architecture": None,
        "protein_class": [], "protein_class_primary": None, "uniprot_ac": None,
        "domain_evidence": "none",
        "interpro_n_domains": 0, "interpro_domain_names": [], "interpro_domain_architecture": None,
        "method_version": METHOD_VERSION, "_data_source": DERIVED_MANIFEST_ID, "_data_note": note,
    }
