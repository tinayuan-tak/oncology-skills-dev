"""M2 render-equivalence proof: rho(record) == the legacy verdict TOKEN, for EVERY axis and EVERY
verdict it can emit (VERDICT_REPRESENTATION_MIGRATION.md M2 — the blocking gate before the M3
source-swap). This is the structural, S3-free form of the proof: it drives each skill's real
_claim_record hook with a known verdict and asserts render_verdict reproduces it exactly.

  * MEASURED verdict  -> finding.state == verdict, so render is identity (the token survives as a
    field — the strangler-fig invariant that lets M3 re-source decision.json's verdict from the
    record with no hash movement).
  * OPEN-WORLD verdict (data_unavailable) -> finding.state='unknown' (ignorance != negation), and
    render reads the exact token back from provenance.legacy_verdict.

Each skill's run.py is imported under a UNIQUE module name (spec_from_file_location) so the eleven
`run` modules do not collide (the CI per-skill isolation constraint), letting one test span all axes.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS))
from _skills_common.claim_record import render_verdict  # noqa: E402

# axis short -> (skill dir, verdicts the resolver/inline logic can emit — incl. an open-world token
# where the axis has one). Verdicts are the record's finding.state universe per axis.
_AXES = {
    "genomic_alteration": ("genomic-alteration-profile", [
        "multi_class_driver", "confirmed_driver", "recurrent_snv_driver", "lof_dominant_pattern",
        "passenger_pattern", "insufficient", "data_unavailable"]),
    "selectivity": ("tumor-selectivity", [
        "strong_tumor_selective", "modest_tumor_selective", "field_effect_tumor_selective",
        "not_selective", "discordant_across_comparators", "not_informative", "insufficient",
        "data_unavailable"]),
    "safety": ("on-target-safety-liability", [
        "highly_constrained_safety_concern", "human_genetics_safety_concern",
        "normal_tissue_protein_safety_concern", "pan_essential_broad_tox_concern",
        "moderately_constrained_safety", "tolerant_reduced_safety_risk", "insufficient",
        "data_unavailable"]),
    "surface_modality": ("surface-modality-fit", [
        "adc_preferred", "tce_preferred", "both_viable", "adc_preferred_tce_unsafe",
        "surface_viable_density_caveated", "shed_dominant_opposed", "neither_viable",
        "tce_unsafe_normal_liability", "modality_ambiguous", "insufficient", "data_unavailable"]),
    "dependency": ("functional-requirement", [
        "concordant_dependent", "broadly_dependent", "lineage_selective", "selective_dependent",
        "pan_essential_killer", "non_dependent", "discordant", "insufficient_underpowered",
        "insufficient"]),
    "differentiation": ("differentiation-landscape", [
        "strong_cooccurring", "strong_mutually_exclusive", "both_patterns_present",
        "has_cooccurring_driver", "modest_cooccurring", "ns", "insufficient", "data_unavailable"]),
    "tractability_small_molecule": ("tractability-small-molecule", [
        "well_covered", "measured_potent_ligand", "chemically_active", "structurally_ligandable",
        "clinical_precedent_only", "tool_compound_only", "weakly_active", "structurally_intractable",
        "chemically_unhit", "discordant", "insufficient"]),
    "mechanism": ("mechanism-and-pharmacology", [
        "well_characterized", "has_pd_marker", "partial", "sparse", "insufficient", "data_unavailable"]),
    "cis_coherence": ("cis-feature-coherence", [
        "coherent_cis_driver", "coherent_epigenetic_silencing", "cis_uncoupled_no_dependency",
        "dependency_without_cis_dosage", "expressed_cis_coupled_inert", "insufficient_cis_coherence"]),
    "synthetic_lethal_partners": ("synthetic-lethal-partners", [
        "has_experimental_sl_partner", "has_computational_sl_partner", "no_curated_sl_partner",
        "insufficient", "data_unavailable"]),
    "tumor_presence": ("tumor-presence", [
        "strongly_upregulated_in_tumor", "modestly_upregulated_in_tumor", "tumor_sparsely_expressed",
        "strongly_downregulated_in_tumor", "broadly_low_expression", "not_informative",
        "data_unavailable"]),
}


def _load_claim_record(skill_dir: str):
    run_py = SKILLS / skill_dir / "scripts" / "run.py"
    spec = importlib.util.spec_from_file_location(f"_m2_{skill_dir.replace('-', '_')}", run_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "_claim_record")


@pytest.mark.parametrize("axis", sorted(_AXES))
def test_render_equivalence_per_axis(axis):
    skill_dir, verdicts = _AXES[axis]
    cr = _load_claim_record(skill_dir)
    for v in verdicts:
        rec = cr([], fired=[], verdict_pair=(v, None))
        assert rec["axis"] == axis, f"{axis}: record axis mismatch ({rec['axis']})"
        rendered = render_verdict(rec)
        assert rendered == v, (
            f"{axis}: rho(record)={rendered!r} != legacy token {v!r} — render-equivalence BROKEN "
            f"(state={rec['finding']['state']!r}, legacy_verdict={rec['provenance'].get('legacy_verdict')!r}).")


def test_every_verdict_bearing_axis_is_covered():
    # 10 resolver gates + tumor_presence — the full M1 shadow set. A new axis must extend this proof.
    assert len(_AXES) == 11
