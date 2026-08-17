"""read_abundance_density_summary (surface-abundance-density card, Tier 1.2, 2026-07-23).

Estimated surface copies-per-cell: anchor an absolute scale on the HPA IHC intensity for the tumor
tissue-of-origin, then shift by the CPTAC tumor-vs-normal log2FC. RANGED + estimated-tier; the band
WIDENS when the anchor is weak (breadth-only) or CPTAC is absent, so the card's wide_uncertainty_band
warning fires honestly. `unmeasured` (never a fabricated number) when the HPA anchor is missing.

No S3: the HPA anchor (cli.load_and_classify) and the CPTAC row (read_target_summary) are both
monkeypatched to synthetic values so the calibration + band arithmetic is pinned deterministically.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = importlib.import_module("methods.cptac_protein_deg.read")
_hpa = importlib.import_module("methods.hpa_normal_tissue_liability.cli")


def _patch_hpa(monkeypatch, *, breadth, specific=None):
    """Stub HPA load_and_classify → a normal-tissue-liability summary shape."""
    monkeypatch.setattr(_hpa, "load_and_classify",
                        lambda gene, hpa_path=None: {
                            "normal_tissue_breadth_class": breadth,
                            "specific_tissues": specific or [],
                        })


def _patch_cptac(monkeypatch, *, cls, effect, cohort="COAD"):
    """Stub read_target_summary → a CPTAC per-cohort summary shape."""
    monkeypatch.setattr(r, "read_target_summary",
                        lambda target, indication=None: {
                            "cohort": cohort,
                            "protein_expression_class": cls,
                            "protein_effect_size": effect,
                        })


@pytest.fixture(autouse=True)
def _no_ladder(monkeypatch):
    """Default: force the ladder to return None so the grade-D estimate tests are isolated from the
    committed governed corpus (a target like ERBB2 IS in the corpus and would otherwise override).
    The ladder-override tests below opt OUT of this by re-patching _ladder_measurement explicitly."""
    monkeypatch.setattr(r, "_ladder_measurement", lambda target, indication=None: None)


def test_tissue_specific_anchor_high_and_tce_viable(monkeypatch):
    # intestine enriched intensity 5e7 (> p66 7.43e6) → IHC 'high' (center 3e5); CPTAC modest_up.
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e7}])
    _patch_cptac(monkeypatch, cls="modest_up", effect=1.05)
    d = r.read_abundance_density_summary("CEACAM5", "COADREAD")
    assert d["hpa_ihc_intensity_class"] == "high"
    assert d["density_evidence_level"] == "D"   # inferred from priors, not calibrated flow
    assert d["_anchor_strength"] == "tissue_specific"
    assert d["_cptac_covered"] is True
    # 3e5 * 2**1.05 ~= 6.2e5 → > 10,000 → high; TCE + high-payload ADC both viable
    assert d["surface_density_class"] == "high"
    assert d["is_tce_viable"] is True
    assert d["is_adc_high_payload_viable"] is True
    # ordering + tight band (factor 12, both anchors strong)
    assert d["estimated_copies_per_cell_lower"] < d["estimated_copies_per_cell_median"] \
        < d["estimated_copies_per_cell_upper"]
    assert d["_band_factor"] == 12.0


def test_tissue_specific_tertiles(monkeypatch):
    # below p33 (8.05e5) → low; between p33 and p66 → medium
    _patch_cptac(monkeypatch, cls="not_significant", effect=0.0)
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e5}])
    assert r.read_abundance_density_summary("X", "COAD")["hpa_ihc_intensity_class"] == "low"
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 2.0e6}])
    assert r.read_abundance_density_summary("X", "COAD")["hpa_ihc_intensity_class"] == "medium"


def test_breadth_only_anchor_widens_band(monkeypatch):
    # BRCA tissue-of-origin is NOT in HPA's enriched vocab → breadth-only medium anchor, factor *1.6.
    _patch_hpa(monkeypatch, breadth="broad_normal_expression", specific=[])
    _patch_cptac(monkeypatch, cls="not_significant", effect=0.5, cohort="BRCA")
    d = r.read_abundance_density_summary("ERBB2", "BRCA")
    assert d["_anchor_strength"] == "breadth_only"
    assert d["hpa_ihc_intensity_class"] == "medium"
    assert d["_band_factor"] == pytest.approx(12.0 * 1.6)   # breadth-only widen, CPTAC covered
    assert d["hpa_ihc_anchor_used"].startswith("HPA broad_normal_expression")


def test_cptac_absent_is_anchor_only_not_unmeasured(monkeypatch):
    # HPA anchor present but the target has NO CPTAC coverage → anchor-only (shift=1), band widened,
    # still a real number (NOT unmeasured — the normal-tissue anchor alone is defensible first-pass).
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e7}])
    _patch_cptac(monkeypatch, cls="data_unavailable", effect=None)
    d = r.read_abundance_density_summary("CEACAM5", "COAD")
    assert d["surface_density_class"] != "unmeasured"
    assert d["_cptac_covered"] is False
    assert d["estimated_copies_per_cell_median"] == pytest.approx(3.0e5)  # shift = 1.0
    assert d["_band_factor"] == pytest.approx(12.0 * 1.6)                  # CPTAC-absent widen


def test_no_hpa_anchor_is_unmeasured(monkeypatch):
    # No HPA call at all → unmeasured; never fabricate a copies/cell number.
    _patch_hpa(monkeypatch, breadth="data_unavailable", specific=[])
    _patch_cptac(monkeypatch, cls="strong_up", effect=2.0)
    d = r.read_abundance_density_summary("GHOST", "COAD")
    assert d["surface_density_class"] == "unmeasured"
    assert d["density_evidence_level"] == "E"   # expression only; no density estimate
    assert d["hpa_ihc_intensity_class"] == "unmeasured"
    assert d["estimated_copies_per_cell_median"] is None
    assert d["is_tce_viable"] is False
    assert d["is_adc_high_payload_viable"] is False


def test_low_anchor_straddles_tce_threshold(monkeypatch):
    # restricted breadth → 'low' IHC class (center 3e3, straddles the 1,000/cell TCE threshold);
    # a slight CPTAC down-shift drops the median below threshold → moderate/low boundary honesty.
    _patch_hpa(monkeypatch, breadth="restricted_normal_expression", specific=[])
    _patch_cptac(monkeypatch, cls="modest_down", effect=-1.0)   # shift 0.5 → 1500/cell
    d = r.read_abundance_density_summary("X", "PRAD")
    assert d["hpa_ihc_intensity_class"] == "low"
    # 3e3 * 0.5 = 1500 → >= 1000 → moderate (TCE-viable, but wide band spans the threshold)
    assert d["surface_density_class"] == "moderate"
    assert d["is_adc_high_payload_viable"] is False


def test_normal_absence_abstains_not_tumor_absent(monkeypatch):
    # S1-2 (cards review 2026-08-17): normal-tissue ABSENCE (`not_detected_in_normal`) is the ideal
    # tumor-restricted-antigen profile (DLL3), NOT evidence of tumor absence. It must ABSTAIN
    # (unmeasured / grade-E), never anchor a tumor `not_detected` — which previously mis-set a very-low
    # copies/cell AND fired the surface `ihc-not-detected-killer` → false `neither_viable`.
    # (Was: test_not_detected_maps_very_low, which pinned the buggy `not_detected` → low mapping.)
    _patch_hpa(monkeypatch, breadth="not_detected_in_normal", specific=[])
    _patch_cptac(monkeypatch, cls="not_significant", effect=0.0)
    d = r.read_abundance_density_summary("X", "COAD")
    assert d["hpa_ihc_intensity_class"] == "unmeasured"       # abstain — never a tumor not_detected
    assert d["hpa_ihc_intensity_class"] != "not_detected"     # the killer trigger must not be produced
    assert d["surface_density_class"] == "unmeasured"         # honest grade-E, no fabricated number
    assert d["density_evidence_level"] == "E"
    assert d["is_tce_viable"] is False


# --- LADDER OVERRIDE (2026-07-23): governed measured anchor is PRIMARY over the grade-D estimate ---
def _patch_ladder(monkeypatch, payload):
    """Stub the ladder read_absolute_density (imported inside _ladder_measurement)."""
    import methods.surface_antigen_density_ladder as _ladder
    monkeypatch.setattr(_ladder, "read_absolute_density",
                        lambda target, indication=None: payload)


def test_ladder_measurement_overrides_estimate(monkeypatch):
    # ladder has a grade-A patient measurement → it is PRIMARY; grade-D estimate retained as context.
    monkeypatch.undo()  # drop the autouse _no_ladder patch for this test
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e7}])  # would be grade-D 'high'
    _patch_cptac(monkeypatch, cls="modest_up", effect=1.05)
    _patch_ladder(monkeypatch, {
        "absolute_density_class": "low", "density_evidence_level": "A", "value_best": 110.0,
        "reported_unit": "molecules/cell", "value_qualifier_best": "mean_with_reported_range",
        "measurement_semantics_best": "direct_molecule_count", "record_partition_best": "native_patient",
        "n_admissible_measurements": 10, "n_patient": 10, "n_cell_line": 0,
    })
    d = r.read_abundance_density_summary("CD19", "MM")
    # measured anchor wins: class from the measurement (low), grade A, source flagged
    assert d["surface_density_class"] == "low"
    assert d["density_evidence_level"] == "A"
    assert d["_density_source"] == "governed_ladder"
    assert d["absolute_value_best"] == 110.0
    assert d["absolute_reported_unit"] == "molecules/cell"
    assert d["absolute_record_partition"] == "native_patient"
    # viability flags follow the MEASURED class, not the grade-D estimate (which would have said 'high')
    assert d["is_tce_viable"] is False and d["is_adc_high_payload_viable"] is False
    # grade-D estimate is retained alongside as context (would have been 'high')
    assert d["_estimate_grade_d_class"] == "high"


def test_ladder_empty_falls_through_to_estimate(monkeypatch):
    # ladder grade E (no measurement) → fall through to the grade-D estimate.
    monkeypatch.undo()
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e7}])
    _patch_cptac(monkeypatch, cls="modest_up", effect=1.05)
    _patch_ladder(monkeypatch, {"absolute_density_class": "no_absolute_measurement",
                                "density_evidence_level": "E", "value_best": None})
    d = r.read_abundance_density_summary("CEACAM5", "COADREAD")
    assert d["density_evidence_level"] == "D"
    assert d.get("_density_source", "estimate") != "governed_ladder"
    assert d["surface_density_class"] == "high"


@pytest.mark.requires_data
def test_committed_corpus_target_reads_grade_ab_live(monkeypatch):
    # integration: a real corpus target reads from the governed ladder, not the estimate.
    monkeypatch.undo()  # drop the autouse _no_ladder patch → use the real committed corpus
    d = r.read_abundance_density_summary("MET", "COADREAD")
    assert d["_density_source"] == "governed_ladder"
    assert d["density_evidence_level"] in ("A", "A-", "B", "B-")
    assert d["absolute_value_best"] is not None


# --- SURFACE-ACCESSIBILITY SOFT GATE (P8.1 Slice 1, 2026-08-05): TOPOLOGY-keyed, labels admissibility,
# NEVER suppresses ----------------------------------------------------------------------------------
# Now keys on the TMbed predicted-topology product (topology_class + ecd_orientation) instead of the
# discredited surfaceome is_surface_protein OR-union. Require an EXTRACELLULAR membrane-spanning
# topology to call a whole-cell number a "surface density"; whole-cell estimate ALWAYS retained.
# Absence / ambiguity is NEVER negative evidence (→ provisional). GPI under-called (Slice 2).
def _patch_topology(monkeypatch, *, topology_class, ecd_orientation="outside"):
    import methods.topology_predictions_tmbed.read as _topo
    payload = {"topology_class": topology_class, "ecd_orientation": ecd_orientation}
    monkeypatch.setattr(_topo, "read_target_summary", lambda target, indication=None: dict(payload))


def _patch_gpi(monkeypatch, *, is_gpi, note="GPI-anchor amidated serine"):
    # Patch the GPI-anchor reader the no_transmembrane branch consults (P8.1 Slice 2). Hermetic:
    # no_transmembrane tests MUST patch this or they'd hit a live S3 read.
    import methods.uniprot_gpi_anchor.read as _gpi
    payload = {"is_gpi_anchored": is_gpi, "gpi_lipid_note": note if is_gpi else None,
               "uniprot_ac": "Q_TEST" if is_gpi else None}
    monkeypatch.setattr(_gpi, "read_gpi_anchor", lambda target, indication=None: dict(payload))


def test_unsupported_retains_estimate_but_flags_not_surface(monkeypatch):
    # no_transmembrane + NOT GPI-anchored (the NRAS/GAPDH case) -> unsupported. The whole-cell estimate
    # is RETAINED (visibility), but the surface class is relabeled + viability flags False.
    _patch_topology(monkeypatch, topology_class="no_transmembrane", ecd_orientation="inside")
    _patch_gpi(monkeypatch, is_gpi=False)
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e7}])
    _patch_cptac(monkeypatch, cls="strong_up", effect=2.0)
    d = r.read_abundance_density_summary("KRAS", "COADREAD")
    assert d["surface_density_admissibility"] == "unsupported"
    assert d["surface_density_class"] == "not_surface_density_whole_cell_estimate"
    assert d["density_evidence_level"] == "D"
    assert d["estimated_copies_per_cell_median"] is not None    # RETAINED, not nulled
    assert d["_whole_cell_class"] == "high"                     # raw class preserved for audit
    assert d["is_tce_viable"] is False and d["is_adc_high_payload_viable"] is False


def test_admissible_when_extracellular_topology(monkeypatch):
    # multi_pass with ECD outside (the STEAP1 case — a real ADC/TCE target the OR-union MISSED) ->
    # admissible, normal surface call.
    _patch_topology(monkeypatch, topology_class="multi_pass", ecd_orientation="outside")
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e7}])
    _patch_cptac(monkeypatch, cls="modest_up", effect=1.05)
    d = r.read_abundance_density_summary("STEAP1", "PRAD")
    assert d["surface_density_admissibility"] == "admissible"
    assert d["surface_density_class"] == "high"
    assert d["is_tce_viable"] is True


def test_coverage_gap_is_provisional_not_unsupported(monkeypatch):
    # topology data_unavailable (coverage gap) -> provisional (absence is NOT negative evidence).
    # Estimate retained + surface call kept (weaker confidence), NOT relabeled unsupported.
    _patch_topology(monkeypatch, topology_class="data_unavailable")
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e7}])
    _patch_cptac(monkeypatch, cls="modest_up", effect=1.05)
    d = r.read_abundance_density_summary("NOVELSURF", "COADREAD")
    assert d["surface_density_admissibility"] == "provisional"
    assert d["surface_density_class"] == "high"      # kept, not relabeled
    assert d["estimated_copies_per_cell_median"] is not None


def test_membrane_spanning_orientation_uncertain_is_provisional(monkeypatch):
    # single_pass_type_other (membrane-spanning but ECD orientation ambiguous) -> provisional, not
    # unsupported: we have a TM domain but can't confirm extracellular exposure.
    _patch_topology(monkeypatch, topology_class="single_pass_type_other", ecd_orientation="unknown")
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e7}])
    _patch_cptac(monkeypatch, cls="modest_up", effect=1.05)
    d = r.read_abundance_density_summary("AMBIGSURF", "COADREAD")
    assert d["surface_density_admissibility"] == "provisional"
    assert d["surface_density_class"] == "high"


def test_gpi_anchored_rescued_to_admissible_slice2(monkeypatch):
    # P8.1 Slice 2: a GPI-anchored antigen (MSLN) presents as no_transmembrane in TMbed 1D topology
    # (a GPI anchor has no membrane-spanning segment), but UniProt curated LIPID features say GPI-
    # anchored -> RESCUED to admissible (GPI antigens ARE displayed on the outer leaflet).
    _patch_topology(monkeypatch, topology_class="no_transmembrane", ecd_orientation="outside")
    _patch_gpi(monkeypatch, is_gpi=True)
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e7}])
    _patch_cptac(monkeypatch, cls="modest_up", effect=1.05)
    d = r.read_abundance_density_summary("MSLN", "MESO")
    assert d["surface_density_admissibility"] == "admissible"      # rescued via GPI
    assert d["_gpi_anchored"] is True
    assert "gpi_anchored_external" in d["surface_accessibility_note"]
    assert d["surface_density_class"] == "high"
    assert d["estimated_copies_per_cell_median"] is not None


def test_no_transmembrane_non_gpi_stays_unsupported(monkeypatch):
    # The specificity guard: no_transmembrane + NOT GPI (NRAS: cytoplasmic lipid-anchor) stays
    # unsupported. GPI rescue must NOT fire for non-GPI proteins.
    _patch_topology(monkeypatch, topology_class="no_transmembrane", ecd_orientation="inside")
    _patch_gpi(monkeypatch, is_gpi=False)
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e7}])
    _patch_cptac(monkeypatch, cls="modest_up", effect=1.05)
    d = r.read_abundance_density_summary("NRAS", "COADREAD")
    assert d["surface_density_admissibility"] == "unsupported"
    assert d["_gpi_anchored"] is False
    assert d["surface_density_class"] == "not_surface_density_whole_cell_estimate"


@pytest.mark.requires_data
def test_ladder_measurement_ignores_accessibility_gate(monkeypatch):
    # a ladder measurement is direct surface evidence -- the soft gate never touches it.
    monkeypatch.undo()
    _patch_topology(monkeypatch, topology_class="no_transmembrane", ecd_orientation="inside")  # adversarial
    d = r.read_abundance_density_summary("MET", "COADREAD")
    assert d["_density_source"] == "governed_ladder"
    assert d["absolute_value_best"] is not None
    assert "surface_density_admissibility" not in d   # ladder path has no soft-gate label


def test_nonfinite_cptac_log2fc_does_not_produce_inf(monkeypatch):
    # a degenerate CPTAC effect (inf: tumor-detected/normal-absent) must NOT yield an inf estimate;
    # it falls back to anchor-only (shift=1). Regression for the STEAP1 effect=inf bug.
    import math
    _patch_topology(monkeypatch, topology_class="multi_pass", ecd_orientation="outside")  # STEAP1 is 6-TM
    _patch_hpa(monkeypatch, breadth="broad_normal_expression", specific=[])   # medium anchor, center 3e4
    _patch_cptac(monkeypatch, cls="not_significant", effect=float("inf"))
    d = r.read_abundance_density_summary("STEAP1", "PRAD")
    assert d["estimated_copies_per_cell_median"] is not None
    assert math.isfinite(d["estimated_copies_per_cell_median"])
    assert d["_cptac_covered"] is False              # inf treated as CPTAC-not-usable
