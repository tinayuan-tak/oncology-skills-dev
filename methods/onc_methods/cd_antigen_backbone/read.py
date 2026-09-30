"""cd_antigen_backbone.read — S3 boundary for the CD/IO-antigen-backbone signal (E6-CD).

Reads the LANDED raw source hgnc-gene-group-471 (members.json, 394 records, 660KB, CC0) directly
(lookup-only reference table — no derived product needed, mirrors how shed_ectodomain_liability
reads its curated vocab). Builds an UPPER(symbol)->record dict, cached; classify.classify_cd_backbone
resolves the target. Symbol-keyed with a uniprot/ensembl fallback so non-'CD'-named backbone antigens
(PDCD1=CD279, CTLA4=CD152) resolve too.

Backbone membership is a protein property — `indication` is accepted for the dispatcher contract but
not consumed. An absent target is `not_cd_antigen` (a real determination: not on the HGNC CD roster),
NOT data_unavailable — distinct from an unreadable roster (infra failure)."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Optional

from onc_methods.catalog_query.read import bucket_prefix_for

from . import classify as _classify

SOURCE_MANIFEST_ID = "hgnc-gene-group-471-cd-molecules-snapshot-2026-07-08"
MEMBERS_FILE = "members.json"
DEFAULT_AWS_PROFILE = "cbg"
METHOD_VERSION = _classify.METHOD_VERSION


from onc_methods.target_id_sidecar import ensure_aws_profile


def _extract_records(doc) -> list:
    """The members.json container shape is tolerant: a bare list, or nested under
    response.docs / docs / members, or the first list-valued field."""
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict):
        resp = doc.get("response")
        if isinstance(resp, dict) and isinstance(resp.get("docs"), list):
            return resp["docs"]
        for k in ("docs", "members", "records"):
            if isinstance(doc.get(k), list):
                return doc[k]
        for v in doc.values():
            if isinstance(v, list):
                return v
    return []


@lru_cache(maxsize=1)
def _load_roster(members_path: Optional[str] = None) -> dict:
    """UPPER(symbol) -> record (+ uniprot/ensembl secondary keys). {} if unreadable.
    members_path overrides S3 for tests (a local members.json)."""
    try:
        if members_path is not None:
            with open(members_path) as f:
                doc = json.load(f)
        else:
            import boto3

            ensure_aws_profile()
            bucket, prefix = bucket_prefix_for(SOURCE_MANIFEST_ID)
            key = f"{prefix}{MEMBERS_FILE}"
            body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
            doc = json.loads(body)
    except Exception as e:
        # Genuine object-absence (S3 404/NoSuchKey, or a missing local members.json) → {} (the caller
        # emits an honest _live_read_error breadcrumb). A transient/creds/broken-env failure is
        # RE-RAISED — not masked as an empty roster that @lru_cache would then memoize process-wide
        # (one blip would pin EVERY target to "roster unreadable" for the whole process, defeating the
        # caller's per-call breadcrumb). lru_cache never memoizes a raise, so the next call retries.
        from onc_methods.target_id_sidecar import is_definitively_absent

        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        return {}
    out = {}
    for rec in _extract_records(doc):
        if not isinstance(rec, dict):
            continue
        sym = rec.get("symbol")
        if sym:
            out[str(sym).upper()] = rec
        # secondary keys so a UniProt/Ensembl-supplied target still resolves
        for u in rec.get("uniprot_ids") or []:
            out.setdefault(str(u).upper(), rec)
        eg = rec.get("ensembl_gene_id")
        if eg:
            out.setdefault(str(eg).upper(), rec)
    return out


def read_cd_antigen_backbone(target: str, indication: Optional[str] = None, members_path: Optional[str] = None) -> dict:
    """CD/IO-antigen-backbone clinical-precedent summary for a target. Protein-intrinsic —
    `indication` accepted for the CARD_DISPATCHERS contract but NOT consumed."""
    roster = _load_roster(members_path)
    if not roster:
        out = _classify.empty("cd-molecule roster unreadable (infra failure)")
        out["_live_read_error"] = "cd_antigen_roster_read_failed"
    else:
        out = _classify.classify_cd_backbone(target, roster)
    out["target"] = target
    out["_data_source"] = SOURCE_MANIFEST_ID
    return out
