"""test_l2_context_identity.py — the L2 record-grain identity PILOT (contracts #804, decision #4).

Two guard layers:

  1. AUTHORITATIVE cross-check against the SHIPPED contracts validator. build_l2_context +
     derive_l2_identity mirror target-contracts/validators/validate_claim_record.py's pinned
     `_canonical_json` + the F/G/H `_context_identity_invariants`. That validator RECOMPUTES every id
     and is the single source of truth, so we run IT over records our helpers produce and assert zero
     errors — if either recipe drifts (separators, sort_keys, ensure_ascii, the rrid payload order) the
     recompute mismatches and this reds. We also assert our `_l2_canonical_json` is byte-identical to
     the validator's own `_canonical_json` (the drift catcher one layer down). Contracts is resolved via
     paths.target_contracts_root() (CI checks it out at the pinned SHA); skipped only when absent locally.

  2. PURE mutation controls (no contracts): perturbing any context dimension MUST move context_id;
     perturbing l0_digest / ruleset_version / a method_version MUST move record_revision_id; the
     scope<->specifier coupling holds; and _attach_l2_claim_record makes R6 (identity.l0_digest ==
     package.governance.resolved_release_digest) true BY CONSTRUCTION and degrades on an unresolved id.
"""

from __future__ import annotations

import importlib.util
import sys

import pytest
from _skills_common import paths  # noqa: E402
from _skills_common.claim_record import (  # noqa: E402
    _l2_canonical_json,
    assemble_claim_record,
    build_l2_context,
    derive_l2_identity,
)
from _skills_common.dispatcher import _attach_l2_claim_record, _l2_method_versions  # noqa: E402

# --------------------------------------------------------------------------- fixtures / helpers


def _sample_context(**over):
    base = dict(
        target={"symbol": "EPCAM", "hgnc_id": 11529, "ensembl": "ENSG00000119888"},
        indication="COADREAD",
        subgroup_spec=None,  # -> subtype NOT_STRATIFIED
        modality_scope="ALL",
    )
    base.update(over)
    return build_l2_context(**base)


def _full_record(context, versions, *, l0="0123456789abcdef", ruleset="1.22.0", axis="tumor_presence"):
    """A schema-shaped record with the L2 blocks attached, exactly as the emitter builds it."""
    rec = assemble_claim_record(
        axis=axis,
        state="present",
        direction="supports",
        availability="measured_positive",
        certainty={"level": "medium", "coverage": "medium", "corroboration": "unmeasured", "unknown_mass": 0.0},
        fired=[{"rule_id": "r1"}],
        cards=[{"card_id": "tumor-rna-vs-adjacent"}],
    )
    rec.setdefault("provenance", {})["versions"] = versions
    rec["context"] = context
    rec["identity"] = derive_l2_identity(
        context=context, axis=axis, l0_digest=l0, ruleset_version=ruleset, versions=versions
    )
    return rec


def _load_contracts_validator():
    root = paths.target_contracts_root()
    vdir = root / "validators"
    vpath = vdir / "validate_claim_record.py"
    if not vpath.exists():
        pytest.skip(f"contracts validator not found at {vpath} — set TARGET_CONTRACTS_ROOT [CI has it]")
    # validate_claim_record imports sibling validators (validate_verdict_tokens) by bare name.
    if str(vdir) not in sys.path:
        sys.path.insert(0, str(vdir))
    spec = importlib.util.spec_from_file_location("_vcr_pinned", vpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # @dataclass (py3.14) resolves cls.__module__ via sys.modules
    spec.loader.exec_module(mod)
    return mod, root


# --------------------------------------------------------------------------- (1) authoritative cross-check


def test_canonical_json_matches_contracts_byte_for_byte():
    """Our pinned serialization is byte-identical to the validator's — the deepest drift catcher."""
    vcr, _ = _load_contracts_validator()
    for obj in (
        {"b": 1, "a": [3, 2, 1]},
        _sample_context(),
        {"café": "ünïcode", "z": None, "a": 2.0},  # ensure_ascii + key sort
    ):
        assert _l2_canonical_json(obj) == vcr._canonical_json(obj)


def test_helpers_pass_contracts_context_identity_invariants():
    """Run the SHIPPED F/G/H invariants over records our helpers build — the recompute must agree."""
    vcr, _ = _load_contracts_validator()
    for ctx_over, versions in (
        (dict(indication="COADREAD", subgroup_spec=None), {"tumor-rna-vs-adjacent": "3.1.0"}),
        (dict(indication="PANCANCER", subgroup_spec=None), {}),  # ALL indication, empty versions
        (dict(indication="LUAD", subgroup_spec=["LUAD_EGFR", "LUAD_KRAS"]), {"c": "1.0"}),  # SPECIFIC subtype
        (dict(indication="BRCA", subgroup_spec="all"), {"c": "1.0"}),  # ALL subtype
    ):
        rec = _full_record(_sample_context(**ctx_over), versions)
        report = vcr.ClaimRecordReport()
        vcr._context_identity_invariants(rec, "pilot", report)
        assert report.ok, f"contracts F/G/H rejected our record: {report.errors}"


def test_record_schema_valid_against_shipped_claim_record_schema():
    """The full record (with L2 blocks) validates against the shipped claim_record.schema.json."""
    jsonschema = pytest.importorskip("jsonschema")
    _, root = _load_contracts_validator()
    import json

    schema = json.loads((root / "schemas" / "claim_record.schema.json").read_text())
    rec = _full_record(_sample_context(), {"tumor-rna-vs-adjacent": "3.1.0"})
    errs = sorted(jsonschema.Draft202012Validator(schema).iter_errors(rec), key=lambda e: list(e.path))
    assert not errs, "record violates claim_record.schema.json:\n  " + "\n  ".join(
        f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errs
    )


# --------------------------------------------------------------------------- (2) pure mutation controls


def test_context_shapes_and_scope_coupling():
    # indication
    assert _sample_context(indication="COADREAD")["indication"] == {"scope": "SPECIFIC", "oncotree_code": "COADREAD"}
    assert _sample_context(indication="PANCANCER")["indication"] == {"scope": "ALL"}
    # subtype 3-state
    assert _sample_context(subgroup_spec=None)["subtype"] == {"scope": "NOT_STRATIFIED"}
    assert _sample_context(subgroup_spec="all")["subtype"] == {"scope": "ALL"}
    assert _sample_context(subgroup_spec=["b", "a"])["subtype"] == {
        "scope": "SPECIFIC",
        "subgroup_ids": ["a", "b"],  # sorted-unique
    }
    # modality is ALL for the presence pilot; SPECIFIC without a channel is refused
    assert _sample_context()["modality"] == {"scope": "ALL"}
    with pytest.raises(ValueError):
        _sample_context(modality_scope="SPECIFIC")
    # target passthrough (optional ids only when present)
    assert _sample_context()["target"] == {"symbol": "EPCAM", "hgnc_id": 11529, "ensembl": "ENSG00000119888"}


def test_context_id_moves_with_every_context_dimension():
    base = _sample_context()
    cid = derive_l2_identity(context=base, axis="tumor_presence", l0_digest="d", ruleset_version="1", versions={})[
        "context_id"
    ]
    for changed in (
        _sample_context(indication="LUAD"),
        _sample_context(indication="PANCANCER"),
        _sample_context(subgroup_spec=["x"]),
        _sample_context(target={"symbol": "MSLN", "hgnc_id": 7371}),
    ):
        other = derive_l2_identity(
            context=changed, axis="tumor_presence", l0_digest="d", ruleset_version="1", versions={}
        )["context_id"]
        assert other != cid, f"context_id failed to move for {changed}"


def test_record_revision_id_moves_with_data_rules_and_methods():
    ctx = _sample_context()

    def rrid(*, l0, ruleset, versions):
        return derive_l2_identity(
            context=ctx, axis="tumor_presence", l0_digest=l0, ruleset_version=ruleset, versions=versions
        )["record_revision_id"]

    base = rrid(l0="d0", ruleset="1.22.0", versions={"c": "1.0"})
    assert rrid(l0="d1", ruleset="1.22.0", versions={"c": "1.0"}) != base  # data release moved
    assert rrid(l0="d0", ruleset="1.23.0", versions={"c": "1.0"}) != base  # ruleset moved
    assert rrid(l0="d0", ruleset="1.22.0", versions={"c": "2.0"}) != base  # method moved
    # logical_key is stable across a data/method revision (same context+axis)
    a = derive_l2_identity(context=ctx, axis="tumor_presence", l0_digest="d0", ruleset_version="1", versions={})
    b = derive_l2_identity(context=ctx, axis="tumor_presence", l0_digest="d9", ruleset_version="9", versions={"x": "1"})
    assert a["logical_key"] == b["logical_key"] and a["record_revision_id"] != b["record_revision_id"]


def test_method_versions_gathered_from_cards():
    cards = [
        {"card_id": "a", "summary": {"method_version": "1.0"}},
        {"card_id": "b", "summary": {}},  # no method_version -> skipped
        {"card_id": "c", "_missing": True, "summary": {"method_version": "9.9"}},  # missing -> skipped
        {"card_id": "d", "summary": {"method_version": "2.0"}},
    ]
    assert _l2_method_versions(cards) == {"a": "1.0", "d": "2.0"}


# --------------------------------------------------------------------------- _attach_l2_claim_record (R6)


def _fake_ep(*, hgnc_id=11529, digest="feedfacecafe0001"):
    return {
        "context": {"target": {"symbol": "EPCAM", "hgnc_id": hgnc_id}},
        "governance": {"resolved_release_digest": digest},
    }


def _fake_crf(cards, fired, verdict_pair):
    return assemble_claim_record(
        axis="tumor_presence",
        state="present",
        direction="supports",
        availability="measured_positive",
        certainty={"level": "medium", "coverage": "medium", "corroboration": "unmeasured", "unknown_mass": 0.0},
        fired=fired,
        cards=cards,
    )


def test_attach_sets_r6_l0_digest_by_construction():
    cards = [{"card_id": "tumor-rna-vs-adjacent", "summary": {"method_version": "3.1.0"}}]
    rec = _attach_l2_claim_record(
        ep=_fake_ep(digest="abc123abc123abcd"),
        claim_record_fn=_fake_crf,
        emitted_cards=cards,
        fired=[{"rule_id": "r1"}],
        verdict_pair=("present", "r1"),
        indication="COADREAD",
        subgroup_spec=None,
        ruleset_version="1.22.0",
    )
    # R6: the record's l0_digest is the enclosing package's resolved_release_digest.
    assert rec["identity"]["l0_digest"] == "abc123abc123abcd"
    assert rec["provenance"]["versions"] == {"tumor-rna-vs-adjacent": "3.1.0"}
    assert rec["context"]["subtype"] == {"scope": "NOT_STRATIFIED"}
    # identity recomputes from the very context we stored (self-consistency).
    recomputed = derive_l2_identity(
        context=rec["context"],
        axis="tumor_presence",
        l0_digest="abc123abc123abcd",
        ruleset_version="1.22.0",
        versions=rec["provenance"]["versions"],
    )
    assert rec["identity"] == recomputed


def test_attach_refuses_unresolved_or_missing_fingerprints():
    cards = [{"card_id": "x", "summary": {"method_version": "1.0"}}]
    with pytest.raises(ValueError):  # hgnc_id sentinel -> context.target invalid
        _attach_l2_claim_record(
            ep=_fake_ep(hgnc_id=-1),
            claim_record_fn=_fake_crf,
            emitted_cards=cards,
            fired=[],
            verdict_pair=None,
            indication="COADREAD",
            subgroup_spec=None,
            ruleset_version="1.22.0",
        )
    with pytest.raises(ValueError):  # no resolved_release_digest -> empty l0_digest
        _attach_l2_claim_record(
            ep={"context": {"target": {"symbol": "EPCAM", "hgnc_id": 11529}}, "governance": {}},
            claim_record_fn=_fake_crf,
            emitted_cards=cards,
            fired=[],
            verdict_pair=None,
            indication="COADREAD",
            subgroup_spec=None,
            ruleset_version="1.22.0",
        )
