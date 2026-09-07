"""evidence_package `synthesis.claim_vectors[*].claim_vector[axis].evidence_atom` — the structural
CITATION-INTEGRITY guard (Group D 2026-08-21, atomization hardening).

Before this, `claim_vector` was an opaque object: an atom could carry a malformed / card_id-less
citation and still validate, so a drifted producer (the ~13 hand-rolled atom builders, now unified on
`claim_vector_core.build_atom`) could emit an un-citable atom silently. The `$defs.evidence_atom` def
pins the minimum: a present `evidence_atom` must carry `values` + a `cite.card_id` string (a real,
composed card the cross-evidence reasoner can cite). These tests pin:
  - a well-formed atom validates, and the `_disclaimer` string on the same claim_vector still validates;
  - a present atom MISSING cite.card_id is REJECTED (the guard bites);
  - the block stays OPTIONAL/additive — a package with no claim_vectors still validates.
"""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[2]
VALIDATOR = Draft202012Validator(json.loads((REPO / "schemas" / "evidence_package.schema.json").read_text()))


def _errors(instance):
    return [
        f"[{'.'.join(str(p) for p in e.absolute_path) or '<root>'}] {e.message}"
        for e in VALIDATOR.iter_errors(instance)
    ]


def _base_ep(**overrides):
    ep = {
        "package_id": "ep-kras-coadread-unpinned-exploratory-001",
        "framework_version": "2.0.0",
        "generated_at": "2026-08-21T00:00:00Z",
        "generated_by": "skills/target-profile@abc1234",
        "context": {
            "target": {"symbol": "KRAS", "hgnc_id": 6407},
            "indication": {"oncotree_code": "COADREAD"},
            "subgroup_spec": None,
            "scope": "cancer_type",
        },
        "governance": {
            "data_mode": "exploratory",
            "release_pin": "unpinned",
            "validation_summary": {
                "n_cards_attempted": 1,
                "n_cards_passed": 1,
                "n_cards_passed_with_warnings": 0,
                "n_cards_failed": 0,
                "n_cards_excluded_by_applies_when": 0,
            },
        },
        "dashboard_spec_ref": "skill:target-profile",
        "cards": [],
        "synthesis": {"headline": "KRAS in COADREAD"},
        "renderings": {"markdown": "dashboard.md"},
        "schema_version": 1,
    }
    ep.update(overrides)
    return ep


def _cv(atom):
    return {
        "dependency": {
            "claim_vector": {
                "DEP": {"signal": "strong", "corroboration": "high", "evidence_atom": atom},
                "_disclaimer": "verdict-inert projection",
            }
        }
    }


_GOOD_ATOM = {
    "read": "dependent",
    "values": {"chronos": -1.2, "n": 300},
    "cite": {"card_id": "pan-cancer-crispr-dependency-distribution", "fields": ["chronos", "n"]},
    "entity": {"measurement_type": "dependency_score", "grain": "target_indication"},
}


def test_wellformed_atom_and_disclaimer_string_validate():
    ep = _base_ep(synthesis={"headline": "KRAS in COADREAD: dependency signal", "claim_vectors": _cv(_GOOD_ATOM)})
    assert _errors(ep) == []


def test_atom_missing_card_id_is_rejected():
    bad = json.loads(json.dumps(_GOOD_ATOM))
    bad["cite"].pop("card_id")
    ep = _base_ep(synthesis={"headline": "KRAS in COADREAD: dependency signal", "claim_vectors": _cv(bad)})
    errs = _errors(ep)
    assert any("claim_vectors" in e for e in errs), (
        f"an evidence_atom without cite.card_id must fail on the atom (citation-integrity guard); got {errs}"
    )


def test_atom_missing_cite_or_values_is_rejected():
    for drop in ("cite", "values"):
        bad = json.loads(json.dumps(_GOOD_ATOM))
        bad.pop(drop)
        ep = _base_ep(synthesis={"headline": "KRAS in COADREAD: dependency signal", "claim_vectors": _cv(bad)})
        assert any("claim_vectors" in e for e in _errors(ep)), f"an evidence_atom missing {drop} must fail on the atom"


def test_claim_vectors_optional_additive():
    # a package with NO claim_vectors (a compose-dashboard-style envelope) still validates
    assert _errors(_base_ep()) == []
