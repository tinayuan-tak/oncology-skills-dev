"""Tests for ScholarEval reading from structured facts.yaml (v1.5.0).

Closes the regex-on-prose brittleness in `parse_risk_assessment()` —
when facts.yaml is present, ScholarEval reads structured fields
(`clinical.highest_phase`, `druggability.has_clinical_compound`, etc.)
directly. Score becomes invariant to markdown rendering choices.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from run_scholareval import parse_facts_yaml  # noqa: E402


def _write_facts(tmp_path: Path, overrides: dict) -> Path:
    """Write a minimal valid facts.yaml fixture, with category-level
    overrides merged onto a baseline."""
    base = {
        "gene": "TESTGENE",
        "disease": "nsclc",
        "date": "2026-05-30",
        "risk_categories": {
            cat: {
                "level": "MEDIUM",
                "key_driver": "x",
                "justification": "x",
                "evidence": [],
            }
            for cat in ("biological", "druggability", "translational",
                        "clinical", "safety", "commercial")
        },
        "recommendation": {"level": "CONDITIONAL", "rationale": "x"},
        "mitigations": [
            {"title": "t", "risk_level": "MEDIUM", "strategy": "s"},
        ],
    }
    for cat, fields in overrides.items():
        base["risk_categories"][cat].update(fields)
    path = tmp_path / "TESTGENE_risk_assessment_facts.yaml"
    path.write_text(yaml.safe_dump(base, sort_keys=False))
    return path


# ---------------------------------------------------------------------------
# Structured-field passthrough (the v1.5.0 contract)
# ---------------------------------------------------------------------------

def test_clinical_highest_phase_passes_through(tmp_path: Path) -> None:
    """`clinical.highest_phase` from facts.yaml lands in lit_evidence
    unchanged — no regex scanning."""
    path = _write_facts(tmp_path, {"clinical": {"highest_phase": 2}})
    ev = parse_facts_yaml(path)
    assert ev["clinical_validation"]["highest_phase"] == 2
    # n_trials / indication_specific are derived: phase>0 → 1 trial, indication-specific.
    assert ev["clinical_validation"]["n_trials"] == 1
    assert ev["clinical_validation"]["indication_specific"] is True


def test_clinical_phase_zero_default(tmp_path: Path) -> None:
    """Missing `highest_phase` defaults to 0 (preclinical-only)."""
    path = _write_facts(tmp_path, {})
    ev = parse_facts_yaml(path)
    assert ev["clinical_validation"]["highest_phase"] == 0
    assert ev["clinical_validation"]["n_trials"] == 0
    assert ev["clinical_validation"]["indication_specific"] is False


def test_druggability_booleans_passthrough(tmp_path: Path) -> None:
    """Druggability boolean fields land in lit_evidence as-is."""
    path = _write_facts(tmp_path, {
        "druggability": {
            "has_approved_drug": False,
            "has_clinical_compound": True,
            "has_tool_compound": True,
            "has_structure": True,
            "best_ic50_nm": 62,
        },
    })
    ev = parse_facts_yaml(path)
    drug = ev["druggability"]
    assert drug["has_approved_drug"] is False
    assert drug["has_clinical_compound"] is True
    assert drug["has_tool_compound"] is True
    assert drug["has_structure"] is True
    assert drug["best_ic50_nm"] == 62
    # has_binding_pocket isn't in the structured schema; stays False to
    # avoid inflating druggability score without explicit evidence.
    assert drug["has_binding_pocket"] is False


def test_druggability_defaults_when_absent(tmp_path: Path) -> None:
    """All druggability flags default to False when absent (legacy facts.yaml)."""
    path = _write_facts(tmp_path, {})
    ev = parse_facts_yaml(path)
    drug = ev["druggability"]
    assert drug["has_approved_drug"] is False
    assert drug["has_clinical_compound"] is False
    assert drug["has_tool_compound"] is False
    assert drug["has_structure"] is False
    assert drug["best_ic50_nm"] is None


# ---------------------------------------------------------------------------
# Biological evidence — derived from study_type counts on biological.evidence[]
# ---------------------------------------------------------------------------

def test_animal_models_count_from_study_type(tmp_path: Path) -> None:
    """`n_animal_models` counts unique PMIDs whose study_type indicates
    in-vivo work."""
    path = _write_facts(tmp_path, {
        "biological": {
            "evidence": [
                {"pmid": "11111111", "claim": "x", "study_type": "in vivo"},
                {"pmid": "22222222", "claim": "y", "study_type": "xenograft"},
                # Duplicate PMID — should NOT inflate count.
                {"pmid": "11111111", "claim": "z", "study_type": "in vivo / mechanistic"},
                {"pmid": "33333333", "claim": "w", "study_type": "mechanistic"},  # not in vivo
            ],
        },
    })
    ev = parse_facts_yaml(path)
    # 2 unique PMIDs with in-vivo study_type (11111111, 22222222).
    assert ev["biological_validation"]["n_animal_models"] == 2


def test_crispr_count_from_claim_text(tmp_path: Path) -> None:
    path = _write_facts(tmp_path, {
        "biological": {
            "evidence": [
                {"pmid": "11111111", "claim": "CRISPR knockout in mice", "study_type": "in vivo"},
                {"pmid": "22222222", "claim": "siRNA knockdown in cells", "study_type": "in vitro"},
            ],
        },
    })
    ev = parse_facts_yaml(path)
    assert ev["biological_validation"]["n_crispr_studies"] == 1
    assert ev["biological_validation"]["n_rnai_studies"] == 1


# ---------------------------------------------------------------------------
# Determinism — the central v1.5.0 claim
# ---------------------------------------------------------------------------

def test_same_facts_yields_same_evidence(tmp_path: Path) -> None:
    """Two facts.yaml files with identical structured content → identical
    lit_evidence dicts. (Cosmetic differences like key ordering or
    whitespace would not change the parsed output.)"""
    overrides = {
        "clinical": {"highest_phase": 2},
        "druggability": {
            "has_approved_drug": False,
            "has_clinical_compound": True,
            "has_tool_compound": True,
            "has_structure": True,
            "best_ic50_nm": 62,
        },
        "biological": {
            "evidence": [
                {"pmid": "11111111", "claim": "CRISPR knockout reduced tumor",
                 "study_type": "in vivo"},
            ],
        },
    }
    p1 = _write_facts(tmp_path / "a", _ensure_dir(tmp_path / "a") and overrides)
    p2 = _write_facts(tmp_path / "b", _ensure_dir(tmp_path / "b") and overrides)
    assert parse_facts_yaml(p1) == parse_facts_yaml(p2)


def _ensure_dir(p: Path) -> bool:
    p.mkdir(parents=True, exist_ok=True)
    return True
