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

from pathlib import Path

# Ensure methods/ is on sys.path for sibling imports
_METHODS_ROOT = Path(__file__).resolve().parent.parent

from onc_methods.collectri_tf_regulon import read as collectri_read
from onc_methods.depmap_coessentiality import read as coessentiality_read
from onc_methods.kinome_atlas_prediction import read as kinome_atlas_read
from onc_methods.reactome_pathway_context import read as reactome_read
from onc_methods.signor_mechanism_network import read as signor_read
from onc_methods.signor_mechanism_network.moa_ontology import ONTOLOGY_VERSION

# network_class edge-count cutoffs: single-sourced from the SIGNOR reader (which in turn MIRRORS the
# CANONICAL cards/signaling-network-mechanism.card.yaml `thresholds:`) so the composed and per-source
# classifiers cannot drift apart. Pinned to the card by
# tests/methods/mechanism_composed/test_network_class_threshold_mirror_guard.py.
from onc_methods.signor_mechanism_network.read import MAX_EDGES_SPARSE, MIN_EDGES_WELL_CHARACTERIZED
from onc_methods.target_id_sidecar import is_definitively_absent


def _is_genuine_absence(e: Exception) -> bool:
    """True IFF `e` means the underlying data product genuinely does not exist.

    Mirrors the honest-loud read contract established across the read path
    (#783/#797/#712/#800/#715): a missing S3 object (NoSuchKey / 404 / NoSuchBucket)
    or a missing local file is honest `data_unavailable`; anything else — expired
    creds / AccessDenied, throttling / SlowDown / 5xx / timeouts, a broken env —
    must RE-RAISE so it surfaces loudly instead of being silently encoded as a real
    absence classification (which on the verdict-driving SIGNOR lane also drops
    mechanism_verdict off its rung and, via risk_projection.py, manufactures a false
    'Right Target' biological-risk escalation).
    """
    return isinstance(e, FileNotFoundError) or is_definitively_absent(e)


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
        existing.setdefault("_class_disagreement", []).append(
            {
                "source": new_source,
                "moa_class": new_edge["moa_class"],
                "raw_mechanism": new_edge.get("raw_mechanism", ""),
            }
        )
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


def _coessentiality_source_note(coessentiality_result: dict) -> str:
    """Build the co-essentiality provenance note from the live pin + read counts.

    SK#1810: the note previously hardcoded "DepMap 26Q1 CRISPR Chronos ... (1,538
    cell lines)" while the reader (methods/depmap_coessentiality/read.py) resolves
    `depmap-coessentiality-26q3-v1`, so the emitted n_cell_lines could disagree with
    the hardcoded count. Derive both the release label and the cell-line count from
    the actual resolved manifest / read result instead.
    """
    manifest_id = getattr(coessentiality_read, "MANIFEST_ID", "depmap-coessentiality")
    n_cell_lines = coessentiality_result.get("n_cell_lines", 0) or 0
    return f"DepMap ({manifest_id}) CRISPR Chronos pan-cancer co-essentiality ({n_cell_lines} cell lines)"


def _classify_network(n_up: int, n_down: int) -> str:
    """Classify network shape from DEDUPED union counts (distinct (partner, direction)).

    Same thresholds as the SIGNOR/CollecTri readers for cross-source consistency,
    but note the counts here are distinct-PARTNER counts (the union dedups on
    (partner_symbol, direction)), whereas the per-source readers count raw edge
    rows. Unioning two sources usually RAISES the distinct-partner count (may
    promote partial→well_characterized), but for a target reached by many
    mechanisms to FEW partners the deduped union count can be LOWER than a single
    source's raw-row count — so composition is not monotonic. Thresholds are
    annotation-density heuristics (≥3 each arm / ≤1 total), not biological cutoffs.
    """
    if n_up == 0 and n_down == 0:
        return "data_unavailable"
    if n_up >= MIN_EDGES_WELL_CHARACTERIZED and n_down >= MIN_EDGES_WELL_CHARACTERIZED:
        return "well_characterized"
    if n_up + n_down <= MAX_EDGES_SPARSE:
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
        # SIGNOR is the VERDICT-DRIVING lane: an empty edge union collapses network_class to
        # data_unavailable and drops mechanism_verdict off its rung, and via the shared risk
        # projector escalates the 'Right Target' biological-risk bin to MED. So a transient S3
        # error must NOT be silently encoded as a real absence (#770). Re-raise anything that is
        # not a genuine not-found; keep the clean empty-lane result only for true absence.
        if not _is_genuine_absence(e):
            raise
        signor_result = {"_data_note": f"signor_absent: {e}", "upstream_regulators": [], "downstream_effectors": []}

    try:
        collectri_result = collectri_read.read_target_summary(target, indication)
        if collectri_result.get("network_class") not in (None, "data_unavailable"):
            sources_wired.append(SOURCE_KEY_COLLECTRI)
    except Exception as e:
        collectri_result = {
            "_data_note": f"collectri_failed: {e}",
            "upstream_regulators": [],
            "downstream_effectors": [],
        }

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
        kinome_atlas_result = {
            "_data_note": f"kinome_atlas_failed: {e}",
            "upstream_regulators": [],
            "downstream_effectors": [],
        }

    # Sprint 4 (2026-08-10): DepMap co-essentiality lane — functional dependency
    # evidence (correlated CRISPR profiles across 1,538 cell lines). Kept separate
    # from the curated mechanism edge union; positive r = co-essential, negative r =
    # anti-correlated dependency (buffering / SL candidate direction).
    coessentiality_result: dict = {}
    try:
        coessentiality_result = coessentiality_read.read_coessential_partners(target, top_n=25)
        if not coessentiality_result.get("_data_unavailable"):
            sources_wired.append(SOURCE_KEY_COESSENTIALITY)
    except Exception as e:
        # Display-only (lower stakes than SIGNOR) but the same honest-loud contract applies (#770):
        # a transient read error must surface, not masquerade as a genuine substrate absence.
        if not _is_genuine_absence(e):
            raise
        coessentiality_result = {
            "_data_unavailable": True,
            "_data_note": f"coessentiality_absent: {e}",
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
    high_conf_edges = sum(1 for e in (union_upstream + union_downstream) if e.get("n_sources_supporting", 1) >= 2)

    # MoA classes aggregated across the union
    moa_classes_present = sorted({e.get("moa_class") for e in union_upstream if e.get("moa_class")})
    pd_classes_present = sorted({e.get("moa_class") for e in union_downstream if e.get("moa_class")})

    # has_actionable_moa / has_pd_marker require at least one edge carrying a MAPPED MoA class
    # (moa_class present and != "unmapped"). The field name promises a CLASSIFIED mechanism / PD
    # hook — a purely count-based (>= 1 edge) predicate over-called it True even when EVERY edge
    # fell to the ontology's 'unmapped' bucket (no actionable MoA class, empty modality_relevance).
    # ~4.2% of curated edges are unmapped, so this only flips all-unmapped-arm targets; the composed
    # network_class (verdict axis) and the EGFR/CEACAM5 replay fixtures are byte-stable.
    def _has_mapped_moa(edges: list[dict]) -> bool:
        return any(e.get("moa_class") and e.get("moa_class") != "unmapped" for e in edges)

    # Aggregated unmapped fraction (weighted)
    signor_total_edges = len(signor_up) + len(signor_dn)
    collectri_total_edges = len(collectri_up) + len(collectri_dn)
    total = signor_total_edges + collectri_total_edges
    signor_frac = signor_result.get("moa_ontology_unmapped_fraction", 0.0) or 0.0
    collectri_frac = collectri_result.get("moa_ontology_unmapped_fraction", 0.0) or 0.0
    if total > 0:
        unmapped_frac = (signor_frac * signor_total_edges + collectri_frac * collectri_total_edges) / total
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
        "has_actionable_moa": _has_mapped_moa(union_upstream),
        "has_pd_marker": _has_mapped_moa(union_downstream),
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
            # Provenance drift fix (SK#1810): derive the note from the live pin +
            # the actually-read cell-line count instead of a hardcoded release/count
            # (was stale "26Q1 ... 1,538 cell lines" while the reader resolves 26q3).
            "source_note": _coessentiality_source_note(coessentiality_result),
        },
        # Honest provenance (2026-08-11): there is NO `mechanism-composed-per-gene-v1` derived
        # manifest in the catalog — this product is COMPOSED ON READ from the upstream source readers
        # (signor-jul2026, collectri, reactome-v96, kinome-atlas, depmap-coessentiality). The former
        # id looked like a resolvable manifest (`*-per-gene-v1`) and would mislead a provenance auditor.
        # Match the established composed-card convention (see _live_readers adc-tce-modality-fit); the
        # real contributing sources are enumerated in `sources_wired` / `source_counts` above.
        "_data_source": "mechanism-composed (composed card; no direct S3 product — see sources_wired)",
    }
