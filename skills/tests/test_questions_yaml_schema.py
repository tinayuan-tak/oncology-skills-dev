"""Skills-side guard for the question registries (item 8): every skills/<skill>/questions.yaml must
validate against target-contracts/schemas/questions.schema.json AND its non-empty measurement_types must
resolve to a real card contract's measurement_type. Mirrors target-contracts/validators/validate_questions.py
(which guards the contracts CI); this gives the SKILLS suite the same coverage against its own artifacts.

Fail-soft on infra: if the contracts schema / cards dir is unavailable (isolated CI), the affected layer
is skipped — the referential structure of questions.yaml is still exercised by the evidence_graph tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).resolve().parents[1]
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.scope import DEFAULT_CONTRACTS_REPO  # noqa: E402

_CONTRACTS = Path(DEFAULT_CONTRACTS_REPO)
_SCHEMA_PATH = _CONTRACTS / "schemas" / "questions.schema.json"
_CARDS_DIR = _CONTRACTS / "cards"

_QUESTIONS = sorted(SKILLS_DIR.glob("*/questions.yaml"))


def _valid_measurement_types() -> set:
    mts = set()
    for f in _CARDS_DIR.glob("*.card.yaml"):
        try:
            y = yaml.safe_load(f.read_text()) or {}
        except yaml.YAMLError:
            continue
        if y.get("measurement_type"):
            mts.add(y["measurement_type"])
    return mts


def test_registries_discovered():
    assert len(_QUESTIONS) >= 14, [p.parent.name for p in _QUESTIONS]


@pytest.mark.skipif(not _SCHEMA_PATH.exists(), reason="contracts questions.schema.json not available")
@pytest.mark.parametrize("qpath", _QUESTIONS, ids=lambda p: p.parent.name)
def test_questions_yaml_matches_schema(qpath):
    from jsonschema import Draft202012Validator

    schema = json.loads(_SCHEMA_PATH.read_text())
    doc = yaml.safe_load(qpath.read_text()) or {}
    errs = [
        f"[{'.'.join(str(x) for x in e.absolute_path) or '<root>'}]: {e.message}"
        for e in Draft202012Validator(schema).iter_errors(doc)
    ]
    assert not errs, (qpath.parent.name, errs)


@pytest.mark.skipif(not _CARDS_DIR.exists(), reason="contracts cards/ not available")
@pytest.mark.parametrize("qpath", _QUESTIONS, ids=lambda p: p.parent.name)
def test_measurement_types_resolve_to_cards(qpath):
    valid = _valid_measurement_types()
    if not valid:
        pytest.skip("no card measurement_types discovered")
    doc = yaml.safe_load(qpath.read_text()) or {}
    dangling = [
        (q.get("id"), mt)
        for q in (doc.get("questions") or [])
        for mt in (q.get("measurement_types") or [])
        if mt not in valid
    ]
    assert not dangling, (qpath.parent.name, dangling)
