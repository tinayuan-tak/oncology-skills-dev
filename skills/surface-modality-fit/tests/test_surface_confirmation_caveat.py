"""Tests for the VERDICT-INERT surface enrichment (v1.8.0): surface_confirmation_caveat + shed_caveat.

surface_confirmation_caveat is the surface analog of tractability-small-molecule's directness_caveat. It
names the surfaceome-family / RNA / predicted-topology annotation-INFLATION risk on a POSITIVE fit_class
that lacks confirmed cell-surface protein — because fit_class is composed from family+topology annotation
ONLY (it does NOT consume CSPA/HPA-IF measured protein, density, or measured internalization). shed_caveat
names a soluble-antigen-sink on a surface-abundant/positive call whose ectodomain is shed.

Pins the load-bearing properties:
  (1) the SHARP over-call tier (family_topology_annotation_unconfirmed) fires for a positive fit + NO
      confirmed protein + NO clinical precedent (the LGR5/GPCR-family pattern);
  (2) the MILDER tier (clinically_precedented_cspa_unconfirmed) fires when a clinical precedent rescues a
      CSPA-unconfirmed call (DLL3/CEACAM5-class validated antigens — NOT an over-call);
  (3) a confirmed_high / corroborated_surface positive is NEVER caveated (ERBB2/MSLN byte-stable);
  (4) a negative / gap fit_class (neither_viable, data_unavailable) is NEVER caveated (WT1 byte-stable);
  (5) the endocytosis-unmeasured ADC sub-note only sets on an ADC-favorable fit with endo unmeasured;
  (6) shed_caveat fires for a shed + surface-abundant target and is None on membrane-retained.
All pure (no S3).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))


def _load_run():
    run_path = SKILL_SCRIPTS / "run.py"
    spec = importlib.util.spec_from_file_location("smf_run_confcaveat", run_path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_M = _load_run()


# ── (1) the SHARP over-call tier — LGR5/GPCR-family pattern ───────────────────────────────────────
def test_annotation_unconfirmed_fires_on_positive_fit_without_protein_or_precedent():
    hl = {"fit_class": "TCE_preferred", "family_class": "gpcr", "topology_class": "multi_pass",
          "surface_confirmation_class": "not_surface", "surface_multimodal_support": "single_modality_negative",
          "endocytosis_confidence": "unmeasured", "cd_established_io_precedent": False}
    c = _M._surface_confirmation_caveat(hl)
    assert c is not None
    assert c["reason"] == "family_topology_annotation_unconfirmed"
    assert c["surface_confirmed"] is False
    assert c["clinical_precedent"] is False
    # TCE_preferred is NOT an ADC-favorable class → no endocytosis-ADC sub-note
    assert c["endocytosis_unmeasured_for_adc"] is False
    assert "UNCONFIRMED" in c["detail"] and "family" in c["detail"].lower()


def test_annotation_unconfirmed_adc_favorable_sets_endocytosis_note():
    """A both_viable/ADC_preferred positive that is unconfirmed AND has endocytosis unmeasured sets the
    ADC internalization sub-note (payload delivery unverified)."""
    hl = {"fit_class": "both_viable", "family_class": "other_surface", "topology_class": "single_pass_type_1",
          "surface_confirmation_class": "not_surface", "surface_multimodal_support": "discordant",
          "endocytosis_confidence": "unmeasured", "cd_established_io_precedent": False}
    c = _M._surface_confirmation_caveat(hl)
    assert c["reason"] == "family_topology_annotation_unconfirmed"
    assert c["endocytosis_unmeasured_for_adc"] is True
    assert "internalization is UNMEASURED" in c["detail"]


# ── (2) the MILDER tier — clinical precedent rescues a CSPA false-negative ────────────────────────
def test_clinically_precedented_cspa_unconfirmed_when_precedent_present():
    """DLL3-class: not_surface CSPA but endocytosis_confidence=clinically_internalizing (curated ADC
    precedent) → the milder, NON-over-call tier."""
    hl = {"fit_class": "both_viable", "family_class": "other_surface", "topology_class": "single_pass_type_1",
          "surface_confirmation_class": "not_surface", "surface_multimodal_support": "discordant",
          "endocytosis_confidence": "clinically_internalizing", "cd_established_io_precedent": False}
    c = _M._surface_confirmation_caveat(hl)
    assert c["reason"] == "clinically_precedented_cspa_unconfirmed"
    assert c["clinical_precedent"] is True
    # clinical precedent means internalization is NOT unmeasured for the ADC note
    assert c["endocytosis_unmeasured_for_adc"] is False


def test_cd_io_precedent_also_counts_as_clinical_precedent():
    hl = {"fit_class": "TCE_preferred", "family_class": "cd_molecule", "topology_class": "single_pass_type_1",
          "surface_confirmation_class": "not_surface", "surface_multimodal_support": "discordant",
          "endocytosis_confidence": "unmeasured", "cd_established_io_precedent": True}
    c = _M._surface_confirmation_caveat(hl)
    assert c["reason"] == "clinically_precedented_cspa_unconfirmed"


# ── (3) a CONFIRMED positive is NEVER caveated (byte-stable on ERBB2/MSLN) ────────────────────────
def test_confirmed_high_surface_never_caveated():
    hl = {"fit_class": "both_viable", "surface_confirmation_class": "confirmed_high",
          "surface_multimodal_support": "corroborated_surface", "endocytosis_confidence": "clinically_internalizing"}
    assert _M._surface_confirmation_caveat(hl) is None


def test_corroborated_multimodal_never_caveated_even_without_cspa_class():
    hl = {"fit_class": "ADC_preferred", "surface_confirmation_class": None,
          "surface_multimodal_support": "corroborated_surface", "endocytosis_confidence": "unmeasured"}
    assert _M._surface_confirmation_caveat(hl) is None


# ── (4) negative / gap fit_class is NEVER caveated (byte-stable on WT1 neither_viable) ─────────────
def test_negative_and_gap_fit_never_caveated():
    for fc in ("neither_viable", "data_unavailable", "insufficient", "modality_ambiguous",
               "isoform_dependent_undefined", None):
        hl = {"fit_class": fc, "surface_confirmation_class": "not_surface",
              "endocytosis_confidence": "unmeasured", "cd_established_io_precedent": False}
        assert _M._surface_confirmation_caveat(hl) is None, f"caveat fired on non-positive fit_class {fc!r}"


# ── (6) shed_caveat ───────────────────────────────────────────────────────────────────────────────
def test_shed_caveat_fires_on_clinically_shed_abundant():
    hl = {"fit_class": "both_viable", "shed_liability_class": "clinically_shed",
          "measured_shed_class": "not_on_secreted_panel", "shed_serum_marker": "CEA",
          "surface_density_class": "high"}
    c = _M._shed_caveat(hl)
    assert c is not None
    assert c["reason"] == "clinically_shed_soluble_sink"
    assert c["serum_marker"] == "CEA"
    assert "soluble" in c["detail"].lower() and "sink" in c["detail"].lower()


def test_shed_caveat_fires_on_measured_media_shed_high():
    hl = {"fit_class": "both_viable", "shed_liability_class": "not_shed_membrane_retained",
          "measured_shed_class": "media_shed_high", "surface_density_class": "high"}
    c = _M._shed_caveat(hl)
    assert c is not None and c["reason"] == "clinically_shed_soluble_sink"


def test_shed_caveat_secretome_proxy_is_milder():
    hl = {"fit_class": "both_viable", "shed_liability_class": "secretome_proxy_shed",
          "measured_shed_class": "not_on_secreted_panel", "surface_density_class": "moderate"}
    c = _M._shed_caveat(hl)
    assert c is not None and c["reason"] == "secretome_proxy_possible_sink"


def test_shed_caveat_none_on_membrane_retained():
    hl = {"fit_class": "both_viable", "shed_liability_class": "not_shed_membrane_retained",
          "measured_shed_class": "not_on_secreted_panel", "surface_density_class": "low"}
    assert _M._shed_caveat(hl) is None


def test_shed_caveat_none_when_not_abundant_and_not_positive():
    """A shed antigen that is neither positive-fit nor surface-abundant → no sink caveat (nothing to sink)."""
    hl = {"fit_class": "neither_viable", "shed_liability_class": "clinically_shed",
          "measured_shed_class": "not_on_secreted_panel", "surface_density_class": "very_low"}
    assert _M._shed_caveat(hl) is None


# ── (5) VERDICT-INERTNESS: the caveats are headline-only, never resolver-consumed ─────────────────
def test_caveats_are_not_resolver_rule_ids():
    """The new fields are headline keys, not fired rule_ids — the surface_modality resolver keys only on
    fit_class + the safety/density/shed rungs, so a headline caveat cannot move the verdict."""
    hl = {"fit_class": "TCE_preferred", "family_class": "gpcr", "topology_class": "multi_pass",
          "surface_confirmation_class": "not_surface", "surface_multimodal_support": "single_modality_negative",
          "endocytosis_confidence": "unmeasured", "cd_established_io_precedent": False,
          "shed_liability_class": "clinically_shed", "surface_density_class": "high"}
    scc = _M._surface_confirmation_caveat(hl)
    shed = _M._shed_caveat(hl)
    # both are dicts with a `reason` string — NOT a rule_id token the resolver's when_(all_)fired keys on
    assert isinstance(scc, dict) and isinstance(scc.get("reason"), str)
    assert isinstance(shed, dict) and isinstance(shed.get("reason"), str)
