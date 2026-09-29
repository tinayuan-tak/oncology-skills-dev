"""Tests for validate_measurement_types.py — the measurement-type registry governance validator.

Asserts the REAL vocabulary is clean, and that each governance rule from DATA_TO_SKILL_CONTRACT.md
FAILS a deliberately-broken synthetic vocab: missing evidence_tier, dangling derived_from input,
multi-provider-without-policy, unknown grain, self-reference, and a derived cycle. Hermetic —
synthetic vocabs written to tmp; the real-vocab test guards the shipped file.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _load(mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, REPO / "validators" / f"{mod_name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


VM = _load("validate_measurement_types")


def _write(tmp_path: Path, doc: dict) -> Path:
    p = tmp_path / "measurement_types.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


def _base_doc(**type_overrides) -> dict:
    types = {
        "crispr_lof_dependency": {
            "claim": "CRISPR LOF dependency.",
            "entity_grains": ["target"],
            "providers": [{"kind": "dataset", "source": "depmap-26q1", "evidence_tier": "measured"}],
        },
    }
    types.update(type_overrides)
    return {
        "schema_version": 1,
        "entity_grain_vocabulary": {
            "target": {"partition_required": False},
            "target_lineage": {"partition_required": False},
        },
        "measurement_types": types,
    }


def _errs(r):
    return "\n".join(r.errors)


# ---------- the real shipped vocab is clean ----------


def test_real_vocabulary_is_clean():
    r = VM.validate(REPO / "vocabularies" / "measurement_types.yaml", REPO / "cards")
    assert r.ok, _errs(r)


# ---------- each governance rule is enforced ----------


def test_missing_evidence_tier_fails(tmp_path):
    doc = _base_doc(
        bad={"claim": "x", "entity_grains": ["target"], "providers": [{"kind": "dataset", "source": "s"}]}
    )  # no evidence_tier
    r = VM.validate(_write(tmp_path, doc), None)
    assert not r.ok and "evidence_tier" in _errs(r)


def test_dangling_derived_input_fails(tmp_path):
    doc = _base_doc(
        deriv={
            "claim": "x",
            "entity_grains": ["target"],
            "providers": [
                {"kind": "derived_from", "inputs": ["nonexistent_type"], "method": "m", "evidence_tier": "measured"}
            ],
        }
    )
    r = VM.validate(_write(tmp_path, doc), None)
    assert not r.ok and "dangling DAG edge" in _errs(r)


def test_multi_provider_without_policy_fails(tmp_path):
    doc = _base_doc(
        twop={
            "claim": "x",
            "entity_grains": ["target"],
            "providers": [
                {"kind": "dataset", "source": "a", "evidence_tier": "measured"},
                {"kind": "dataset", "source": "b", "evidence_tier": "inferred"},
            ],
        }
    )
    r = VM.validate(_write(tmp_path, doc), None)
    assert not r.ok and "multi_provider_policy" in _errs(r)


def test_multi_provider_with_policy_passes(tmp_path):
    doc = _base_doc(
        twop={
            "claim": "x",
            "entity_grains": ["target"],
            "multi_provider_policy": "tier_dominant",
            "providers": [
                {"kind": "dataset", "source": "a", "evidence_tier": "measured"},
                {"kind": "dataset", "source": "b", "evidence_tier": "inferred"},
            ],
        }
    )
    r = VM.validate(_write(tmp_path, doc), None)
    assert r.ok, _errs(r)


def test_unknown_grain_fails(tmp_path):
    doc = _base_doc(
        g={
            "claim": "x",
            "entity_grains": ["target_galaxy"],
            "providers": [{"kind": "dataset", "source": "s", "evidence_tier": "measured"}],
        }
    )
    r = VM.validate(_write(tmp_path, doc), None)
    assert not r.ok and "not in entity_grain_vocabulary" in _errs(r)


def test_self_referential_derived_fails(tmp_path):
    doc = _base_doc(
        selfref={
            "claim": "x",
            "entity_grains": ["target"],
            "providers": [{"kind": "derived_from", "inputs": ["selfref"], "method": "m", "evidence_tier": "measured"}],
        }
    )
    r = VM.validate(_write(tmp_path, doc), None)
    assert not r.ok and "self-referential" in _errs(r)


def test_derived_cycle_detected(tmp_path):
    doc = _base_doc(
        a={
            "claim": "a",
            "entity_grains": ["target"],
            "providers": [{"kind": "derived_from", "inputs": ["b"], "method": "m", "evidence_tier": "measured"}],
        },
        b={
            "claim": "b",
            "entity_grains": ["target"],
            "providers": [{"kind": "derived_from", "inputs": ["a"], "method": "m", "evidence_tier": "measured"}],
        },
    )
    r = VM.validate(_write(tmp_path, doc), None)
    assert not r.ok and "CYCLE" in _errs(r)


def test_dangling_card_backref_fails(tmp_path):
    doc = _base_doc(
        t={
            "claim": "x",
            "entity_grains": ["target"],
            "cards": ["no-such-card"],
            "providers": [{"kind": "dataset", "source": "s", "evidence_tier": "measured"}],
        }
    )
    # cards dir = the tmp (empty) → known_cards is an empty set, so the backref dangles
    (tmp_path / "cards").mkdir()
    r = VM.validate(_write(tmp_path, doc), tmp_path / "cards")
    assert not r.ok and "back-ref" in _errs(r)


# ---------- evidence_substrate (Rule 7, independence-before-certainty) ----------


def test_unknown_evidence_substrate_fails(tmp_path):
    doc = _base_doc()
    doc["evidence_substrates"] = {"real_substrate": {"description": "d"}}
    doc["measurement_types"]["crispr_lof_dependency"]["evidence_substrate"] = "not_a_real_substrate"
    r = VM.validate(_write(tmp_path, doc), None)
    assert not r.ok and "not a key in the" in _errs(r) and "evidence_substrates" in _errs(r)


def test_dataset_type_declares_valid_substrate_passes(tmp_path):
    """A dataset-kind base type may declare any vocab substrate — it asserts its own raw substrate."""
    doc = _base_doc()
    doc["evidence_substrates"] = {"depmap_crispr_chronos": {"description": "d"}}
    doc["measurement_types"]["crispr_lof_dependency"]["evidence_substrate"] = "depmap_crispr_chronos"
    r = VM.validate(_write(tmp_path, doc), None)
    assert r.ok, _errs(r)


def test_derived_type_inherits_input_substrate_passes(tmp_path):
    """A derived type whose declared substrate IS carried by a derived_from input is valid."""
    doc = _base_doc(
        strat={
            "claim": "mutation-stratified dependency",
            "entity_grains": ["target"],
            "evidence_substrate": "depmap_crispr_chronos",
            "providers": [
                {
                    "kind": "derived_from",
                    "inputs": ["crispr_lof_dependency"],
                    "method": "stratified",
                    "evidence_tier": "measured",
                }
            ],
        }
    )
    doc["evidence_substrates"] = {"depmap_crispr_chronos": {"description": "d"}}
    doc["measurement_types"]["crispr_lof_dependency"]["evidence_substrate"] = "depmap_crispr_chronos"
    r = VM.validate(_write(tmp_path, doc), None)
    assert r.ok, _errs(r)


def test_derived_type_invents_substrate_absent_from_lineage_fails(tmp_path):
    """A derived type cannot claim a substrate none of its inputs carry (Rule 7)."""
    doc = _base_doc(
        strat={
            "claim": "stratified dependency claiming a substrate its lineage does not touch",
            "entity_grains": ["target"],
            "evidence_substrate": "recount3_tcga_gtex_bulk_rna",
            "providers": [
                {
                    "kind": "derived_from",
                    "inputs": ["crispr_lof_dependency"],
                    "method": "stratified",
                    "evidence_tier": "measured",
                }
            ],
        }
    )
    doc["evidence_substrates"] = {
        "depmap_crispr_chronos": {"description": "d"},
        "recount3_tcga_gtex_bulk_rna": {"description": "d"},
    }
    doc["measurement_types"]["crispr_lof_dependency"]["evidence_substrate"] = "depmap_crispr_chronos"
    r = VM.validate(_write(tmp_path, doc), None)
    assert not r.ok and "no derived_from input carries it" in _errs(r)


def test_derived_type_transitive_substrate_inheritance_passes(tmp_path):
    """Substrate inheritance walks the transitive input closure through an untagged intermediate."""
    doc = _base_doc(
        mid={
            "claim": "intermediate derived, untagged",
            "entity_grains": ["target"],
            "providers": [
                {
                    "kind": "derived_from",
                    "inputs": ["crispr_lof_dependency"],
                    "method": "m",
                    "evidence_tier": "measured",
                }
            ],
        },
        leaf={
            "claim": "leaf derived, inherits through the untagged intermediate",
            "entity_grains": ["target"],
            "evidence_substrate": "depmap_crispr_chronos",
            "providers": [{"kind": "derived_from", "inputs": ["mid"], "method": "m", "evidence_tier": "measured"}],
        },
    )
    doc["evidence_substrates"] = {"depmap_crispr_chronos": {"description": "d"}}
    doc["measurement_types"]["crispr_lof_dependency"]["evidence_substrate"] = "depmap_crispr_chronos"
    r = VM.validate(_write(tmp_path, doc), None)
    assert r.ok, _errs(r)
