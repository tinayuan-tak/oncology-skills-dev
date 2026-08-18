"""mechanism_composed.read — union SIGNOR + CollecTri + Reactome per target.

Signature matches signor_mechanism_network.read.read_target_summary so the
mechanism-and-pharmacology skill dispatcher can swap this in without code
change.

Returns:
    {
      "network_class": ...,
      "n_upstream_regulators": int,       # UNIQUE partners after union
      "n_downstream_effectors": int,
      "upstream_regulators": [            # per-edge dict with source list
          {"partner_gene_symbol", "partner_uniprot_ac", "direction",
           "raw_mechanism", "moa_class", "modality_relevance",
           "sources": ["signor", "collectri"], "references": ...,
           "n_sources_supporting": int}, ...
      ],
      "downstream_effectors": [...],
      "moa_classes_present": [...],       # union across sources
      "pd_marker_classes_present": [...],
      "has_actionable_moa": bool,
      "has_pd_marker": bool,
      "high_confidence_edges_count": int, # edges with n_sources_supporting >= 2
      "moa_ontology_version": ...,
      "moa_ontology_unmapped_fraction": float,
      "source_counts": {"signor": N, "collectri": M, "reactome_pathways": K},
      "sources_wired": ["signor", "collectri", "reactome", "depmap_coessentiality"],
      "reactome_pathway_context": {       # LAYERED annotation, not per-edge
          "pathway_class": ...,
          "pathway_count": ...,
          "top_level_pathways": [...],
          "is_signaling": bool,
      },
      "coessentiality_context": {         # FUNCTIONAL lane — DepMap 26Q1 CRISPR
          "data_available": bool,
          "n_partners": int,
          "n_cell_lines": int,
          "top_partners": [{"symbol", "pearson_r", "abs_rank", "direction"}, ...],
          "method_version": str,
          "source_note": str,
      },
    }
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure methods/ is on sys.path for sibling imports
_METHODS_ROOT = Path(__file__).resolve().parent.parent
if str(_METHODS_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_METHODS_ROOT.parent))

from methods.signor_mechanism_network.moa_ontology import ONTOLOGY_VERSION
from methods.signor_mechanism_network import read as signor_read
from methods.collectri_tf_regulon import read as collectri_read
from methods.reactome_pathway_context import read as reactome_read
from methods.kinome_atlas_prediction import read as kinome_atlas_read
from methods.depmap_coessentiality import read as coessentiality_read


# Source keys for provenance stamping. Curated sources first; kinome-atlas
# is PREDICTION so consumers/synthesis should weight it lower.
SOURCE_KEY_SIGNOR = "signor"
SOURCE_KEY_COLLECTRI = "collectri"
SOURCE_KEY_REACTOME = "reactome"
SOURCE_KEY_KINOME_ATLAS = "kinome_atlas_prediction"
SOURCE_KEY_COESSENTIALITY = "depmap_coessentiality"

# Curated sources — governance-grade evidence. Kinome-atlas + co-essentiality
# are separately labelled so downstream can filter/weight distinctly.
CURATED_SOURCE_KEYS = {SOURCE_KEY_SIGNOR, SOURCE_KEY_COLLECTRI, SOURCE_KEY_REACTOME}
PREDICTION_SOURCE_KEYS = {SOURCE_KEY_KINOME_ATLAS}
FUNCTIONAL_SOURCE_KEYS = {SOURCE_KEY_COESSENTIALITY}


def _edge_key(edge: dict) -> tuple:
    """Deduplication key for an edge across sources: (partner_symbol, direction).
    We union on this key.

    Partners are keyed by HGNC symbol only (not UniProt-AC): SIGNOR carries both
    while CollecTri carries only the symbol (AC left empty). Keying on symbol lets
    SIGNOR + CollecTri union the same partner even when only SIGNOR has the AC.
    """
    return (
        (edge.get("partner_gene_symbol") or "").strip().upper(),
        edge.get("direction", ""),
    )


def _merge_edge(existing: dict, new_edge: dict, new_source: str) -> dict:
    """Merge a new-source record into an existing edge dict, appending
    new_source to `sources`. Semantic conflicts (e.g. raw_mechanism
    differing between sources) preserve BOTH via list-append, not
    overwrite — governance readers can see disagreement.
    """
    existing_sources = existing.setdefault("sources", [])
    if new_source not in existing_sources:
        existing_sources.append(new_source)
    # Union references (semicolon-joined PMIDs, per-source-native)
    if new_edge.get("references"):
        existing_refs = existing.get("references", "")
        combined = [r for r in [existing_refs, new_edge["references"]] if r]
        existing["references"] = ";".join(combined)
    # Track disagreement (rare but governance-critical): if new source has a
    # different moa_class than the first-seen edge, we keep the first-seen
    # class as authoritative but flag disagreement in _class_disagreement.
    if new_edge.get("moa_class") and existing.get("moa_class") != new_edge["moa_class"]:
        existing.setdefault("_class_disagreement", []).append({
            "source": new_source,
            "moa_class": new_edge["moa_class"],
            "raw_mechanism": new_edge.get("raw_mechanism", ""),
        })
    # Fill in AC if the new edge has it and existing doesn't
    if new_edge.get("partner_uniprot_ac") and not existing.get("partner_uniprot_ac"):
        existing["partner_uniprot_ac"] = new_edge["partner_uniprot_ac"]
    return existing


def _tag_edge_with_source(edge: dict, source: str) -> dict:
    """Add sources: [source] to a per-source edge before adding to the union."""
    tagged = dict(edge)  # shallow copy
    tagged["sources"] = [source]
    return tagged


def _union_edges(signor_edges: list[dict], collectri_edges: list[dict]) -> list[dict]:
    """Union SIGNOR + CollecTri edges on (partner_symbol, direction) key.

    Returns list of merged edge dicts, each with `sources: [str, ...]`
    reflecting which sources supported the edge.
    """
    union: dict[tuple, dict] = {}

    # SIGNOR first (has UniProt-AC + richer mechanism annotation)
    for e in signor_edges:
        key = _edge_key(e)
        if not key[0]:  # skip edges with empty partner symbol
            continue
        union[key] = _tag_edge_with_source(e, SOURCE_KEY_SIGNOR)

    # Then CollecTri (may add TF-target edges or reinforce SIGNOR-seen edges)
    for e in collectri_edges:
        key = _edge_key(e)
        if not key[0]:
            continue
        if key in union:
            _merge_edge(union[key], e, SOURCE_KEY_COLLECTRI)
        else:
            union[key] = _tag_edge_with_source(e, SOURCE_KEY_COLLECTRI)

    # Finalize per-edge fields
    result = []
    for e in union.values():
        e["n_sources_supporting"] = len(e.get("sources", []))
        result.append(e)
    return result


def _classify_network(n_up: int, n_down: int) -> str:
    """Same classification as SIGNOR/CollecTri readers for cross-source
    consistency. When unioned, the counts are HIGHER, so the classification
    may promote from partial→well_characterized after union.
    """
    if n_up == 0 and n_down == 0:
        return "data_unavailable"
    if n_up >= 3 and n_down >= 3:
        return "well_characterized"
    if n_up + n_down <= 1:
        return "sparse"
    return "partial"


def read_target_summary(target: str, indication: str = None) -> dict:
    """Composed Phase-D mechanism-network summary for a target.

    Fans out to signor, collectri, reactome readers in parallel-ish
    (sequential in iter-1; could parallelize later). Unions edge sources,
    layers pathway-context annotation, emits governance-facing per-edge
    provenance.

    Args:
        target: HGNC gene symbol OR UniProt-AC.
        indication: unused for Phase-D (mechanism is indication-agnostic).

    Returns:
        dict matching the composed Phase-D card summary schema.
    """
    sources_wired: list[str] = []
    signor_result: dict = {}
    collectri_result: dict = {}
    reactome_result: dict = {}

    try:
        signor_result = signor_read.read_target_summary(target, indication)
        if signor_result.get("network_class") not in (None, "data_unavailable"):
            sources_wired.append(SOURCE_KEY_SIGNOR)
    except Exception as e:
        signor_result = {"_data_note": f"signor_failed: {e}",
                          "upstream_regulators": [], "downstream_effectors": []}

    try:
        collectri_result = collectri_read.read_target_summary(target, indication)
        if collectri_result.get("network_class") not in (None, "data_unavailable"):
            sources_wired.append(SOURCE_KEY_COLLECTRI)
    except Exception as e:
        collectri_result = {"_data_note": f"collectri_failed: {e}",
                             "upstream_regulators": [], "downstream_effectors": []}

    try:
        reactome_result = reactome_read.read_target_summary(target, indication)
        if reactome_result.get("pathway_class") not in (None, "data_unavailable"):
            sources_wired.append(SOURCE_KEY_REACTOME)
    except Exception as e:
        reactome_result = {"_data_note": f"reactome_failed: {e}"}

    # Sprint 3 (2026-07-10): kinome-atlas prediction lane
    kinome_atlas_result: dict = {}
    try:
        kinome_atlas_result = kinome_atlas_read.read_target_summary(target, indication)
        if kinome_atlas_result.get("network_class") not in (None, "data_unavailable"):
            sources_wired.append(SOURCE_KEY_KINOME_ATLAS)
    except Exception as e:
        kinome_atlas_result = {"_data_note": f"kinome_atlas_failed: {e}",
                                "upstream_regulators": [], "downstream_effectors": []}

    # Sprint 4 (2026-08-10): DepMap co-essentiality lane — functional dependency
    # evidence (correlated CRISPR profiles across 1,538 cell lines). Kept separate
    # from the curated mechanism edge union; positive r = co-essential, negative r =
    # anti-correlated dependency (buffering / SL candidate direction).
    coessentiality_result: dict = {}
    try:
        coessentiality_result = coessentiality_read.read_coessential_partners(
            target, top_n=25
        )
        if not coessentiality_result.get("_data_unavailable"):
            sources_wired.append(SOURCE_KEY_COESSENTIALITY)
    except Exception as e:
        coessentiality_result = {
            "_data_unavailable": True,
            "_data_note": f"coessentiality_failed: {e}",
        }

    # Curated union: SIGNOR + CollecTri edges (Reactome is layered as
    # pathway context; kinome-atlas is a SEPARATE prediction lane).
    signor_up = signor_result.get("upstream_regulators", [])
    signor_dn = signor_result.get("downstream_effectors", [])
    collectri_up = collectri_result.get("upstream_regulators", [])
    collectri_dn = collectri_result.get("downstream_effectors", [])

    union_upstream = _union_edges(signor_up, collectri_up)
    union_downstream = _union_edges(signor_dn, collectri_dn)

    # Kinome-atlas predictions kept SEPARATE from the curated union so
    # downstream synthesis can weight them lower.
    kinome_atlas_upstream = kinome_atlas_result.get("upstream_regulators", []) or []
    kinome_atlas_downstream = kinome_atlas_result.get("downstream_effectors", []) or []

    n_up = len(union_upstream)
    n_dn = len(union_downstream)
    network_class = _classify_network(n_up, n_dn)

    # High-confidence edges = edges supported by >=2 sources
    high_conf_edges = sum(
        1 for e in (union_upstream + union_downstream)
        if e.get("n_sources_supporting", 1) >= 2
    )

    # MoA classes aggregated across the union
    moa_classes_present = sorted({e.get("moa_class") for e in union_upstream
                                    if e.get("moa_class")})
    pd_classes_present = sorted({e.get("moa_class") for e in union_downstream
                                   if e.get("moa_class")})

    # Aggregated unmapped fraction (weighted)
    signor_total_edges = len(signor_up) + len(signor_dn)
    collectri_total_edges = len(collectri_up) + len(collectri_dn)
    total = signor_total_edges + collectri_total_edges
    signor_frac = signor_result.get("moa_ontology_unmapped_fraction", 0.0) or 0.0
    collectri_frac = collectri_result.get("moa_ontology_unmapped_fraction", 0.0) or 0.0
    if total > 0:
        unmapped_frac = (
            signor_frac * signor_total_edges + collectri_frac * collectri_total_edges
        ) / total
    else:
        unmapped_frac = 0.0

    return {
        "network_class": network_class,
        "n_upstream_regulators": n_up,
        "n_downstream_effectors": n_dn,
        "upstream_regulators": union_upstream,
        "downstream_effectors": union_downstream,
        "moa_classes_present": moa_classes_present,
        "pd_marker_classes_present": pd_classes_present,
        "has_actionable_moa": n_up >= 1,
        "has_pd_marker": n_dn >= 1,
        "high_confidence_edges_count": high_conf_edges,
        "moa_ontology_version": ONTOLOGY_VERSION,
        "moa_ontology_unmapped_fraction": unmapped_frac,
        "source_counts": {
            SOURCE_KEY_SIGNOR: signor_total_edges,
            SOURCE_KEY_COLLECTRI: collectri_total_edges,
            SOURCE_KEY_REACTOME: reactome_result.get("pathway_count", 0),
            SOURCE_KEY_KINOME_ATLAS: len(kinome_atlas_upstream) + len(kinome_atlas_downstream),
            SOURCE_KEY_COESSENTIALITY: coessentiality_result.get("n_partners", 0),
        },
        "sources_wired": sources_wired,
        "reactome_pathway_context": {
            "pathway_class": reactome_result.get("pathway_class", "data_unavailable"),
            "pathway_count": reactome_result.get("pathway_count", 0),
            "top_level_pathways": reactome_result.get("top_level_pathways", []),
            "is_signaling": reactome_result.get("is_signaling", False),
        },
        # Sprint 3 (2026-07-10): PREDICTION lane kept separate from the
        # curated edge union. Consumers weight lower per reviewer guidance.
        "kinome_atlas_predictions": {
            "network_class": kinome_atlas_result.get("network_class", "data_unavailable"),
            "n_upstream_predicted_kinases": len(kinome_atlas_upstream),
            "n_downstream_predicted_substrates": len(kinome_atlas_downstream),
            "upstream_predicted_kinases": kinome_atlas_upstream,
            "downstream_predicted_substrates": kinome_atlas_downstream,
            "source_note": kinome_atlas_result.get("_source_note", ""),
        },
        # Sprint 4 (2026-08-10): FUNCTIONAL lane — DepMap pan-cancer co-essentiality.
        # Positive r = co-essential (shared complex/pathway); negative r = anti-correlated
        # dependency (buffering / SL candidate). Not a mechanism edge; kept separate.
        "coessentiality_context": {
            "data_available": not coessentiality_result.get("_data_unavailable", False),
            "n_partners": coessentiality_result.get("n_partners", 0),
            "n_cell_lines": coessentiality_result.get("n_cell_lines", 0),
            "top_partners": coessentiality_result.get("partners", []),
            "method_version": coessentiality_result.get("method_version", ""),
            "substrate_uri": coessentiality_result.get("substrate_uri", ""),
            "source_note": "DepMap 26Q1 CRISPR Chronos pan-cancer co-essentiality (1,538 cell lines)",
        },
        # Honest provenance (2026-08-11): there is NO `mechanism-composed-per-gene-v1` derived
        # manifest in the catalog — this product is COMPOSED ON READ from the upstream source readers
        # (signor-jul2026, collectri, reactome-v96, kinome-atlas, depmap-coessentiality). The former
        # id looked like a resolvable manifest (`*-per-gene-v1`) and would mislead a provenance auditor.
        # Match the established composed-card convention (see _live_readers adc-tce-modality-fit); the
        # real contributing sources are enumerated in `sources_wired` / `source_counts` above.
        "_data_source": "mechanism-composed (composed card; no direct S3 product — see sources_wired)",
    }
