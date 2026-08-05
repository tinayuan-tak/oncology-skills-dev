"""gene_ontology_annotation — per-target Gene Ontology term membership (BP / MF / CC).

The INDICATION-INDEPENDENT GO-annotation view of a target: which GO terms is this gene-product
annotated with, split into the three GO namespaces — biological_process (BP), molecular_function (MF),
cellular_component (CC) — with counts + the top experimental-evidence terms per namespace.

Target-intrinsic (cancer-independent): a gene's GO annotations are the same regardless of indication.
Consumed by the target-intrinsic dossier subskill. Descriptive — no verdict.

Substrate (source manifest gene-ontology-release-2026-05-19, all pre-catalogued on S3):
  - goa_human.gaf.gz     GOA Human gene-product → GO-term associations (GAF 2.2): col2=UniProt AC,
                         col5=GO id, col7=evidence code, col9=namespace (P/F/C).
  - go-basic.obo         GO term DAG: id / name / namespace per term (for term names).
  - goa_human.gaf.gz.target_resolution.parquet  resolver sidecar (HGNC symbol → UniProt AC).

Runtime: S3 get → in-process lru_cache of the parsed GAF (gene→terms) + OBO (id→name) + resolver
sidecar; single lookup per call. Same discipline as reactome_pathway_context (parse-once, cache).

License: GO + GOA are CC-BY-4.0 (cite the GO Consortium).
"""
from __future__ import annotations

import gzip
import io
import os
from functools import lru_cache
from typing import Optional

METHOD_VERSION = "1.0.0"
DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
GO_SOURCE_MANIFEST_ID = "gene-ontology-release-2026-05-19"
_PREFIX = "data-catalog/sources/gene-ontology/release-2026-05-19"
GAF_S3_KEY = f"{_PREFIX}/goa_human.gaf.gz"
OBO_S3_KEY = f"{_PREFIX}/go-basic.obo"
SIDECAR_S3_KEY = f"{_PREFIX}/goa_human.gaf.gz.target_resolution.parquet"

# GAF namespace code (col9) → GO namespace label.
_NS_CODE = {"P": "biological_process", "F": "molecular_function", "C": "cellular_component"}
# Experimental / high-trust GO evidence codes (vs IEA electronic). Used to flag curated terms.
_EXPERIMENTAL_EVIDENCE = {"EXP", "IDA", "IPI", "IMP", "IGI", "IEP", "HTP", "HDA", "HMP", "HGI", "HEP"}


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _boto3_client():
    import boto3
    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")


@lru_cache(maxsize=1)
def _load_obo_names(obo_path: Optional[str] = None) -> dict:
    """GO id → term name, from go-basic.obo. (Namespace also parseable but the GAF carries it in col9,
    which is authoritative + cheaper, so we only need names here.)"""
    if obo_path is not None:
        raw = open(obo_path, "rb").read()
    else:
        _ensure_aws_profile()
        raw = _boto3_client().get_object(Bucket=S3_BUCKET, Key=OBO_S3_KEY)["Body"].read()
    names: dict[str, str] = {}
    cur_id = None
    for line in io.StringIO(raw.decode("utf-8", "replace")):
        line = line.rstrip("\n")
        if line == "[Term]":
            cur_id = None
        elif line.startswith("id: GO:"):
            cur_id = line[4:].strip()
        elif line.startswith("name:") and cur_id:
            names[cur_id] = line[5:].strip()
    return names


@lru_cache(maxsize=1)
def _load_gaf(gaf_path: Optional[str] = None) -> dict:
    """UniProt AC → list of {go_id, namespace, evidence} from goa_human.gaf.gz.

    Dedups on (AC, go_id, namespace) keeping the strongest evidence seen (experimental > other)."""
    if gaf_path is not None:
        raw = open(gaf_path, "rb").read()
    else:
        _ensure_aws_profile()
        raw = _boto3_client().get_object(Bucket=S3_BUCKET, Key=GAF_S3_KEY)["Body"].read()
    by_ac: dict[str, dict] = {}   # ac -> {(go_id, ns): evidence}
    with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("!"):
                continue
            c = line.rstrip("\n").split("\t")
            if len(c) < 9:
                continue
            ac, go_id, evidence, ns_code = c[1].strip(), c[4].strip(), c[6].strip(), c[8].strip()
            ns = _NS_CODE.get(ns_code)
            if not ac or not go_id or ns is None:
                continue
            slot = by_ac.setdefault(ac, {})
            key = (go_id, ns)
            # keep the strongest evidence (experimental wins over IEA/ISS)
            prev = slot.get(key)
            if prev is None or (evidence in _EXPERIMENTAL_EVIDENCE and prev not in _EXPERIMENTAL_EVIDENCE):
                slot[key] = evidence
    out: dict[str, list] = {}
    for ac, terms in by_ac.items():
        out[ac] = [{"go_id": gid, "namespace": ns, "evidence": ev} for (gid, ns), ev in terms.items()]
    return out


@lru_cache(maxsize=1)
def _load_symbol_to_ac(sidecar_path: Optional[str] = None) -> dict:
    """HGNC symbol (UPPER) → UniProt AC, from the GOA resolver sidecar (never a GAF symbol column —
    deprecated-symbol risk)."""
    try:
        import pandas as pd
        if sidecar_path is not None:
            df = pd.read_parquet(sidecar_path)
        else:
            _ensure_aws_profile()
            body = _boto3_client().get_object(Bucket=S3_BUCKET, Key=SIDECAR_S3_KEY)["Body"].read()
            df = pd.read_parquet(io.BytesIO(body))
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, str] = {}
    if "hgnc_primary_symbol_at_resolution" in df.columns and "native_row_key" in df.columns:
        for sym, ac in zip(df["hgnc_primary_symbol_at_resolution"].values, df["native_row_key"].values):
            if isinstance(sym, str) and sym.strip() and isinstance(ac, str) and ac.strip():
                out.setdefault(sym.strip().upper(), ac.strip())
    return out


def read_target_summary(target: str, indication: str = None,
                        gaf_path: Optional[str] = None, obo_path: Optional[str] = None,
                        sidecar_path: Optional[str] = None) -> dict:
    """Per-target GO annotation summary (BP / MF / CC). `indication` unused (GO is target-intrinsic;
    accepted for dispatcher signature consistency)."""
    sym_to_ac = _load_symbol_to_ac(sidecar_path)
    ac = target.strip() if _looks_like_uniprot_ac(target) else sym_to_ac.get(target.strip().upper())
    if not ac:
        return _empty("target_symbol_not_resolvable")
    try:
        gaf = _load_gaf(gaf_path)
        terms = gaf.get(ac, [])
        if not terms:
            return _empty("target_not_in_goa_human")
        names = _load_obo_names(obo_path)
        by_ns: dict[str, list] = {"biological_process": [], "molecular_function": [], "cellular_component": []}
        for t in terms:
            by_ns[t["namespace"]].append(t)

        def _top(ns_terms, k=8):
            # experimental-evidence terms first, then by go_id for determinism
            ranked = sorted(ns_terms, key=lambda t: (t["evidence"] not in _EXPERIMENTAL_EVIDENCE, t["go_id"]))
            return [{"go_id": t["go_id"], "name": names.get(t["go_id"], t["go_id"]),
                     "evidence": t["evidence"]} for t in ranked[:k]]

        n_total = len(terms)
        n_experimental = sum(1 for t in terms if t["evidence"] in _EXPERIMENTAL_EVIDENCE)
        annotation_class = ("well_annotated" if n_total >= 20 else
                            "partial" if n_total >= 5 else "sparse")
        return {
            "annotation_class": annotation_class,   # PRIMARY
            "n_go_terms_total": n_total,
            "n_go_terms_experimental": n_experimental,
            "n_biological_process": len(by_ns["biological_process"]),
            "n_molecular_function": len(by_ns["molecular_function"]),
            "n_cellular_component": len(by_ns["cellular_component"]),
            "top_biological_process": _top(by_ns["biological_process"]),
            "top_molecular_function": _top(by_ns["molecular_function"]),
            "top_cellular_component": _top(by_ns["cellular_component"]),
            "uniprot_ac_resolved": ac,
            "method_version": METHOD_VERSION,
            "_data_source": GO_SOURCE_MANIFEST_ID,
        }
    except Exception as e:  # noqa: BLE001
        return _empty(f"compute_failed: {type(e).__name__}")


def _looks_like_uniprot_ac(s: str) -> bool:
    import re
    return bool(re.match(r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})$",
                         s.strip()))


def _empty(note: str) -> dict:
    return {
        "annotation_class": "data_unavailable",
        "n_go_terms_total": 0, "n_go_terms_experimental": 0,
        "n_biological_process": 0, "n_molecular_function": 0, "n_cellular_component": 0,
        "top_biological_process": [], "top_molecular_function": [], "top_cellular_component": [],
        "uniprot_ac_resolved": None, "method_version": METHOD_VERSION,
        "_data_source": GO_SOURCE_MANIFEST_ID, "_data_note": note,
    }
