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
    # 3 original worked examples + the pan-cancer (scope: ALL) context/identity example.
    assert report.checked_count >= 4, "expected the 4 worked examples to be validated"


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
    bad["finding"]["magnitude"]["scale"] = None  # value stays set, scale nulled
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
    probe["axis"] = "expression"  # a no-resolver inline axis
    probe["finding"]["state"] = "anything_goes_here"
    probe["provenance"]["legacy_verdict"] = "anything_goes_here"  # keep invariant E satisfied
    r = _run_one(probe)
    assert r.ok, "a no-resolver axis must be UNCHECKED (warning), not an error"
    assert "expression" in r.unchecked_axes


# ---------- invariant D: certainty.level <= ordinal min(coverage, corroboration), DOWNGRADE-ONLY ----------


def test_unmeasured_corroboration_level_bounded_by_coverage():
    rec = _load("claim_record.safety.example.yaml")  # coverage=medium, corrob=unmeasured
    bad = copy.deepcopy(rec)
    bad["certainty"]["level"] = "high"  # high > coverage (medium) — over-claim
    r = _run_one(bad)
    assert not r.ok and any("CERTAINTY_LEVEL" in e for e in r.errors)


def test_level_may_not_exceed_ordinal_min():
    rec = _load("claim_record.genomic_alteration.example.yaml")  # high/high/high => high
    bad = copy.deepcopy(rec)
    bad["certainty"]["coverage"] = "low"  # min(low, high) = low, but level says high
    r = _run_one(bad)
    assert not r.ok and any("CERTAINTY_LEVEL" in e for e in r.errors)


# ---------- invariant E: provenance.legacy_verdict is the M2 render-equivalence anchor ----------


def test_measured_state_must_match_legacy_verdict():
    rec = _load("claim_record.genomic_alteration.example.yaml")  # measured; legacy==state
    assert _run_one(rec).ok
    bad = copy.deepcopy(rec)
    bad["provenance"]["legacy_verdict"] = "some_other_token"  # measured state must equal legacy
    r = _run_one(bad)
    assert not r.ok and any("LEGACY_VERDICT" in e for e in r.errors)


def test_open_world_legacy_verdict_may_differ_from_unknown():
    rec = _load("claim_record.selectivity.open_world.example.yaml")  # state='unknown', legacy='data_unavailable'
    r = _run_one(rec)
    assert r.ok, f"open-world legacy_verdict may differ from 'unknown': {r.errors}"


def test_downgrade_below_min_is_allowed():
    # a skill may legitimately downgrade level BELOW the min (e.g. 'low' on a none-verdict) — not an error
    rec = _load("claim_record.genomic_alteration.example.yaml")  # coverage=high, corrob=high
    ok = copy.deepcopy(rec)
    ok["certainty"]["level"] = "low"  # downgrade — allowed
    r = _run_one(ok)
    assert r.ok, f"a downgrade below the ordinal min must be allowed, got: {r.errors}"


# ---------- record-grain context + identity (F/G/H, 2026-09-18) ----------

PAN = "claim_record.genomic_alteration.pan_cancer.example.yaml"


def test_pan_cancer_example_valid():
    """The scope: ALL example is schema-valid AND satisfies every context/identity invariant."""
    r = _run_one(_load(PAN))
    assert r.ok, f"pan-cancer example failed: {r.errors}"


def _reidentify(rec):
    """Recompute a record's identity from its (possibly mutated) context, so an H-arm test is not
    masked by a stale context_id firing CONTEXT_ID_MISMATCH first."""
    ctx = rec["context"]
    cid = vcr._canonical_sha16(ctx)
    lk = f"{cid}::{rec['axis']}"
    versions = (rec.get("provenance") or {}).get("versions") or {}
    ident = rec["identity"]
    payload = "|".join([lk, ident["l0_digest"], ident["ruleset_version"], vcr._canonical_json(versions)])
    import hashlib

    ident["context_id"] = cid
    ident["logical_key"] = lk
    ident["record_revision_id"] = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return rec


# F/G: identity is DERIVED — every field recomputes, never trusted.


def test_context_id_recomputed():
    bad = copy.deepcopy(_load(PAN))
    bad["identity"]["context_id"] = "0000000000000000"
    bad["identity"]["logical_key"] = "0000000000000000::genomic_alteration"
    r = _run_one(bad)
    assert not r.ok and any("CONTEXT_ID_MISMATCH" in e for e in r.errors), r.errors


def test_logical_key_recomputed():
    bad = copy.deepcopy(_load(PAN))
    bad["identity"]["logical_key"] = bad["identity"]["context_id"] + "::wrong_axis"
    r = _run_one(bad)
    assert not r.ok and any("LOGICAL_KEY_MISMATCH" in e for e in r.errors), r.errors


def test_record_revision_id_recomputed():
    bad = copy.deepcopy(_load(PAN))
    bad["identity"]["record_revision_id"] = "ffffffffffffffff"
    r = _run_one(bad)
    assert not r.ok and any("RECORD_REVISION_ID_MISMATCH" in e for e in r.errors), r.errors


def test_record_revision_id_moves_with_l0_digest():
    """The data fingerprint really feeds the revision id: change l0_digest and the OLD rrid is stale."""
    bad = copy.deepcopy(_load(PAN))
    bad["identity"]["l0_digest"] = "1111111111111111"  # a different release; rrid not recomputed
    r = _run_one(bad)
    assert not r.ok and any("RECORD_REVISION_ID_MISMATCH" in e for e in r.errors), r.errors


def test_identity_requires_context():
    bad = copy.deepcopy(_load(PAN))
    del bad["context"]
    r = _run_one(bad)
    assert not r.ok and any("IDENTITY_WITHOUT_CONTEXT" in e for e in r.errors), r.errors


# H: the scope <-> specifier-field coupling (the ALL arm is tested here — R7).


def test_all_indication_scope_forbids_oncotree_code():
    """R7: mutating the scope: ALL arm (adding a specifier) must RED — the arm is not decoration."""
    bad = copy.deepcopy(_load(PAN))
    bad["context"]["indication"]["oncotree_code"] = "COAD"  # illegal on an ALL scope
    _reidentify(bad)  # keep identity consistent so INDICATION_SCOPE_FIELD is the isolated failure
    r = _run_one(bad)
    assert not r.ok and any("INDICATION_SCOPE_FIELD" in e for e in r.errors), r.errors


def test_specific_indication_scope_requires_oncotree_code():
    bad = copy.deepcopy(_load(PAN))
    bad["context"]["indication"]["scope"] = "SPECIFIC"  # now demands oncotree_code, which is absent
    _reidentify(bad)
    r = _run_one(bad)
    assert not r.ok and any("INDICATION_SCOPE_FIELD" in e for e in r.errors), r.errors


def test_not_stratified_subtype_forbids_subgroup_ids():
    bad = copy.deepcopy(_load(PAN))
    bad["context"]["subtype"]["subgroup_ids"] = ["CMS1"]  # illegal on NOT_STRATIFIED
    _reidentify(bad)
    r = _run_one(bad)
    assert not r.ok and any("SUBTYPE_SCOPE_FIELD" in e for e in r.errors), r.errors


def test_all_modality_scope_forbids_channel():
    bad = copy.deepcopy(_load(PAN))
    bad["context"]["modality"]["channel"] = "small_molecule"  # illegal on an ALL scope
    _reidentify(bad)
    r = _run_one(bad)
    assert not r.ok and any("MODALITY_SCOPE_FIELD" in e for e in r.errors), r.errors


def test_specific_modality_scope_recomputes_and_passes():
    """A well-formed SPECIFIC record (channel present, ids recomputed) is clean — proves the coupling
    is a real biconditional, not a blanket 'ALL good / SPECIFIC bad'."""
    ok = copy.deepcopy(_load(PAN))
    ok["context"]["modality"] = {"scope": "SPECIFIC", "channel": "degrader"}
    _reidentify(ok)
    r = _run_one(ok)
    assert r.ok, f"a valid SPECIFIC-modality record must pass, got: {r.errors}"
