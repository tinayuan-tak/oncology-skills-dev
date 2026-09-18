"""Tests for build_summary_field_types.py — the structural type partition of summary fields.

Pins: the committed snapshot is fresh (--self-check green), the drift detector is non-vacuous (a
mutated snapshot reds), the per-property classifier is correct, and the coverage arithmetic holds.
Hermetic — reads the committed generated schemas; the drift test monkeypatches the snapshot path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "build_summary_field_types", REPO / "validators" / "build_summary_field_types.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_summary_field_types"] = mod
    spec.loader.exec_module(mod)
    return mod


B = _load()


# ── the CI gate: the committed snapshot is fresh ────────────────────────────────────────────────
def test_self_check_passes_on_committed_snapshot():
    ok, errs = B.self_check()
    assert ok, errs


# ── non-vacuity: the drift detector must actually fire ──────────────────────────────────────────
def test_self_check_detects_a_mutated_class(monkeypatch, tmp_path):
    partition = B.compute_partition()
    # flip one field's class to a wrong value
    card = next(iter(partition["by_card"]))
    field = next(iter(partition["by_card"][card]))
    partition["by_card"][card][field] = "boolean" if partition["by_card"][card][field] != "boolean" else "numeric"
    p = tmp_path / "summary_field_types.yaml"
    p.write_text(yaml.safe_dump(partition))
    monkeypatch.setattr(B, "PARTITION_PATH", p)
    ok, errs = B.self_check()
    assert not ok
    assert any("drift" in e for e in errs), errs


def test_self_check_detects_a_dropped_field(monkeypatch, tmp_path):
    partition = B.compute_partition()
    card = next(iter(partition["by_card"]))
    field = next(iter(partition["by_card"][card]))
    del partition["by_card"][card][field]  # a stale snapshot: schema has the field, snapshot doesn't
    p = tmp_path / "summary_field_types.yaml"
    p.write_text(yaml.safe_dump(partition))
    monkeypatch.setattr(B, "PARTITION_PATH", p)
    ok, errs = B.self_check()
    assert not ok


def test_self_check_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(B, "PARTITION_PATH", tmp_path / "nope.yaml")
    ok, errs = B.self_check()
    assert not ok and any("missing" in e for e in errs)


# ── the per-property classifier ─────────────────────────────────────────────────────────────────
def test_classify_property_cases():
    assert B.classify_property({"type": ["string", "null"], "enum": ["a", "b", None]}) == "categorical"
    assert B.classify_property({"enum": ["x"]}) == "categorical"  # enum dominates
    assert B.classify_property({"type": ["number", "null"]}) == "numeric"
    assert B.classify_property({"type": "integer"}) == "numeric"
    assert B.classify_property({"type": ["boolean", "null"]}) == "boolean"
    assert B.classify_property({"type": ["object", "null"]}) == "record"
    assert B.classify_property({"type": ["array", "null"]}) == "array"
    assert B.classify_property({"type": ["null", "string"]}) == "string"
    assert B.classify_property({}) == "unknown"
    assert B.classify_property({"type": "null"}) == "unknown"


# ── coverage arithmetic + vocabulary ────────────────────────────────────────────────────────────
def test_counts_sum_to_n_fields():
    p = B.compute_partition()
    assert sum(p["counts"].values()) == p["n_fields"]
    assert p["n_fields"] == sum(len(v) for v in p["by_card"].values())


def test_all_classes_are_in_the_vocabulary():
    p = B.compute_partition()
    seen = {cls for fields in p["by_card"].values() for cls in fields.values()}
    assert seen <= set(B.TYPE_CLASSES)
    assert set(p["counts"]) == set(B.TYPE_CLASSES)


def test_numeric_fields_exist():
    # a floor guard: the whole point is typing numeric fields the skills projection can't reach.
    # If this hits 0 the generator has stopped reading types (green-for-the-wrong-reason).
    p = B.compute_partition()
    assert p["counts"]["numeric"] > 0
