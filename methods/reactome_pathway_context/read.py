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

import os
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

# Canonical Reactome top-level signaling parents. These are the R-HSA-NNNNNNN
# pathway stable IDs at the highest hierarchy level (parent has no parent).
# Used to compute the top-level pathway rollup for a target's pathway set.
# Extracted 2026-07-10 from ReactomePathways.txt filtered to Homo sapiens
# + roots of ReactomePathwaysRelation.txt hierarchy.
_TOP_LEVEL_HINT_STRINGS = {
    "signal transduction", "cell cycle", "immune system",
    "gene expression", "metabolism", "programmed cell death",
    "developmental biology", "hemostasis", "extracellular matrix organization",
    "dna repair", "dna replication", "chromatin organization",
    "transport of small molecules", "vesicle-mediated transport",
    "reproduction", "cell-cell communication", "muscle contraction",
    "digestion and absorption", "sensory perception",
    "neuronal system", "circadian clock",
    "protein localization", "autophagy",
    "metabolism of proteins", "metabolism of rna",
    "organelle biogenesis and maintenance",
}


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
    path = (Path(uniprot2reactome_path) if uniprot2reactome_path
            else _ensure_cached(UNIPROT_TO_REACTOME_S3_KEY, "UniProt2Reactome_All_Levels.txt"))
    result: dict[str, list[dict]] = {}
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            parts = raw.rstrip("\n").split("\t")
            if len(parts) < 6:
                continue
            uac, pid, url, pname, evidence, organism = parts[:6]
            if organism.strip() != "Homo sapiens":
                continue
            result.setdefault(uac.strip(), []).append({
                "pathway_id": pid.strip(),
                "pathway_name": pname.strip(),
                "evidence_code": evidence.strip(),
                "url": url.strip(),
            })
    return result


@lru_cache(maxsize=1)
def _load_pathway_hierarchy(pathways_path: Optional[str] = None,
                            relations_path: Optional[str] = None) -> tuple[dict, dict]:
    """Return (pathway_id → name map, child → parent map).

    ReactomePathways.txt format (tab-separated):
        PathwayID  PathwayName  Organism
    ReactomePathwaysRelation.txt format (tab-separated):
        ParentID  ChildID

    `pathways_path` / `relations_path` (test fixture / warm cache) are read directly instead of S3.
    """
    pathways_path = (Path(pathways_path) if pathways_path
                     else _ensure_cached(PATHWAYS_S3_KEY, "ReactomePathways.txt"))
    id_to_name: dict[str, str] = {}
    with pathways_path.open("r", encoding="utf-8") as f:
        for raw in f:
            parts = raw.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            pid, name, organism = parts[:3]
            if organism.strip() == "Homo sapiens":
                id_to_name[pid.strip()] = name.strip()

    relations_path = (Path(relations_path) if relations_path
                      else _ensure_cached(PATHWAYS_RELATION_S3_KEY, "ReactomePathwaysRelation.txt"))
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

    iter-1 uses the framework's identifier resolver (if available) or a
    minimal fallback that reads uniprot-sprot-human-2026-02 gene-name-to-
    accession mapping from S3.

    For iter-1 v0.1, we accept target as EITHER an HGNC symbol OR a
    UniProt-AC (P/Q-shape prefix).

    UniProt-AC pattern (strict): [OPQ][0-9][A-Z0-9]{3}[0-9] (6 chars) OR
    [A-N,R-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2} (6-10 chars). The strict
    pattern is required because permissive heuristics falsely match HGNC
    symbols like NFE2L2 (looks like it has digits, but is a symbol).
    """
    target = target.strip()
    if not target:
        return None
    # Check strict UniProt-AC pattern before assuming input is HGNC symbol.
    import re
    _UNIPROT_AC_RE = re.compile(
        r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|"
        r"[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})$"
    )
    if _UNIPROT_AC_RE.match(target):
        return target
    # Otherwise, treat as HGNC symbol and look up crosswalk.
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
        S3_BUCKET, REACTOME_RESOLVER_SIDECAR_S3_KEY,
        "hgnc_primary_symbol_at_resolution", "native_row_key",
        local_path=sidecar_path)


def _hgnc_symbol_to_uniprot_ac_cached(symbol: str, sidecar_path: Optional[str] = None) -> Optional[str]:
    return _load_hgnc_uniprot_crosswalk(sidecar_path).get(symbol.upper())


def _classify_top_level(pathway_name: str) -> str:
    """Categorize a top-level pathway name into the framework's canonical
    top-level bucket (mostly signal-adjacent for oncology-target work).
    """
    lower = pathway_name.lower().strip()
    for hint in _TOP_LEVEL_HINT_STRINGS:
        if hint in lower:
            return pathway_name.strip()
    return pathway_name.strip()  # fallback: preserve verbatim


def read_target_summary(target: str, indication: str = None, *,
                        uniprot2reactome_path: Optional[str] = None,
                        pathways_path: Optional[str] = None,
                        relations_path: Optional[str] = None,
                        sidecar_path: Optional[str] = None) -> dict:
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
        uniprot_map = _load_uniprot_to_reactome(uniprot2reactome_path)
        pathways = uniprot_map.get(uac, [])
        if not pathways:
            return _empty_result("target_not_in_reactome_human")

        id_to_name, child_to_parent = _load_pathway_hierarchy(pathways_path, relations_path)

        # Compute top-level rollup per pathway
        top_level_ids: set[str] = set()
        for p in pathways:
            top_pid = _walk_to_top(p["pathway_id"], child_to_parent)
            top_level_ids.add(top_pid)

        top_level_names = sorted({
            id_to_name.get(pid, pid) for pid in top_level_ids
        })
        top_level_classified = sorted({
            _classify_top_level(n) for n in top_level_names
        })

        # Signaling flag: does any top-level pathway contain "Signal
        # Transduction" or "Signaling"?
        is_signaling = any(
            "signal" in n.lower() for n in top_level_names
        )

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
            {"pathway_id": p["pathway_id"],
             "pathway_name": p["pathway_name"],
             "evidence_code": p["evidence_code"]}
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
