"""Consumer-derived field contract — the CI-enforceable half.

The salience/verdict layer is the CONSUMER: for each field it reads, it declares an expected
type by the SPEC SLOT it places the field in (effect_field/extra_scalars → numeric,
categorical/label_field → string, strata_array → list). That slot placement IS the contract.

This gate enforces the part of the contract that needs NO emitted data (so it can never go
stale and never has to commit not-redistributable derived values): the declaration must be
INTERNALLY COHERENT — a field cannot be read as two different types across specs, because that
guarantees an unreadable emission on some card carrying both.

The EMISSION half of the contract (does the producer actually emit the declared type?) lives in
`skills/tools/field_conformance_audit.py`, which runs where the data is (a package cache). A
future CI emission gate (a committed field→type-name registry) is deferred until a clean
re-emit, so it is not built on deadlock-blanked packages.
"""

import sys
from collections import defaultdict
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1]  # skills/tools
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import field_conformance_audit as fca  # noqa: E402  (adds skills/ to path → _skills_common importable)
from _skills_common import evidence_salience as es  # noqa: E402


def _field_type_map():
    """field → set of type-categories it is read as across ALL salience specs."""
    byfield = defaultdict(set)
    for spec in es.SALIENCE_SPECS.values():
        buckets = fca.spec_fields(spec)
        for kind in ("numeric", "string", "array"):
            for field in buckets[kind]:
                byfield[field].add(kind)
    return byfield


def test_every_salience_read_field_has_one_consistent_type():
    """THE CONTRACT: a field the verdict layer reads resolves to exactly one expected type.
    A field read as numeric in one spec and string in another cannot be faithfully emitted for
    both — one consumer always gets nothing. Holds today (0 conflicts over 326 fields); this
    gate keeps it that way."""
    conflicts = {fld: sorted(kinds) for fld, kinds in _field_type_map().items() if len(kinds) > 1}
    assert not conflicts, (
        "salience-read fields with CONFLICTING expected types across specs "
        f"(each will be unreadable on some card): {conflicts}"
    )


def test_read_fields_are_well_formed():
    """No spec names an empty or non-string read field (a malformed contract entry)."""
    bad = [fld for fld in _field_type_map() if not isinstance(fld, str) or not fld.strip()]
    assert not bad, f"malformed read-field names in SALIENCE_SPECS: {bad!r}"


def test_audit_flags_a_planted_violation_end_to_end():
    """Smoke-test the emission enforcer end to end: a card emitting a bool where its spec reads a
    numeric extra_scalar (the real 'label/flag as number' defect class) must be caught."""
    # pick a real measurement_type whose spec reads a numeric extra_scalar
    mt = next((m for m, s in es.SALIENCE_SPECS.items() if fca.spec_fields(s)["numeric"]), None)
    assert mt, "expected at least one spec with a numeric read field"
    numfield = fca.spec_fields(es.SALIENCE_SPECS[mt])["numeric"][0]
    good = {numfield: 1.23}
    bad = {numfield: False}  # a flag where a number is read → reader gets nothing
    assert fca.classify_numeric(numfield, good, {}) == fca.OK
    assert fca.classify_numeric(numfield, bad, {}) == fca.WRONGTYPE
    # and absence/null must NOT be treated as a structural defect (that is coverage/0b)
    assert fca.classify_numeric(numfield, {}, {}) == fca.NA
    assert fca.classify_numeric(numfield, {numfield: None}, {}) == fca.NA
