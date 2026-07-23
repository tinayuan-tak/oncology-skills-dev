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
    _patch_cptac(monkeypatch, cls="ns", effect=0.0)
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e5}])
    assert r.read_abundance_density_summary("X", "COAD")["hpa_ihc_intensity_class"] == "low"
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 2.0e6}])
    assert r.read_abundance_density_summary("X", "COAD")["hpa_ihc_intensity_class"] == "medium"


def test_breadth_only_anchor_widens_band(monkeypatch):
    # BRCA tissue-of-origin is NOT in HPA's enriched vocab → breadth-only medium anchor, factor *1.6.
    _patch_hpa(monkeypatch, breadth="broad_normal_expression", specific=[])
    _patch_cptac(monkeypatch, cls="ns", effect=0.5, cohort="BRCA")
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


def test_not_detected_maps_very_low(monkeypatch):
    _patch_hpa(monkeypatch, breadth="not_detected_in_normal", specific=[])
    _patch_cptac(monkeypatch, cls="ns", effect=0.0)
    d = r.read_abundance_density_summary("X", "COAD")
    assert d["hpa_ihc_intensity_class"] == "not_detected"
    # center 3e2, shift 1 → 300/cell → very_low? no: 100 <= 300 < 1000 → low
    assert d["surface_density_class"] == "low"
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


def test_committed_corpus_target_reads_grade_ab_live(monkeypatch):
    # integration: a real corpus target reads from the governed ladder, not the estimate.
    monkeypatch.undo()  # drop the autouse _no_ladder patch → use the real committed corpus
    d = r.read_abundance_density_summary("MET", "COADREAD")
    assert d["_density_source"] == "governed_ladder"
    assert d["density_evidence_level"] in ("A", "A-", "B", "B-")
    assert d["absolute_value_best"] is not None


# --- SURFACE-ACCESSIBILITY SOFT GATE (2026-07-23 v2): labels admissibility, NEVER suppresses -------
# Design principle (multiagent-verified): the surfaceome classifier is unreliable BOTH ways, so it must
# not hard-veto. Separate TARGET VISIBILITY (whole-cell estimate always retained) from SURFACE-DENSITY
# ADMISSIBILITY {admissible|unsupported|provisional}. Absence is NEVER negative evidence.
def _patch_surfaceome(monkeypatch, *, surfy, hpa_pm, data_note="", family="Receptors"):
    import methods.surfaceome_family_fusion as _surf
    payload = {"is_surface_protein": bool(surfy or hpa_pm), "surface_protein_family": family,
               "surfaceome_confidence_score": 1.0,
               "source_surfy_positive": surfy, "source_hpa_plasma_membrane": hpa_pm}
    if data_note:
        payload["_data_note"] = data_note
    monkeypatch.setattr(_surf, "read_target_summary", lambda target, indication=None: dict(payload))


def test_unsupported_retains_estimate_but_flags_not_surface(monkeypatch):
    # IN table, NO positive surface evidence (SURFY-neg AND HPA-neg) -> unsupported. The whole-cell
    # estimate is RETAINED (visibility), but the surface class is relabeled + viability flags False.
    _patch_surfaceome(monkeypatch, surfy=False, hpa_pm=False, family="Not_surface")
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


def test_admissible_when_positive_surface_evidence(monkeypatch):
    # SURFY-positive (even with HPA negative — the CD19/BCMA case) -> admissible, normal surface call
    _patch_surfaceome(monkeypatch, surfy=True, hpa_pm=False)
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e7}])
    _patch_cptac(monkeypatch, cls="modest_up", effect=1.05)
    d = r.read_abundance_density_summary("CD19", "MM")
    assert d["surface_density_admissibility"] == "admissible"
    assert d["surface_density_class"] == "high"
    assert d["is_tce_viable"] is True


def test_coverage_gap_is_provisional_not_unsupported(monkeypatch):
    # absent from the table (_data_note) -> provisional (absence is NOT negative evidence). Estimate
    # retained + surface call kept (weaker confidence), NOT relabeled unsupported.
    _patch_surfaceome(monkeypatch, surfy=False, hpa_pm=False,
                      data_note="target_not_in_surfaceome_family")
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e7}])
    _patch_cptac(monkeypatch, cls="modest_up", effect=1.05)
    d = r.read_abundance_density_summary("NOVELSURF", "COADREAD")
    assert d["surface_density_admissibility"] == "provisional"
    assert d["surface_density_class"] == "high"      # kept, not relabeled
    assert d["estimated_copies_per_cell_median"] is not None


def test_ladder_measurement_ignores_accessibility_gate(monkeypatch):
    # a ladder measurement is direct surface evidence -- the soft gate never touches it.
    monkeypatch.undo()
    _patch_surfaceome(monkeypatch, surfy=False, hpa_pm=False, family="Not_surface")  # adversarial
    d = r.read_abundance_density_summary("MET", "COADREAD")
    assert d["_density_source"] == "governed_ladder"
    assert d["absolute_value_best"] is not None
    assert "surface_density_admissibility" not in d   # ladder path has no soft-gate label


def test_nonfinite_cptac_log2fc_does_not_produce_inf(monkeypatch):
    # a degenerate CPTAC effect (inf: tumor-detected/normal-absent) must NOT yield an inf estimate;
    # it falls back to anchor-only (shift=1). Regression for the STEAP1 effect=inf bug.
    import math
    _patch_surfaceome(monkeypatch, surfy=True, hpa_pm=True)
    _patch_hpa(monkeypatch, breadth="broad_normal_expression", specific=[])   # medium anchor, center 3e4
    _patch_cptac(monkeypatch, cls="ns", effect=float("inf"))
    d = r.read_abundance_density_summary("STEAP1", "PRAD")
    assert d["estimated_copies_per_cell_median"] is not None
    assert math.isfinite(d["estimated_copies_per_cell_median"])
    assert d["_cptac_covered"] is False              # inf treated as CPTAC-not-usable
