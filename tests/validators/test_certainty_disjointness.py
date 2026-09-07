"""Guard for CERTAINTY_MODEL §3 required-validator #1 (R3): certainty corroboration ⟂ verdict-precedence.

(1) The committed vocabularies/certainty_corroboration.yaml must be clean (every registered corroboration
    card is verdict-disjoint for its gate).
(2) The validator must actually CATCH a violation — injecting a corroboration card that DOES drive the
    gate's verdict (dependency's CRISPR↔RNAi concordance, which resolves concordant_dependent) must error.
    This is the anti-regression pin: a green validator that can't fail is worthless.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VALIDATOR = REPO / "validators" / "validate_certainty_disjointness.py"


def _mod():
    spec = importlib.util.spec_from_file_location("_ccd", VALIDATOR)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_committed_manifest_is_disjoint():
    errors = _mod().validate(REPO)
    assert errors == [], "certainty corroboration is NOT verdict-disjoint:\n" + "\n".join(errors)


def test_validator_catches_a_verdict_driving_corroboration(tmp_path, monkeypatch):
    """Inject a manifest where dependency corroboration = crispr-rnai-dependency-concordance (which DOES
    resolve the dependency verdict). The validator MUST flag the disjointness violation."""
    m = _mod()
    # Build a fake contracts root that reuses the real resolvers/ + interpretation-rules/ but a poisoned
    # manifest. Symlink the real dirs so the validator sees real verdict-precedence.
    (tmp_path / "vocabularies").mkdir()
    (tmp_path / "resolvers").symlink_to(REPO / "resolvers")
    (tmp_path / "interpretation-rules").symlink_to(REPO / "interpretation-rules")
    (tmp_path / "vocabularies" / "certainty_corroboration.yaml").write_text(
        "enum_id: certainty_corroboration\nversion: 1.0.0\n"
        "corroboration_by_gate:\n  dependency:\n    - crispr-rnai-dependency-concordance\n"
    )
    errors = m.validate(tmp_path)
    assert any("DISJOINTNESS VIOLATION" in e and "dependency" in e for e in errors), (
        f"validator failed to catch a verdict-driving corroboration card; errors={errors}"
    )


def test_unknown_gate_is_flagged(tmp_path):
    m = _mod()
    (tmp_path / "vocabularies").mkdir()
    (tmp_path / "resolvers").mkdir()
    (tmp_path / "interpretation-rules").mkdir()
    (tmp_path / "vocabularies" / "certainty_corroboration.yaml").write_text(
        "corroboration_by_gate:\n  no_such_gate:\n    - some-card\n"
    )
    errors = m.validate(tmp_path)
    assert any("no resolver" in e for e in errors)
