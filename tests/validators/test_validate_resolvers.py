"""Tests for validate_resolvers.py (gap #5 static resolver validator).

Asserts both directions: the shipped dependency.resolver.yaml is clean, AND each failure
mode (dangling rung, bad driving_rule, missing default, structural) is caught — so a
typo'd/renamed rule_id in a rung fails CI (the silent-drift class an if-chain can't catch).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "validate_resolvers", REPO / "validators" / "validate_resolvers.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["validate_resolvers"] = m
    spec.loader.exec_module(m)
    return m


VR = _load()
_KNOWN = VR._all_rule_ids(REPO / "interpretation-rules")


def _write(tmp_path, spec: dict) -> Path:
    p = tmp_path / "x.resolver.yaml"
    p.write_text(yaml.safe_dump(spec))
    return p


def _base(**over) -> dict:
    spec = {
        "gate": "dependency", "version": "1.0.0",
        "resolve": [{"verdict": "non_dependent", "when_fired": "non-dependent-killer"}],
        "default": "insufficient",
    }
    spec.update(over)
    return spec


# --- the shipped spec is clean ---

def test_shipped_dependency_resolver_is_clean():
    r = VR.validate_resolver_file(REPO / "resolvers" / "dependency.resolver.yaml", _KNOWN)
    assert r.ok, f"shipped dependency resolver must validate: {r.errors}"


# --- dangling rung (typo / renamed rule) is caught ---

def test_dangling_rung_rule_id_fails(tmp_path):
    spec = _base(resolve=[{"verdict": "foo", "when_fired": "this-rule-does-not-exist"}])
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN)
    assert not r.ok
    assert any("DANGLING_RUNG" in e for e in r.errors)


def test_dangling_in_when_all_fired_caught(tmp_path):
    spec = _base(resolve=[{"verdict": "foo",
                           "when_all_fired": ["non-dependent-killer", "nope-not-real"]}])
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN)
    assert not r.ok and any("DANGLING_RUNG" in e for e in r.errors)


# --- bad driving_rule (not one of the rung's own rules) is caught ---

def test_bad_driving_rule_fails(tmp_path):
    spec = _base(resolve=[{"verdict": "foo",
                           "when_all_fired": ["non-dependent-killer",
                                              "strong-paralog-buffering-degrader-preferred"],
                           "driving_rule": "lineage-selective-supportive"}])  # not in the rung
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN)
    assert not r.ok and any("BAD_DRIVING_RULE" in e for e in r.errors)


def test_valid_driving_rule_passes(tmp_path):
    spec = _base(resolve=[{"verdict": "foo",
                           "when_all_fired": ["non-dependent-killer",
                                              "strong-paralog-buffering-degrader-preferred"],
                           "driving_rule": "strong-paralog-buffering-degrader-preferred"}])
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN)
    assert r.ok, r.errors


# --- structural (schema) failures ---

def test_missing_default_fails(tmp_path):
    spec = _base()
    del spec["default"]
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN)
    assert not r.ok  # schema requires default → STRUCTURAL error


def test_rung_with_no_predicate_fails(tmp_path):
    spec = _base(resolve=[{"verdict": "foo"}])  # no when_* → schema oneOf fails
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN)
    assert not r.ok
