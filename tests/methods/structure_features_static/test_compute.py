"""structure_features_static.compute — hermetic tests for the pure row-building kernels (B0, 2026-08-07).

No S3, no PDB/AlphaFold API — synthetic pLDDT arrays + domain coords + HGVSp hotspot strings + PDB entry
dicts. Pins: HGVSp→residue parsing (incl. 'p.' + 3-letter), pLDDT aggregation + disordered fraction,
per-domain min + low-confidence count, PDB best-resolution selection, and the v1 pLDDT pocket-adjacency
heuristic in all 4 enum states (no_structure / no_hotspots_annotated / adjacent / distant) — including the
conservative guarantee that a hotspot in a disordered region is NEVER called 'adjacent'.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.structure_features_static.compute import (  # noqa: E402
    parse_hgvsp_residue, aggregate_plddt, per_domain_plddt, pdb_coverage,
    pocket_adjacency, build_row, parse_cif_plddt, PLDDT_POCKET_MIN,
)


# ---------- CIF per-residue pLDDT parse (pure text, no structure lib) ----------
# Minimal AlphaFold-style _atom_site loop: 3 residues, one CA each, B-factor = pLDDT.
# Column order deliberately NOT the AF default (B_iso_or_equiv before Cartn_x) to prove the
# parser resolves columns by NAME, not position.
_MINI_CIF = """data_AF-TEST-F1
loop_
_atom_site.group_PDB
_atom_site.label_atom_id
_atom_site.label_seq_id
_atom_site.B_iso_or_equiv
_atom_site.Cartn_x
ATOM CA 1 85.0 1.0
ATOM CB 1 85.0 1.5
ATOM CA 2 95.5 2.0
ATOM CA 3 40.0 3.0
"""


def test_parse_cif_plddt_ca_only_in_order():
    plddt = parse_cif_plddt(_MINI_CIF)
    assert plddt == [85.0, 95.5, 40.0]   # 3 CA rows, in file order; the CB row ignored


def test_parse_cif_plddt_empty_and_malformed():
    assert parse_cif_plddt("") == []
    assert parse_cif_plddt("no atom_site loop here\njust text") == []
    # header present but no B-factor column → can't extract → []
    assert parse_cif_plddt("loop_\n_atom_site.group_PDB\n_atom_site.label_atom_id\nATOM CA\n") == []


def test_parse_cif_plddt_feeds_kernels_end_to_end():
    """The parsed array flows into aggregate_plddt + pocket_adjacency exactly like the live path."""
    plddt = parse_cif_plddt(_MINI_CIF)
    agg = aggregate_plddt(plddt)
    assert agg["alphafold_plddt_mean"] == round((85.0 + 95.5 + 40.0) / 3, 3)
    assert agg["disordered_fraction"] == round(1 / 3, 4)   # residue 3 (40.0) < 50
    # residue 2 (95.5) is high-confidence → a hotspot there is 'adjacent'
    s = pocket_adjacency([2], plddt=plddt, domains=[], has_structure=True)
    assert s["hotspot_pocket_adjacency_call"] == "adjacent"


# ---------- HGVSp → residue ----------
def test_parse_hgvsp_short_and_prefixed_and_threeletter():
    assert parse_hgvsp_residue("G12C") == 12
    assert parse_hgvsp_residue("p.G12C") == 12
    assert parse_hgvsp_residue("p.R175H") == 175
    assert parse_hgvsp_residue("p.Arg175His") == 175   # 3-letter ref aa
    assert parse_hgvsp_residue("V600E") == 600


def test_parse_hgvsp_unparseable_is_none():
    for bad in (None, "", "unknown", "NA", ".", "splice_region", 12, "p.?"):
        assert parse_hgvsp_residue(bad) is None


# ---------- pLDDT aggregation ----------
def test_aggregate_plddt_mean_min_disordered():
    # 5 residues: two disordered (<50), mean = (95+92+88+40+30)/5 = 69.0
    s = aggregate_plddt([95, 92, 88, 40, 30])
    assert s["alphafold_plddt_mean"] == 69.0
    assert s["alphafold_plddt_min"] == 30.0
    assert s["disordered_fraction"] == 0.4     # 2/5 below 50


def test_aggregate_plddt_empty_is_none():
    s = aggregate_plddt([])
    assert s["alphafold_plddt_mean"] is None and s["disordered_fraction"] is None


# ---------- per-domain pLDDT ----------
def test_per_domain_min_and_low_count():
    # array of 10 residues; domain A (1-3) high, domain B (6-8) low
    plddt = [95, 96, 94, 80, 80, 40, 45, 42, 80, 80]
    domains = [{"start": 1, "end": 3}, {"start": 6, "end": 8}]
    s = per_domain_plddt(plddt, domains)
    assert s["alphafold_plddt_min_domain"] == 40.0     # lowest domain-min (domain B)
    assert s["n_domains_low_plddt"] == 1               # only domain B < 70


def test_per_domain_clamps_out_of_bounds_and_handles_no_domains():
    plddt = [90, 90, 90]
    # domain end beyond the array is clamped, not an error
    assert per_domain_plddt(plddt, [{"start": 1, "end": 999}])["alphafold_plddt_min_domain"] == 90.0
    assert per_domain_plddt(plddt, [])["alphafold_plddt_min_domain"] is None
    assert per_domain_plddt(plddt, [])["n_domains_low_plddt"] == 0


# ---------- PDB coverage ----------
def test_pdb_best_resolution_selected():
    entries = [
        {"pdb_id": "1abc", "resolution_angstrom": 2.4, "method": "X-RAY DIFFRACTION"},
        {"pdb_id": "2def", "resolution_angstrom": 1.8, "method": "X-RAY DIFFRACTION"},
        {"pdb_id": "3ghi", "resolution_angstrom": 3.1, "method": "ELECTRON MICROSCOPY"},
    ]
    s = pdb_coverage(entries)
    assert s["pdb_ids_available"] == ["1ABC", "2DEF", "3GHI"]   # deduped, upper, sorted
    assert s["pdb_best_resolution_angstrom"] == 1.8            # finest resolution
    assert s["pdb_best_method"] == "X-RAY DIFFRACTION"


def test_pdb_no_resolution_entries_and_empty():
    nmr = pdb_coverage([{"pdb_id": "5xyz", "method": "SOLUTION NMR"}])
    assert nmr["pdb_ids_available"] == ["5XYZ"] and nmr["pdb_best_resolution_angstrom"] is None
    assert nmr["pdb_best_method"] == "SOLUTION NMR"
    empty = pdb_coverage([])
    assert empty["pdb_ids_available"] == [] and empty["pdb_best_method"] == "none"


# ---------- pocket adjacency (the 4 enum states) ----------
def test_pocket_no_structure():
    s = pocket_adjacency([12], plddt=[], domains=[], has_structure=False)
    assert s["hotspot_pocket_adjacency_call"] == "no_structure"
    assert s["mutation_hotspot_in_druggable_pocket"] is False


def test_pocket_no_hotspots_annotated():
    """Structure present but zero hotspots → no_hotspots_annotated (the enum value the old scaffold
    could never emit)."""
    s = pocket_adjacency([], plddt=[90, 90, 90], domains=[], has_structure=True)
    assert s["hotspot_pocket_adjacency_call"] == "no_hotspots_annotated"
    assert s["mutation_hotspot_in_druggable_pocket"] is False


def test_pocket_adjacent_when_hotspot_in_high_confidence_region():
    """KRAS-G12C-like: hotspot residue 12 sits in a high-pLDDT structured region → adjacent + druggable."""
    plddt = [95] * 20
    s = pocket_adjacency([12], plddt=plddt, domains=[{"start": 1, "end": 20}], has_structure=True)
    assert s["hotspot_pocket_adjacency_call"] == "adjacent"
    assert s["mutation_hotspot_in_druggable_pocket"] is True


def test_pocket_distant_when_hotspot_in_disordered_region():
    """CONSERVATIVE GUARANTEE: a hotspot in a low-pLDDT/disordered region is NEVER 'adjacent'."""
    plddt = [30] * 20   # all disordered
    s = pocket_adjacency([12], plddt=plddt, domains=[], has_structure=True)
    assert s["hotspot_pocket_adjacency_call"] == "distant"
    assert s["mutation_hotspot_in_druggable_pocket"] is False


def test_pocket_distant_when_protein_is_disorder_dominated():
    """PILOT-DRIVEN DISCRIMINATION (2026-08-07): a hotspot in a HIGH-pLDDT residue is STILL 'distant' if
    the protein overall is disorder-dominated (>=50% below pLDDT 50) — an AR/BRD4/NR3C1-class protein is
    not a credible SM-pocket scaffold even at a locally-ordered hotspot. Without this guard the pLDDT-only
    call saturated to all-adjacent."""
    # residue 12 is high-confidence (95) but 12 of 20 residues are disordered (60% > 50% floor)
    plddt = [30] * 11 + [95] + [30] * 8
    s = pocket_adjacency([12], plddt=plddt, domains=[], has_structure=True)
    assert s["hotspot_pocket_adjacency_call"] == "distant"
    assert s["mutation_hotspot_in_druggable_pocket"] is False


def test_pocket_adjacent_needs_only_one_structured_hotspot_in_ordered_protein():
    """In an ORDERED protein (not disorder-dominated), one recurrent hotspot in a high-pLDDT residue is
    enough to call adjacent."""
    # mostly ordered: only 2/12 disordered → below the 0.50 floor; residue 12 high
    plddt = [90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 30, 95]
    s = pocket_adjacency([12], plddt=plddt, domains=[], has_structure=True)
    assert s["hotspot_pocket_adjacency_call"] == "adjacent"


# ---------- build_row integration ----------
def test_build_row_full_schema_and_kras_like():
    plddt = [95] * 200
    row = build_row(
        "P01116", "KRAS",
        plddt=plddt,
        domains=[{"start": 1, "end": 166}],
        pdb_entries=[{"pdb_id": "6oim", "resolution_angstrom": 1.65, "method": "X-RAY DIFFRACTION"}],
        hotspot_hgvsp=["G12C", "G12D", "unknown"],   # 'unknown' dropped
        alphafold_prediction_id="AF-P01116-F1",
        alphafold_model_version="4",
        has_structure=True,
    )
    # all 15 documented columns present
    expected_cols = {
        "uniprot_ac", "gene_symbol", "pdb_ids_available", "pdb_best_resolution_angstrom",
        "pdb_best_method", "alphafold_prediction_id", "alphafold_model_version",
        "alphafold_plddt_mean", "alphafold_plddt_min", "alphafold_plddt_min_domain",
        "n_domains_low_plddt", "mutation_hotspot_in_druggable_pocket",
        "hotspot_pocket_adjacency_call", "disordered_fraction", "method_version",
    }
    assert set(row) == expected_cols
    assert row["hotspot_pocket_adjacency_call"] == "adjacent"    # G12 in a high-pLDDT structured domain
    assert row["mutation_hotspot_in_druggable_pocket"] is True
    assert row["pdb_best_resolution_angstrom"] == 1.65
    assert row["alphafold_plddt_mean"] == 95.0


def test_build_row_disordered_target_is_distant():
    row = build_row(
        "Q00000", "DISPROT",
        plddt=[20] * 100, domains=[], pdb_entries=[], hotspot_hgvsp=["S50P"],
        has_structure=True,
    )
    assert row["hotspot_pocket_adjacency_call"] == "distant"
    assert row["pdb_ids_available"] == []
    assert row["disordered_fraction"] == 1.0


# ---------- read._coerce_id_list: parquet returns list cols as numpy arrays (regression) ----------
def test_coerce_id_list_handles_ndarray_list_str_none():
    """Regression: parquet returns pdb_ids_available as a numpy ndarray; `arr or []` raises
    'truth value ambiguous'. _coerce_id_list must normalise ndarray/list/tuple/str/None → list.
    This bug shipped in read.py (never hit until the derived product existed) — B0 publish caught it."""
    import numpy as np
    from methods.structure_features_static.read import _coerce_id_list
    assert _coerce_id_list(np.array(["1ABC", "2DEF"])) == ["1ABC", "2DEF"]   # the failing case
    assert _coerce_id_list(["1ABC", "2DEF"]) == ["1ABC", "2DEF"]
    assert _coerce_id_list(("1ABC",)) == ["1ABC"]
    assert _coerce_id_list("1ABC") == ["1ABC"]
    assert _coerce_id_list(None) == []
    assert _coerce_id_list(np.array([])) == []
    assert _coerce_id_list("") == []
