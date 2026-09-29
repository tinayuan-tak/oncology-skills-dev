"""evidence_package `subtype_resolved` block — subtype-first-class-evidence-axis spec (Option A).

The framework builds molecular-subtype signal at the data/method/card layers, but by the time it
reaches the evidence package it collapses to near-nothing: `context.subgroup_spec` was hardcoded
null and the per-stratum panoramas rode buried in raw card blobs. Option A surfaces those per-stratum
SIGNALS into a first-class, machine-readable `subtype_resolved` block the cross-evidence integrator
can reason over — WITHOUT changing the deterministic spine's deliberate "subtype = context, not a
gate" treatment. These tests pin the schema half:

  - the block is OPTIONAL — a default (no-strata) envelope that omits it still validates
    (byte-stable, additive, non-breaking); the top-level schema is unevaluatedProperties:false, so
    the key had to be declared to be accepted at all;
  - a populated block (requested_strata + per-stratum records + convergence facet) validates, and
    context.subgroup_spec accepts the strata list;
  - the block's required fields (schema_version==1, requested_strata, per_stratum) + the per-stratum
    record's required fields (stratum, axes) are enforced;
  - a stratum below its n-floor is representable (subgroup_n_floor_met:false) — the absence-discipline
    the SOFT-context invariant rests on.
"""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[2]
PKG_SCHEMA = json.loads((REPO / "schemas" / "evidence_package.schema.json").read_text())
VALIDATOR = Draft202012Validator(PKG_SCHEMA)


def _errors(instance):
    return [
        f"[{'.'.join(str(p) for p in e.absolute_path) or '<root>'}] {e.message}"
        for e in VALIDATOR.iter_errors(instance)
    ]


def _base_ep(**overrides):
    """A minimal schema-valid evidence_package envelope (no subtype_resolved)."""
    ep = {
        "package_id": "ep-kras-coadread-unpinned-exploratory-001",
        "framework_version": "2.0.0",
        "generated_at": "2026-08-17T00:00:00Z",
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
        "synthesis": {"headline": "KRAS in COADREAD: nominate (high confidence)"},
        "renderings": {"markdown": "dashboard.md"},
        "schema_version": 1,
    }
    ep.update(overrides)
    return ep


def _populated_subtype_resolved():
    return {
        "schema_version": 1,
        "requested_strata": ["MSI_H", "MSS"],
        "available_strata": ["MSI_H", "MSS"],
        "per_stratum": [
            {
                "stratum": "MSS",
                "axes": {
                    "dependency": {
                        "evidence_state": "measured",
                        "subgroup_n": 42,
                        "subgroup_n_floor_met": True,
                        "metric": {"chronos_median": -0.6},
                    },
                    "mutation_frequency": {
                        "evidence_state": "measured",
                        "subgroup_n": 310,
                        "subgroup_n_floor_met": True,
                        "metric": {"mutated_fraction": 0.41},
                    },
                },
            },
            {
                "stratum": "MSI_H",
                "axes": {
                    "dependency": {
                        # below n-floor: present but carries NO weight (absence-discipline)
                        "evidence_state": "underpowered",
                        "subgroup_n": 4,
                        "subgroup_n_floor_met": False,
                        "metric": {},
                    },
                },
            },
        ],
        "convergence_facet": {
            "verdict": "single_axis_stratification",
            "convergent_subtypes": [],
            "associated_subtypes": [],
            "per_subtype": {"MSS": {"axes_measured": ["dependency", "mutation_frequency"]}},
        },
        "_disclaimer": "Subtype is SOFT integrator context, never a gate.",
    }


# ---------- optional / backward-compat ----------


def test_default_envelope_without_block_validates():
    """Default (no-strata) runs OMIT the block and must still validate — additive, non-breaking."""
    assert _errors(_base_ep()) == []


def test_top_level_rejects_unknown_key_but_accepts_subtype_resolved():
    """unevaluatedProperties:false means the key had to be DECLARED to be accepted."""
    # a genuinely unknown key is still rejected (guards the additive claim is real, not a loosening)
    assert _errors(_base_ep(some_unknown_key={})) != []
    # subtype_resolved is now an accepted top-level property
    assert _errors(_base_ep(subtype_resolved=_populated_subtype_resolved())) == []


# ---------- populated block ----------


def test_populated_block_validates_with_strata_subgroup_spec():
    ep = _base_ep(subtype_resolved=_populated_subtype_resolved())
    ep["context"]["subgroup_spec"] = ["MSI_H", "MSS"]  # no longer hardcoded null
    ep["context"]["scope"] = "cancer_subtype"  # scope must AGREE with subgroup_spec (2026-09-18 invariant)
    assert _errors(ep) == []


def test_below_floor_stratum_is_representable():
    ep = _base_ep(subtype_resolved=_populated_subtype_resolved())
    msi = next(r for r in ep["subtype_resolved"]["per_stratum"] if r["stratum"] == "MSI_H")
    assert msi["axes"]["dependency"]["subgroup_n_floor_met"] is False
    assert _errors(ep) == []


# ---------- required-field enforcement ----------


def test_block_requires_per_stratum():
    block = _populated_subtype_resolved()
    del block["per_stratum"]
    assert _errors(_base_ep(subtype_resolved=block)) != []


def test_block_requires_schema_version_const_1():
    block = _populated_subtype_resolved()
    block["schema_version"] = 2
    assert _errors(_base_ep(subtype_resolved=block)) != []


def test_stratum_record_requires_stratum_and_axes():
    block = _populated_subtype_resolved()
    block["per_stratum"].append({"axes": {}})  # missing `stratum`
    assert _errors(_base_ep(subtype_resolved=block)) != []

    block2 = _populated_subtype_resolved()
    block2["per_stratum"].append({"stratum": "CMS1"})  # missing `axes`
    assert _errors(_base_ep(subtype_resolved=block2)) != []


# ---------- scope <-> subgroup_spec consistency invariant (2026-09-18) ----------
# scope was hardcoded "cancer_type" in the skills emitter regardless of subgroup_spec, so a subtype
# run silently emitted cancer_type + a strata list. The emitter now derives scope from subgroup_spec;
# this schema invariant pins that agreement so the two can never disagree again. Both directions are
# tested by MUTATION so the guard is real, not decoration.


def test_cancer_subtype_requires_nonnull_subgroup_spec():
    ep = _base_ep()
    ep["context"]["scope"] = "cancer_subtype"
    ep["context"]["subgroup_spec"] = None  # a subtype scope with no subgroup is contradictory
    assert any("subgroup_spec" in e or "context" in e for e in _errors(ep)), _errors(ep)


def test_cancer_subtype_requires_present_subgroup_spec():
    ep = _base_ep()
    ep["context"]["scope"] = "cancer_subtype"
    del ep["context"]["subgroup_spec"]  # absent is also contradictory for a subtype scope
    assert _errors(ep) != []


def test_cancer_type_forbids_a_subgroup_spec():
    ep = _base_ep()  # scope stays cancer_type
    ep["context"]["subgroup_spec"] = ["MSI_H", "MSS"]  # a strata list on an indication scope
    assert _errors(ep) != []


def test_pancancer_forbids_a_subgroup_spec():
    ep = _base_ep()
    ep["context"]["scope"] = "pancancer"
    ep["context"]["subgroup_spec"] = "all"
    assert _errors(ep) != []


def test_consistent_scope_subgroup_pairs_validate():
    # cancer_type + null (the byte-stable default)
    assert _errors(_base_ep()) == []
    # cancer_subtype + strata list
    ep = _base_ep()
    ep["context"]["scope"] = "cancer_subtype"
    ep["context"]["subgroup_spec"] = ["MSI_H", "MSS"]
    assert _errors(ep) == []
    # cancer_subtype + the "all" sentinel
    ep = _base_ep()
    ep["context"]["scope"] = "cancer_subtype"
    ep["context"]["subgroup_spec"] = "all"
    assert _errors(ep) == []
    # cancer_type + absent subgroup_spec
    ep = _base_ep()
    del ep["context"]["subgroup_spec"]
    assert _errors(ep) == []
