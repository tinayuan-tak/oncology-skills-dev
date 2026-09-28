"""reactome_pathway_context — read Reactome pathway-membership per target.

Returns per-target pathway annotation:
  - top_level_pathways: canonical signaling parents (e.g. 'Signal Transduction',
    'Cell Cycle', 'Immune System')
  - specific_pathways: leaf-level pathways containing the target
  - pathway_count: total pathways at all hierarchy levels
  - is_signaling: bool, target sits under 'Signal Transduction' subtree

Consumer: signaling-network-mechanism composed card via mechanism-and-
pharmacology skill. This method provides the PATHWAY-CONTEXT column that
enriches SIGNOR + CollecTri edges — a partner sharing a pathway with the
target is a governance-differentiating signal.

Uses HGNC symbol → UniProt-AC resolution to join UniProt2Reactome. The
lookup is cached in-memory per Python process (small: ~15k UniProt-AC's
with pathways in v96).

License: Reactome CC0-1.0 (public domain).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from methods.catalog_query.read import bucket_prefix_for, sidecar_bucket_key_for

DEFAULT_AWS_PROFILE = "cbg"
REACTOME_SOURCE_MANIFEST_ID = "reactome-v96"

# Files this reader consumes — all pre-catalogued in reactome-v96. bucket + source-dir
# prefix resolved from the manifest (single source of truth); each key rides off it.
S3_BUCKET, _REACTOME_PREFIX = bucket_prefix_for(REACTOME_SOURCE_MANIFEST_ID)
UNIPROT_TO_REACTOME_S3_KEY = f"{_REACTOME_PREFIX}UniProt2Reactome_All_Levels.txt"
PATHWAYS_S3_KEY = f"{_REACTOME_PREFIX}ReactomePathways.txt"
PATHWAYS_RELATION_S3_KEY = f"{_REACTOME_PREFIX}ReactomePathwaysRelation.txt"

CACHE_DIR = Path.home() / ".cache" / "framework-reactome"


from methods.target_id_sidecar import ensure_aws_profile, looks_like_uniprot_ac
from methods.target_id_sidecar import s3_client as _boto3_client


def _ensure_cached(s3_key: str, cache_filename: str) -> Path:
    """Idempotent S3 → local cache download."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    local = CACHE_DIR / cache_filename
    if local.exists() and local.stat().st_size > 0:
        return local
    s3 = _boto3_client()
    s3.download_file(S3_BUCKET, s3_key, str(local))
    return local


@lru_cache(maxsize=1)
def _load_uniprot_to_reactome(uniprot2reactome_path: Optional[str] = None) -> dict:
    """UniProt-AC → list of {pathway_id, pathway_name, evidence_code, url,
    organism} dicts. Filtered to Homo sapiens.

    UniProt2Reactome_All_Levels.txt format (tab-separated, no header):
        UniProtAC  R-HSA-NNNNNNN  URL  PathwayName  EvidenceCode  Organism

    `uniprot2reactome_path` (test fixture / warm cache) is read directly instead of S3.
    """
    path = (
        Path(uniprot2reactome_path)
        if uniprot2reactome_path
        else _ensure_cached(UNIPROT_TO_REACTOME_S3_KEY, "UniProt2Reactome_All_Levels.txt")
    )
    result: dict[str, list[dict]] = {}
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            parts = raw.rstrip("\n").split("\t")
            if len(parts) < 6:
                continue
            uac, pid, url, pname, evidence, organism = parts[:6]
            if organism.strip() != "Homo sapiens":
                continue
            result.setdefault(uac.strip(), []).append(
                {
                    "pathway_id": pid.strip(),
                    "pathway_name": pname.strip(),
                    "evidence_code": evidence.strip(),
                    "url": url.strip(),
                }
            )
    return result


@lru_cache(maxsize=1)
def _load_pathway_hierarchy(
    pathways_path: Optional[str] = None, relations_path: Optional[str] = None
) -> tuple[dict, dict]:
    """Return (pathway_id → name map, child → parent map).

    ReactomePathways.txt format (tab-separated):
        PathwayID  PathwayName  Organism
    ReactomePathwaysRelation.txt format (tab-separated):
        ParentID  ChildID

    `pathways_path` / `relations_path` (test fixture / warm cache) are read directly instead of S3.
    """
    pathways_path = Path(pathways_path) if pathways_path else _ensure_cached(PATHWAYS_S3_KEY, "ReactomePathways.txt")
    id_to_name: dict[str, str] = {}
    with pathways_path.open("r", encoding="utf-8") as f:
        for raw in f:
            parts = raw.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            pid, name, organism = parts[:3]
            if organism.strip() == "Homo sapiens":
                id_to_name[pid.strip()] = name.strip()

    relations_path = (
        Path(relations_path)
        if relations_path
        else _ensure_cached(PATHWAYS_RELATION_S3_KEY, "ReactomePathwaysRelation.txt")
    )
    child_to_parent: dict[str, str] = {}
    with relations_path.open("r", encoding="utf-8") as f:
        for raw in f:
            parts = raw.rstrip("\n").split("\t")
            if len(parts) != 2:
                continue
            parent, child = parts
            # keep first-seen parent (in practice Reactome pathways have
            # single parents in the tree; check hasn't been triggered)
            child_to_parent.setdefault(child.strip(), parent.strip())
    return id_to_name, child_to_parent


def _walk_to_top(pid: str, child_to_parent: dict) -> str:
    """Walk the pathway hierarchy up to the root. Returns the top-level
    pathway ID (the ancestor with no parent).
    """
    visited: set = set()
    current = pid
    while current in child_to_parent and current not in visited:
        visited.add(current)
        current = child_to_parent[current]
    return current


def _hgnc_to_uniprot_ac(target: str, sidecar_path: Optional[str] = None) -> Optional[str]:
    """Resolve HGNC gene symbol → primary UniProt accession.

    Accepts target as EITHER a UniProt-AC (returned as-is; matched by the strict
    shared looks_like_uniprot_ac shape) or an HGNC symbol (looked up in the
    Reactome resolver-sidecar crosswalk).
    """
    target = target.strip()
    if not target:
        return None
    # An AC passed in place of a symbol is returned as-is; otherwise look up the crosswalk.
    if looks_like_uniprot_ac(target):
        return target
    return _hgnc_symbol_to_uniprot_ac_cached(target, sidecar_path)


# The RESOLVER SIDECAR shipped alongside the Reactome source (produced by target_id_resolver at
# ingest time): maps every UniProt2Reactome native accession → canonical HGNC symbol. Replaces the
# former hardcoded ~30-target inline crosswalk (a v0.1 shortcut that failed the standing resolver-
# sidecar rule for any target outside the inline set). 12,136 rows, lru-cached per process.
# resolver sidecar resolved from the manifest's target_resolution.sidecar_s3_uri.
_, REACTOME_RESOLVER_SIDECAR_S3_KEY = sidecar_bucket_key_for(REACTOME_SOURCE_MANIFEST_ID)


@lru_cache(maxsize=1)
def _load_hgnc_uniprot_crosswalk(sidecar_path: Optional[str] = None) -> dict:
    """HGNC symbol (UPPER) → primary UniProt-AC, from the Reactome resolver sidecar on S3.

    Reads the target_id_resolver sidecar (hgnc_primary_symbol_at_resolution → native_row_key)
    shipped with reactome-v96 — the same discipline as the CSPA/GPI/topology readers (never a
    hardcoded map, never a source symbol column). Delegates to the shared resolver-sidecar loader,
    which RAISES on read failure instead of silently returning {} — an empty crosswalk would fail
    EVERY target (data_unavailable framework-wide). The live-read seam turns a raise into an honest
    per-card _live_read_error. `sidecar_path` (test fixture / warm cache) is read directly."""
    from methods.target_id_sidecar import read_resolver_sidecar_map

    return read_resolver_sidecar_map(
        S3_BUCKET,
        REACTOME_RESOLVER_SIDECAR_S3_KEY,
        "hgnc_primary_symbol_at_resolution",
        "native_row_key",
        local_path=sidecar_path,
    )


def _hgnc_symbol_to_uniprot_ac_cached(symbol: str, sidecar_path: Optional[str] = None) -> Optional[str]:
    return _load_hgnc_uniprot_crosswalk(sidecar_path).get(symbol.upper())


_DERIVED_PRODUCT_ID = "reactome-pathway-per-uniprot-v1"


def _load_pathways_from_product(uac: str, product_path=None):
    """(pathways, top_level_names) for the accession via predicate-pushdown on the per-AC product,
    else None when the product is UNREACHABLE (→ caller falls back to the live UniProt2Reactome read).

      * pathways : ordered [{pathway_id, pathway_name, evidence_code, url}] in the SAME source order the
        live map yields (row_order), so `pathways[:20]` is identical;
      * top_level_names : set of top-level pathway NAMES (the hierarchy walk baked at build time).

    Empty result (AC absent) returns ([], set()) so the caller emits target_not_in_reactome_human,
    mirroring the live uniprot_map.get(uac, []) miss. `product_path` overrides S3 (tests).
    """
    cols = ["uniprot_ac", "row_order", "pathway_id", "pathway_name", "evidence_code", "url", "top_level_pathway_name"]
    if product_path is not None:
        import pandas as pd

        try:
            df = pd.read_parquet(product_path, columns=cols, filters=[("uniprot_ac", "=", uac)])
        except (FileNotFoundError, OSError):
            return None
        recs = df.to_dict("records")
    else:
        try:
            from methods.catalog_query.read import s3_uri_for

            uri = s3_uri_for(_DERIVED_PRODUCT_ID)
        except Exception:  # absence-discipline: exempt -- resolves a LOCAL data-catalog manifest (not an S3 read); an unregistered/unreadable manifest => product not available => live UniProt2Reactome fallback, which enforces its own read discipline.
            return None
        try:
            import pyarrow.fs as fs
            import pyarrow.parquet as pq

            ensure_aws_profile()
            tbl = pq.read_table(
                uri.replace("s3://", "", 1),
                filesystem=fs.S3FileSystem(),
                columns=["row_order", "pathway_id", "pathway_name", "evidence_code", "url", "top_level_pathway_name"],
                filters=[("uniprot_ac", "=", uac)],
            )
        except Exception as e:  # noqa: BLE001
            from methods.target_id_sidecar import is_definitively_absent

            if isinstance(e, FileNotFoundError) or is_definitively_absent(e):
                return None  # object genuinely absent → live fallback
            raise  # transient/creds → honest _live_read_error
        recs = tbl.to_pylist()
    recs.sort(key=lambda r: r["row_order"])  # restore source order for specific_pathways[:20]
    pathways = [
        {
            "pathway_id": r["pathway_id"],
            "pathway_name": r["pathway_name"],
            "evidence_code": r["evidence_code"],
            "url": r["url"],
        }
        for r in recs
    ]
    top_level_names = {r["top_level_pathway_name"] for r in recs}
    return pathways, top_level_names


def read_target_summary(
    target: str,
    indication: str = None,
    *,
    uniprot2reactome_path: Optional[str] = None,
    pathways_path: Optional[str] = None,
    relations_path: Optional[str] = None,
    sidecar_path: Optional[str] = None,
) -> dict:
    """Per-target Reactome pathway-context summary.

    Args:
        target: HGNC gene symbol OR UniProt accession
        indication: unused (Reactome is indication-agnostic; accepted for
            dispatcher signature consistency)
        uniprot2reactome_path / pathways_path / relations_path / sidecar_path:
            optional local-file overrides (test fixtures / warm cache) that
            bypass the S3 reads — the same seam the sibling readers expose.

    Returns:
        dict with pathway-context annotation:
          - pathway_count (int)
          - top_level_pathways (list<str>)
          - specific_pathways (list<{pathway_id, pathway_name}>)
          - is_signaling (bool)
          - pathway_class ('well_annotated' | 'partial' | 'sparse' | 'data_unavailable')
    """
    uac = _hgnc_to_uniprot_ac(target, sidecar_path)
    if uac is None:
        return _empty_result("target_symbol_not_resolvable")

    try:
        # Prefer the precomputed per-AC product (pushdown, ~kB — no whole 117 MB UniProt2Reactome +
        # hierarchy cold-start read); the fixture-path test seam forces the live path.
        _fixture = uniprot2reactome_path is not None or pathways_path is not None or relations_path is not None
        prod = _load_pathways_from_product(uac) if not _fixture else None
        if prod is not None:
            pathways, top_level_names = prod  # ordered pathways + top-level name set (baked)
        else:
            uniprot_map = _load_uniprot_to_reactome(uniprot2reactome_path)
            pathways = uniprot_map.get(uac, [])
            if not pathways:
                return _empty_result("target_not_in_reactome_human")
            id_to_name, child_to_parent = _load_pathway_hierarchy(pathways_path, relations_path)
            top_level_names = {  # top-level rollup per pathway (walk to root)
                id_to_name.get(
                    _walk_to_top(p["pathway_id"], child_to_parent), _walk_to_top(p["pathway_id"], child_to_parent)
                )
                for p in pathways
            }
        if not pathways:
            return _empty_result("target_not_in_reactome_human")

        top_level_classified = sorted({n.strip() for n in top_level_names})

        # Signaling flag: does any top-level pathway contain "Signal
        # Transduction" or "Signaling"?
        is_signaling = any("signal" in n.lower() for n in top_level_names)

        # Classification
        n_pathways = len(pathways)
        if n_pathways == 0:
            pathway_class = "data_unavailable"
        elif n_pathways >= 20:
            pathway_class = "well_annotated"
        elif n_pathways >= 5:
            pathway_class = "partial"
        else:
            pathway_class = "sparse"

        # Top 10 specific pathways for the emitted summary
        specific_pathways = [
            {"pathway_id": p["pathway_id"], "pathway_name": p["pathway_name"], "evidence_code": p["evidence_code"]}
            for p in pathways[:20]
        ]

        return {
            "pathway_class": pathway_class,
            "pathway_count": n_pathways,
            "top_level_pathways": top_level_classified,
            "specific_pathways": specific_pathways,
            "is_signaling": is_signaling,
            "uniprot_ac_resolved": uac,
            "_data_source": "reactome-pathway-context-per-gene-v1",
            "_data_source_upstream": REACTOME_SOURCE_MANIFEST_ID,
        }
    except Exception as e:
        # honest-loud absence discipline (#822): only a GENUINE product/source absence
        # (NoSuchKey/404/NoSuchBucket or a missing local file) is an honest data_unavailable; a transient
        # S3/creds/parse fault must RE-RAISE (fail-loud) rather than being masked as a benign
        # pathway-context gap. (A target genuinely not in Reactome is handled by the
        # 'target_not_in_reactome_human' / 'target_symbol_not_resolvable' branches, not this catch.)
        # Mirrors collectri_tf_regulon/read.py:177-198.
        from methods.target_id_sidecar import is_definitively_absent

        if not (isinstance(e, FileNotFoundError) or is_definitively_absent(e)):
            raise
        return _empty_result(f"compute_failed: {type(e).__name__}: {e}")


def _empty_result(note: str) -> dict:
    return {
        "pathway_class": "data_unavailable",
        "pathway_count": 0,
        "top_level_pathways": [],
        "specific_pathways": [],
        "is_signaling": False,
        "uniprot_ac_resolved": None,
        "_data_note": note,
    }
