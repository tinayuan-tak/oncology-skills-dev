"""Tests for the surface orthogonality scorer (enrichment E7, 2026-08-07).

Pins the load-bearing design properties:
  (1) PRESENCE-CLUSTER COLLAPSE — the 5 correlated presence cards count as ONE dimension,
      not 5 (the whole reason this isn't a fired-rule count);
  (2) COVERAGE vs SUPPORT are separate — an abstaining (data_unavailable) dimension is a
      coverage gap, NEVER an opposing vote (honest-coverage doctrine);
  (3) SHED INVERSION — not_shed is SUPPORTIVE, clinically_shed/media_shed_high is OPPOSING;
  (4) orthogonality_class bands key on breadth of SUPPORT gated by coverage;
  (5) VERDICT-INERT — the facet is emitted in the headline and CANNOT move the
      surface_modality verdict (the resolver keys only on fit_class rungs).
All pure (synthetic card dicts); no S3.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))
import orthogonality as orth  # noqa: E402

import importlib.util  # noqa: E402


def _load_run():
    """Load THIS skill's run.py under a UNIQUE module name. A bare `import run` binds
    sys.modules['run'] to whichever skill's run.py loaded FIRST in the process — so when
    surface-modality-fit's tests share a pytest session with another skill's (the
    `import run` collision documented in skills-validate.yml), `import run as smf` would
    return the WRONG skill's module. spec_from_file_location sidesteps the shared name."""
    run_path = SKILL_SCRIPTS / "run.py"
    spec = importlib.util.spec_from_file_location("smf_run_orth", run_path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _card(cid, **summary):
    return {"card_id": cid, "summary": dict(summary)}


# ---- (1) presence-cluster collapse ---------------------------------------

def test_presence_cluster_collapses_to_one_dimension():
    """FIVE presence cards all supportive → presence contributes exactly ONE supportive
    dimension, not five. This is the core anti-double-count guarantee."""
    cards = [
        _card("protein-surface-evidence", surface_confirmation_class="confirmed_high"),
        _card("surface-topology-and-ptm", topology_class="single_pass_type_1", ecd_engineerability_class="large_ecd"),
        _card("surface-abundance-density", surface_density_class="high"),
        _card("surfaceome-family-classification", family_class="growth_factor_receptor"),
        _card("rna-protein-concordance-tumor", rna_as_biomarker="adequate_proxy"),
    ]
    out = orth.score_orthogonality(cards)
    # only D1 is covered+supportive; the other 4 dims abstain (no cards)
    assert out["dimensions"]["presence_accessibility"] == "supportive"
    assert out["n_dimensions_supportive"] == 1
    assert out["n_dimensions_covered"] == 1
    assert out["orthogonality_class"] == "single_axis"


# ---- (2) coverage vs support separation (honest coverage) ----------------

def test_abstain_is_coverage_gap_not_opposing():
    """A dimension with no data abstains — it must NOT count as opposing, and must lower
    coverage, not support."""
    cards = [_card("pmhc-presentation", pmhc_presentation_class="data_unavailable")]
    out = orth.score_orthogonality(cards)
    assert out["dimensions"]["pmhc_presentation"] == "abstain"
    assert out["n_dimensions_opposing"] == 0
    assert out["n_dimensions_covered"] == 0
    assert out["orthogonality_class"] == "insufficient_coverage"


def test_no_cards_at_all_is_insufficient_coverage():
    out = orth.score_orthogonality([])
    assert out["n_dimensions_covered"] == 0
    assert out["n_dimensions_supportive"] == 0
    assert out["orthogonality_class"] == "insufficient_coverage"


# ---- (3) shed inversion ---------------------------------------------------

def test_shed_not_shed_is_supportive():
    cards = [_card("shed-ectodomain-liability", shed_liability_class="not_shed_membrane_retained")]
    out = orth.score_orthogonality(cards)
    assert out["dimensions"]["shed_liability"] == "supportive"


def test_shed_clinically_shed_is_opposing():
    cards = [_card("shed-ectodomain-liability", shed_liability_class="clinically_shed")]
    out = orth.score_orthogonality(cards)
    assert out["dimensions"]["shed_liability"] == "opposing"
    assert out["n_dimensions_opposing"] == 1
    assert out["n_dimensions_supportive"] == 0


def test_shed_measured_high_is_opposing_even_if_annotation_absent():
    cards = [_card("shed-ectodomain-liability", shed_liability_class="indeterminate",
                   measured_shed_class="media_shed_high")]
    out = orth.score_orthogonality(cards)
    assert out["dimensions"]["shed_liability"] == "opposing"


# ---- (4) class bands ------------------------------------------------------

def test_four_supportive_dimensions_is_broadly_corroborated():
    cards = [
        _card("protein-surface-evidence", surface_confirmation_class="confirmed_high"),  # D1
        _card("normal-tissue-liability", normal_tissue_breadth_class="restricted_normal_expression",
              essential_tissue_flag="absent"),                                                    # D2
        _card("shed-ectodomain-liability", shed_liability_class="not_shed_membrane_retained"),    # D3
        _card("tumor-scrna-celltype-expression", tce_homogeneity_class="homogeneous"),            # D4
        _card("pmhc-presentation", pmhc_presentation_class="broadly_presented_normal"),           # D5 opposing
    ]
    out = orth.score_orthogonality(cards)
    assert out["n_dimensions_supportive"] == 4
    assert out["n_dimensions_opposing"] == 1
    assert out["n_dimensions_covered"] == 5
    assert out["orthogonality_class"] == "broadly_corroborated"


def test_covered_but_unsupportive_is_uncorroborated_not_insufficient():
    """Dims are COVERED but none supportive → uncorroborated (distinct from the
    no-coverage insufficient_coverage state)."""
    cards = [
        _card("shed-ectodomain-liability", shed_liability_class="clinically_shed"),        # opposing
        _card("pmhc-presentation", pmhc_presentation_class="broadly_presented_normal"),    # opposing
    ]
    out = orth.score_orthogonality(cards)
    assert out["n_dimensions_covered"] == 2
    assert out["n_dimensions_supportive"] == 0
    assert out["orthogonality_class"] == "uncorroborated"


# ---- (5) verdict-inertness ------------------------------------------------

def test_orthogonality_is_verdict_inert():
    """The facet is emitted in the headline; it must carry NO verdict-bearing key and the
    surface_modality resolver must never read the headline. Mirrors the biomarker-facet
    verdict-inert contract (no overall_recommendation / nominate)."""
    cards = [_card("protein-surface-evidence", surface_confirmation_class="confirmed_high")]
    out = orth.score_orthogonality(cards)
    for forbidden in ("surface_modality_verdict", "verdict", "fit_class",
                      "overall_recommendation", "nominate", "driving_rule_id"):
        assert forbidden not in out, f"orthogonality facet must not carry {forbidden}"
    assert "_doctrine" in out and "VERDICT-INERT" in out["_doctrine"]


def test_headline_orthogonality_does_not_change_verdict():
    """End-to-end: _headline attaches orthogonality, but the verdict comes from _verdict
    (resolver on fit_class). Adding the facet leaves the two spine keys untouched.
    _headline reads every card in smf.CARDS via get_card_field (which raises on an absent
    card_id), so the fixture stubs ALL of them — only three carry meaningful values."""
    smf = _load_run()
    meaningful = {
        "adc-tce-modality-fit": {"fit_class": "ADC_preferred"},
        "protein-surface-evidence": {"surface_confirmation_class": "confirmed_high"},
        "shed-ectodomain-liability": {"shed_liability_class": "clinically_shed"},
    }
    cards = [_card(cid, **meaningful.get(cid, {})) for cid in smf.CARDS]
    verdict_pair = smf._verdict([{"rule_id": "adc-preferred-supportive"}])
    hl = smf._headline(cards, [], verdict_pair)
    assert "orthogonality" in hl
    # the spine keys are exactly what _verdict produced — the facet changed neither
    assert hl["surface_modality_verdict"] == verdict_pair[0]
    assert hl["driving_rule_id"] == verdict_pair[1]
    # and the facet correctly saw D1 supportive + D3 opposing
    assert hl["orthogonality"]["dimensions"]["presence_accessibility"] == "supportive"
    assert hl["orthogonality"]["dimensions"]["shed_liability"] == "opposing"
