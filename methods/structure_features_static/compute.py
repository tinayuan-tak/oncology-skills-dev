"""structure_features_static.compute — PURE compute kernels for the per-UniProt structural-feature row.

Separated from cli.py (the I/O + orchestration layer) so the row-building LOGIC is unit-testable against
synthetic fixtures WITHOUT any live PDB/AlphaFold/S3 read (B0, 2026-08-07). Each function takes already-
loaded inputs (a pLDDT array, InterPro domain coords, HGVSp hotspot strings, PDB entry dicts) and returns
the raw columns the derived parquet stores; read.py then derives the display CLASSES from those raw columns.

v1 pocket-adjacency is a pLDDT + domain-context HEURISTIC (no external structure lib): a hotspot residue
sitting in a high-confidence, structured (high-pLDDT) region is a candidate druggable-pocket location; a
hotspot in a low-pLDDT / intrinsically-disordered region is NOT. Real solvent-accessibility (freesasa) +
cavity detection (fpocket / canSAR) is the documented iter-2 upgrade (see the card caveats + the B0 plan).
The card's own caveat prescribes exactly this pLDDT-heuristic for iter-1.
"""
from __future__ import annotations

import re
from typing import Optional

METHOD_VERSION = "0.1.0"

# pLDDT bands (AlphaFold convention; matches the card thresholds + read.py classifier).
PLDDT_DISORDERED_MAX = 50.0     # residues below this are treated as disordered/very-low-confidence
PLDDT_LOW_DOMAIN_MAX = 70.0     # a domain whose min pLDDT is below this is "low-confidence" (n_domains_low_plddt)
PLDDT_POCKET_MIN = 70.0         # a hotspot in a region at/above this confidence is a candidate structured pocket

# HGVSp short form, optionally 'p.'-prefixed: <ref-aa><pos><alt-aa|Ter|fs|*|=|del|dup|ins...>.
# We only need the integer residue POSITION. Accepts 'G12C', 'p.G12C', 'p.Arg175His' (3-letter), etc.
_HGVSP_POS_RE = re.compile(r'^p?\.?[A-Za-z]{1,3}(\d+)')


def parse_hgvsp_residue(hgvsp) -> Optional[int]:
    """Extract the 1-indexed residue POSITION from an HGVSp_Short string ('G12C'→12, 'p.R175H'→175,
    'p.Arg175His'→175). Returns None for empty / 'unknown' / non-substitution strings we can't anchor
    to a single residue (splice, intronic, or unparseable). Conservative: a None hotspot simply does
    not contribute to pocket-adjacency (never a false pocket)."""
    if not isinstance(hgvsp, str):
        return None
    s = hgvsp.strip()
    if not s or s.lower() in ("unknown", "na", "none", "."):
        return None
    m = _HGVSP_POS_RE.match(s)
    if not m:
        return None
    try:
        pos = int(m.group(1))
    except (ValueError, TypeError):
        return None
    return pos if pos > 0 else None


def aggregate_plddt(plddt: list) -> dict:
    """Per-protein pLDDT summary from the per-residue array. Returns mean, min, and disordered_fraction
    (fraction of residues below PLDDT_DISORDERED_MAX). Empty/None input → all-None (data_unavailable)."""
    vals = [float(v) for v in (plddt or []) if v is not None]
    if not vals:
        return {"alphafold_plddt_mean": None, "alphafold_plddt_min": None, "disordered_fraction": None}
    n = len(vals)
    disordered = sum(1 for v in vals if v < PLDDT_DISORDERED_MAX)
    return {
        "alphafold_plddt_mean": round(sum(vals) / n, 3),
        "alphafold_plddt_min": round(min(vals), 3),
        "disordered_fraction": round(disordered / n, 4),
    }


def per_domain_plddt(plddt: list, domains: list) -> dict:
    """Per-DOMAIN pLDDT confidence. For each InterPro domain {start,end} (1-indexed, inclusive), take the
    MIN pLDDT across its residues; report the lowest such domain-min (alphafold_plddt_min_domain) and the
    count of domains whose min falls below PLDDT_LOW_DOMAIN_MAX (n_domains_low_plddt). A domain the target
    doesn't have, or coordinates outside the array, is skipped safely. No domains / no pLDDT → None / 0."""
    vals = [float(v) if v is not None else None for v in (plddt or [])]
    domain_mins: list[float] = []
    for d in (domains or []):
        start, end = d.get("start"), d.get("end")
        if start is None or end is None:
            continue
        # 1-indexed inclusive → python slice; clamp to the array bounds.
        lo = max(1, int(start)); hi = min(len(vals), int(end))
        window = [v for v in vals[lo - 1:hi] if v is not None]
        if window:
            domain_mins.append(min(window))
    if not domain_mins:
        return {"alphafold_plddt_min_domain": None, "n_domains_low_plddt": 0}
    return {
        "alphafold_plddt_min_domain": round(min(domain_mins), 3),
        "n_domains_low_plddt": int(sum(1 for m in domain_mins if m < PLDDT_LOW_DOMAIN_MAX)),
    }


def pdb_coverage(pdb_entries: list) -> dict:
    """Summarise experimental PDB coverage from a list of entry dicts
    ({pdb_id, resolution_angstrom, method}). Returns the id list, best (lowest) resolution, and the
    method of that best entry. Empty → no coverage. read.py derives pdb_coverage_class from the id count."""
    entries = [e for e in (pdb_entries or []) if isinstance(e, dict) and e.get("pdb_id")]
    if not entries:
        return {"pdb_ids_available": [], "pdb_best_resolution_angstrom": None, "pdb_best_method": "none"}
    ids = sorted({str(e["pdb_id"]).upper() for e in entries})
    # "best" = finest (lowest) resolution among entries that report one; ties/absent handled gracefully.
    with_res = [e for e in entries if isinstance(e.get("resolution_angstrom"), (int, float))]
    if with_res:
        best = min(with_res, key=lambda e: e["resolution_angstrom"])
        return {"pdb_ids_available": ids,
                "pdb_best_resolution_angstrom": round(float(best["resolution_angstrom"]), 2),
                "pdb_best_method": str(best.get("method") or "unknown")}
    # entries exist but none report resolution (e.g. NMR / cryo-EM without a resolution field)
    return {"pdb_ids_available": ids, "pdb_best_resolution_angstrom": None,
            "pdb_best_method": str(entries[0].get("method") or "unknown")}


def pocket_adjacency(hotspot_residues: list, plddt: list, domains: list,
                     has_structure: bool) -> dict:
    """v1 pLDDT+domain HEURISTIC pocket-adjacency call.

    Returns mutation_hotspot_in_druggable_pocket (bool) + hotspot_pocket_adjacency_call (the 4-value
    card enum). Logic, conservative by construction:
      - no_structure          : neither PDB nor AlphaFold coverage (has_structure False / no pLDDT).
      - no_hotspots_annotated : structure exists but the gene has ZERO parseable hotspot residues.
      - adjacent              : >=1 hotspot residue sits in a HIGH-confidence structured region
                                (pLDDT >= PLDDT_POCKET_MIN) — a candidate druggable-pocket location.
      - distant               : hotspots exist + structure exists, but ALL hotspot residues fall in
                                low-pLDDT / disordered regions (not a credible small-molecule pocket).
    mutation_hotspot_in_druggable_pocket is True iff the call is 'adjacent'. NOTE: pLDDT is a CONFIDENCE
    proxy, not a cavity/SASA measurement — a high-pLDDT hotspot is a CANDIDATE, upgraded by fpocket/canSAR
    in iter-2. The heuristic never calls 'adjacent' without a structured hotspot, so it cannot manufacture
    a pocket where the structure is disordered."""
    vals = [float(v) if v is not None else None for v in (plddt or [])]
    structured = has_structure and any(v is not None for v in vals)
    if not structured:
        return {"mutation_hotspot_in_druggable_pocket": False,
                "hotspot_pocket_adjacency_call": "no_structure"}

    residues = [r for r in (hotspot_residues or []) if isinstance(r, int) and r > 0]
    if not residues:
        return {"mutation_hotspot_in_druggable_pocket": False,
                "hotspot_pocket_adjacency_call": "no_hotspots_annotated"}

    for res in residues:
        if 1 <= res <= len(vals):
            v = vals[res - 1]
            if v is not None and v >= PLDDT_POCKET_MIN:
                return {"mutation_hotspot_in_druggable_pocket": True,
                        "hotspot_pocket_adjacency_call": "adjacent"}
    # hotspots exist but none land in a high-confidence structured region
    return {"mutation_hotspot_in_druggable_pocket": False,
            "hotspot_pocket_adjacency_call": "distant"}


def build_row(uniprot_ac: str, gene_symbol: str, *,
              plddt: list, domains: list, pdb_entries: list, hotspot_hgvsp: list,
              alphafold_prediction_id: Optional[str] = None,
              alphafold_model_version: Optional[str] = None,
              has_structure: bool = True) -> dict:
    """Assemble ONE derived-parquet row from already-loaded inputs. Pure — no I/O. The 15-column schema
    matches cli.py's documented columns + read.py's consumed keys. `has_structure` lets the caller signal
    'no PDB and no AlphaFold model' independent of an empty pLDDT array."""
    residues = sorted({r for r in (parse_hgvsp_residue(h) for h in (hotspot_hgvsp or [])) if r is not None})
    row = {
        "uniprot_ac": uniprot_ac,
        "gene_symbol": gene_symbol,
        "alphafold_prediction_id": alphafold_prediction_id,
        "alphafold_model_version": alphafold_model_version,
        "method_version": METHOD_VERSION,
    }
    row.update(pdb_coverage(pdb_entries))
    row.update(aggregate_plddt(plddt))
    row.update(per_domain_plddt(plddt, domains))
    row.update(pocket_adjacency(residues, plddt, domains, has_structure))
    return row
