"""Tests for v1.7.0 primary_evidence per-category pointer."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from integrated_report.risk_assessment_renderer import load_facts  # noqa: E402
from integrated_report.context import _load_primary_evidence  # noqa: E402


def _facts(extras: dict | None = None) -> dict:
    """Minimal valid facts.yaml with optional category overrides."""
    base = {
        "gene": "G",
        "disease": "nsclc",
        "date": "2026-05-31",
        "risk_categories": {
            cat: {
                "level": "MEDIUM",
                "key_driver": "x",
                "justification": "x",
                "evidence": [
                    {"pmid": "11111111", "claim": "c1", "study_type": "in vivo"},
                    {"pmid": "22222222", "claim": "c2", "study_type": "in vitro"},
                ],
            }
            for cat in ("biological", "druggability", "translational",
                        "clinical", "safety", "commercial")
        },
        "recommendation": {"level": "CONDITIONAL", "rationale": "x"},
        "mitigations": [{"title": "t", "risk_level": "MEDIUM", "strategy": "s"}],
    }
    for cat, fields in (extras or {}).items():
        base["risk_categories"][cat].update(fields)
    return base


def _write(tmp_path: Path, facts: dict) -> Path:
    p = tmp_path / "facts.yaml"
    p.write_text(yaml.safe_dump(facts, sort_keys=False))
    return p


# ---------------------------------------------------------------------------
# Validator: primary_evidence sub-schema
# ---------------------------------------------------------------------------

def test_primary_evidence_pointer_validates(tmp_path: Path) -> None:
    """Valid pointer (PMID exists in evidence[]) parses cleanly."""
    p = _write(tmp_path, _facts({
        "biological": {
            "primary_evidence": {"pmid": "11111111",
                                 "why_primary": "Sole in-vivo PoC"},
        },
    }))
    facts = load_facts(p)
    pe = facts.risk_categories["biological"]["primary_evidence"]
    assert pe["pmid"] == "11111111"
    assert pe["why_primary"] == "Sole in-vivo PoC"


def test_primary_evidence_dangling_pmid_rejected(tmp_path: Path) -> None:
    """primary_evidence.pmid must reference an existing evidence[] entry."""
    p = _write(tmp_path, _facts({
        "biological": {
            "primary_evidence": {"pmid": "99999999",
                                 "why_primary": "made up"},
        },
    }))
    with pytest.raises(ValueError, match="primary_evidence.pmid=.99999999."):
        load_facts(p)


def test_primary_evidence_missing_why_primary_rejected(tmp_path: Path) -> None:
    p = _write(tmp_path, _facts({
        "biological": {
            "primary_evidence": {"pmid": "11111111"},
        },
    }))
    with pytest.raises(ValueError, match="why_primary"):
        load_facts(p)


def test_primary_evidence_empty_why_primary_rejected(tmp_path: Path) -> None:
    p = _write(tmp_path, _facts({
        "biological": {
            "primary_evidence": {"pmid": "11111111", "why_primary": "   "},
        },
    }))
    with pytest.raises(ValueError, match="why_primary"):
        load_facts(p)


def test_primary_evidence_unrecognized_subkey_rejected(tmp_path: Path) -> None:
    p = _write(tmp_path, _facts({
        "biological": {
            "primary_evidence": {
                "pmid": "11111111", "why_primary": "x", "extra": "?",
            },
        },
    }))
    with pytest.raises(ValueError, match="primary_evidence.*extra"):
        load_facts(p)


def test_primary_evidence_optional(tmp_path: Path) -> None:
    """Categories without primary_evidence still validate."""
    p = _write(tmp_path, _facts({}))
    facts = load_facts(p)
    for cat in ("biological", "druggability", "translational",
                "clinical", "safety", "commercial"):
        assert "primary_evidence" not in facts.risk_categories[cat]


# ---------------------------------------------------------------------------
# Step 4 context loader
# ---------------------------------------------------------------------------

def test_load_primary_evidence_returns_title_cased_dict(tmp_path: Path) -> None:
    """_load_primary_evidence keys by title-case category name to match
    Step 4's RiskCategory.name convention."""
    p = _write(tmp_path, _facts({
        "biological": {
            "primary_evidence": {"pmid": "11111111", "why_primary": "x"},
        },
        "druggability": {
            "primary_evidence": {"pmid": "22222222", "why_primary": "y"},
        },
    }))
    out = _load_primary_evidence(p)
    assert "Biological" in out
    assert "Druggability" in out
    assert out["Biological"]["pmid"] == "11111111"


def test_load_primary_evidence_missing_file_returns_empty(tmp_path: Path) -> None:
    out = _load_primary_evidence(tmp_path / "does_not_exist.yaml")
    assert out == {}


def test_load_primary_evidence_none_returns_empty() -> None:
    assert _load_primary_evidence(None) == {}
