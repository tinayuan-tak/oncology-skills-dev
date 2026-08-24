"""claim_record schema + cross-field invariants (M0 of the factored-record migration).

Pins that (1) the shipped hand-authored examples are BOTH schema-valid AND satisfy the four
intra-record invariants, and (2) each invariant actually FAILS a crafted violation — so the
validator is a real guard, not a rubber stamp, before any skill emits the record at M1.
"""
import copy
import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "validators"))
import validate_claim_record as vcr  # noqa: E402

SCHEMA_PATH = REPO / "schemas" / "claim_record.schema.json"
EXAMPLES = REPO / "docs" / "design" / "examples"
RESOLVERS = REPO / "resolvers"
SCHEMA = json.loads(SCHEMA_PATH.read_text())
EMITTED = vcr.emitted_verdicts_by_gate(RESOLVERS)


# ---------- schema well-formedness + shipped examples ----------

def test_schema_is_valid_draft202012():
    Draft202012Validator.check_schema(SCHEMA)


def test_shipped_examples_pass_end_to_end():
    report = vcr.validate(SCHEMA_PATH, EXAMPLES, RESOLVERS)
    assert report.ok, f"shipped examples failed: {report.errors}"
    assert report.checked_count >= 3, "expected the 3 worked examples to be validated"


def _load(name):
    return yaml.safe_load((EXAMPLES / name).read_text())


def _run_one(rec):
    """Schema-validate + invariant-check a single record; return its report."""
    report = vcr.ClaimRecordReport()
    vcr.validate_record(rec, "test", SCHEMA, Draft202012Validator, EMITTED, report)
    return report


# ---------- invariant A: open-world => non-committal finding ----------

def test_open_world_must_be_unknown_state():
    rec = _load("claim_record.selectivity.open_world.example.yaml")
    bad = copy.deepcopy(rec)
    bad["finding"]["state"] = "strong_tumor_selective"  # a real verdict, but illegal under not_wired
    r = _run_one(bad)
    assert not r.ok and any("OPEN_WORLD_STATE" in e for e in r.errors)


def test_open_world_must_be_neutral_direction():
    rec = _load("claim_record.selectivity.open_world.example.yaml")
    bad = copy.deepcopy(rec)
    bad["finding"]["direction"] = "opposes"
    r = _run_one(bad)
    assert not r.ok and any("OPEN_WORLD_DIRECTION" in e for e in r.errors)


# ---------- invariant B: no bare numbers ----------

def test_value_requires_scale():
    rec = _load("claim_record.genomic_alteration.example.yaml")
    bad = copy.deepcopy(rec)
    bad["finding"]["magnitude"]["scale"] = None      # value stays set, scale nulled
    r = _run_one(bad)
    assert not r.ok and any("BARE_NUMBER" in e for e in r.errors)


# ---------- invariant C: finding.state in the axis resolver's emitted set ----------

def test_state_must_be_emitted_by_resolver():
    rec = _load("claim_record.genomic_alteration.example.yaml")
    bad = copy.deepcopy(rec)
    bad["finding"]["state"] = "totally_made_up_verdict"
    r = _run_one(bad)
    assert not r.ok and any("UNKNOWN_STATE" in e for e in r.errors)


def test_no_resolver_axis_is_unchecked_not_error():
    rec = _load("claim_record.genomic_alteration.example.yaml")
    probe = copy.deepcopy(rec)
    probe["axis"] = "expression"                     # a no-resolver inline axis
    probe["finding"]["state"] = "anything_goes_here"
    r = _run_one(probe)
    assert r.ok, "a no-resolver axis must be UNCHECKED (warning), not an error"
    assert "expression" in r.unchecked_axes


# ---------- invariant D: certainty.level <= ordinal min(coverage, corroboration), DOWNGRADE-ONLY ----------

def test_unmeasured_corroboration_level_bounded_by_coverage():
    rec = _load("claim_record.safety.example.yaml")           # coverage=medium, corrob=unmeasured
    bad = copy.deepcopy(rec)
    bad["certainty"]["level"] = "high"                        # high > coverage (medium) — over-claim
    r = _run_one(bad)
    assert not r.ok and any("CERTAINTY_LEVEL" in e for e in r.errors)


def test_level_may_not_exceed_ordinal_min():
    rec = _load("claim_record.genomic_alteration.example.yaml")  # high/high/high => high
    bad = copy.deepcopy(rec)
    bad["certainty"]["coverage"] = "low"                        # min(low, high) = low, but level says high
    r = _run_one(bad)
    assert not r.ok and any("CERTAINTY_LEVEL" in e for e in r.errors)


def test_downgrade_below_min_is_allowed():
    # a skill may legitimately downgrade level BELOW the min (e.g. 'low' on a none-verdict) — not an error
    rec = _load("claim_record.genomic_alteration.example.yaml")  # coverage=high, corrob=high
    ok = copy.deepcopy(rec)
    ok["certainty"]["level"] = "low"                             # downgrade — allowed
    r = _run_one(ok)
    assert r.ok, f"a downgrade below the ordinal min must be allowed, got: {r.errors}"
