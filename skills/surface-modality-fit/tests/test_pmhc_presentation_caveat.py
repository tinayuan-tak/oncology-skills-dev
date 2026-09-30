"""Tests for the VERDICT-INERT pmhc_presentation_caveat (v1.10.0, CASE-012).

The pMHC-TCE route (`pmhc_tce_supported`) is the framework's ONE positive for a folded-surface-dead
intracellular oncoprotein. Its only normal-tissue safety clamp in the resolver is the immunopeptidome-
BREADTH veto (`pmhc-broadly-presented-normal-tce-opposing`), which fires only at `broadly_presented_normal`
(>= atlas Q3 normal tissues). That leaves the MIDDLE band — `intermediate_presentation` (Q1–Q3) —
uncaveated: NOX1/CRC reads a clean `pmhc_tce_supported` despite its epitope being presented on 8 normal
tissues (colon + small intestine + bone marrow). This caveat NAMES that liability. It is scored on the
modality-appropriate axis (presentation breadth, NOT RNA/protein expression) and does NOT foreclose the
route — restricted-presentation pMHC targets (NY-ESO-1/MAGE-A4) carry no caveat, and it never moves the
verdict (owned by the resolver).

Pins the load-bearing properties:
  (1) fires for pmhc_tce_supported + intermediate_presentation, naming the sensitive normal tissues;
  (2) None on restricted_presentation (the clean pMHC target — NY-ESO-1/MAGE-A4 byte-stable);
  (3) None on broadly_presented_normal (already withdrawn to tce_unsafe_normal_liability by the resolver);
  (4) None on not_observed (weak-negative / tumor-restricted candidate);
  (5) None when the verdict is NOT pmhc_tce_supported (a surface-viable call with an additive pMHC signal);
  (6) VERDICT-INERT — it is a pure function of the headline, never a resolver input.
All pure (no S3).
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

_M = load_run_py(Path(__file__).resolve().parent.parent, "smf_run_pmhccaveat")


def _hl(**kw):
    base = {
        "surface_modality_verdict": "pmhc_tce_supported",
        "pmhc_presentation_class": "intermediate_presentation",
        "pmhc_n_normal_tissues": 8,
        "pmhc_normal_tissues_presented": "Bone marrow;Cerebellum;Colon;Lung;Small intestine;Spleen;Testis;Thymus",
    }
    base.update(kw)
    return base


# ── (1) fires on the intermediate band + names the sensitive normal tissues ───────────────────────
def test_fires_on_intermediate_presentation_pmhc_supported():
    c = _M._pmhc_presentation_caveat(_hl())
    assert c is not None
    assert c["reason"] == "pmhc_intermediate_normal_presentation"
    assert c["pmhc_presentation_class"] == "intermediate_presentation"
    assert c["n_normal_tissues"] == 8
    # the GI + hematopoietic tissues are surfaced as the named concern (NOX1/CRC pattern)
    assert "Colon" in c["sensitive_normal_tissues"]
    assert "Small intestine" in c["sensitive_normal_tissues"]
    assert "Bone marrow" in c["sensitive_normal_tissues"]
    # Cerebellum/Testis are not in the sensitive list → not named
    assert "Cerebellum" not in c["sensitive_normal_tissues"]
    assert "intermediate_presentation" in c["detail"]
    assert "CAVEAT not a veto" in c["detail"]


# ── (2) None on the CLEAN restricted pMHC target (NY-ESO-1/MAGE-A4) ───────────────────────────────
def test_none_on_restricted_presentation():
    assert (
        _M._pmhc_presentation_caveat(_hl(pmhc_presentation_class="restricted_presentation", pmhc_n_normal_tissues=1))
        is None
    )


# ── (3) None on broadly_presented_normal (the resolver already withdrew the positive) ─────────────
def test_none_on_broadly_presented_normal():
    assert (
        _M._pmhc_presentation_caveat(_hl(pmhc_presentation_class="broadly_presented_normal", pmhc_n_normal_tissues=22))
        is None
    )


# ── (4) None on not_observed (weak-negative candidate) ────────────────────────────────────────────
def test_none_on_not_observed():
    assert _M._pmhc_presentation_caveat(_hl(pmhc_presentation_class="not_observed", pmhc_n_normal_tissues=0)) is None


# ── (5) None when the verdict is NOT a pMHC route (additive pMHC signal on a surface-viable call) ─
def test_none_when_verdict_not_pmhc_route():
    assert _M._pmhc_presentation_caveat(_hl(surface_modality_verdict="both_viable")) is None
    assert _M._pmhc_presentation_caveat(_hl(surface_modality_verdict="tce_unsafe_normal_liability")) is None


# ── (5b, #2113) ALSO fires for the caveat verdict — an intermediate read now resolves to the caveat
#     token, and the rich named-tissue detail must not be lost when the promotion demotes. ─────────────
def test_fires_on_the_presentation_unconfirmed_caveat_verdict():
    c = _M._pmhc_presentation_caveat(_hl(surface_modality_verdict="pmhc_tce_supported_presentation_unconfirmed"))
    assert c is not None, "the intermediate-presentation detail must survive the #2113 demotion to the caveat verdict"
    assert c["reason"] == "pmhc_intermediate_normal_presentation"
    assert "Colon" in c["sensitive_normal_tissues"] and "Bone marrow" in c["sensitive_normal_tissues"]


# ── (6) empty/absent tissue string still yields a caveat (fires on the class), just no named tissues ─
def test_fires_without_named_tissues():
    c = _M._pmhc_presentation_caveat(_hl(pmhc_normal_tissues_presented=None))
    assert c is not None
    assert c["sensitive_normal_tissues"] == []
    assert c["normal_tissues_presented"] == []
