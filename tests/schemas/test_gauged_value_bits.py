"""gauged_value.bits / bits_withheld — the salience layer's schema contract.

`bits` is the two-sided empirical surprise of a `cohort_percentile` ruler, in bits. It is the
label-free replacement for reading rank off a hand-set `priority:` rung, and it is DISPLAY-ONLY like
every other layer on this record. Three invariants are worth a schema (rather than a reader) because
every downstream consumer reads the record, not the producer:

  1. `bits` and `bits_withheld` are MUTUALLY EXCLUSIVE. Carrying both lets one reader take the number
     while another takes the refusal — which is exactly how a withheld measurement silently becomes a
     used one.
  2. A real `bits` requires a real `cohort_percentile` AND a real `cohort_n >= 1`. Without this,
     log2(n+1) computed against an empty column ships as a confident 0 indistinguishable from a
     genuinely median value.
  3. `bits` is non-negative. A surprise below zero is not a weaker claim, it is a broken one.

Every invariant is asserted in BOTH directions: the shipped example must PASS, and a crafted
violation must FAIL. A schema constraint nothing can violate is decoration.
"""

import copy
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "validators"))
import validate_evidence_graph as veg  # noqa: E402

SCHEMA = json.loads((REPO / "schemas" / "evidence_graph.schema.json").read_text())
EXAMPLE = json.loads((REPO / "schemas" / "examples" / "evidence_graph.example.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)


def _cohort_ruler(graph):
    """The (card_index, interpretation_index) of the shipped cohort_percentile ruler."""
    for ci, card in enumerate(graph.get("cards") or []):
        for ii, gv in enumerate((card.get("key_evidence") or {}).get("interpretation") or []):
            if (gv.get("frame") or {}).get("kind") == "cohort_percentile":
                return ci, ii
    pytest.fail("no cohort_percentile ruler in the shipped example — every test below would be vacuous")


def _mutated(**overrides):
    """The shipped example with the cohort ruler's keys overridden; a value of None DELETES the key."""
    g = copy.deepcopy(EXAMPLE)
    ci, ii = _cohort_ruler(g)
    gv = g["cards"][ci]["key_evidence"]["interpretation"][ii]
    for k, v in overrides.items():
        if v is _DELETE:
            gv.pop(k, None)
        else:
            gv[k] = v
    return g


_DELETE = object()


def _errors(graph):
    return [f"{'.'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in VALIDATOR.iter_errors(graph)]


# ── the positive control, FIRST ───────────────────────────────────────────────────────────────────


def test_shipped_example_carries_a_scored_cohort_ruler_and_validates():
    """Anti-vacuity before anything else: if the happy path did not validate, every rejection below
    would pass for the wrong reason."""
    assert not _errors(EXAMPLE), _errors(EXAMPLE)
    ci, ii = _cohort_ruler(EXAMPLE)
    gv = EXAMPLE["cards"][ci]["key_evidence"]["interpretation"][ii]
    assert isinstance(gv.get("bits"), (int, float)) and gv["bits"] > 0, "the example must SCORE, not withhold"
    # and through the validator the CI gate actually shells, not just the raw schema
    report = veg.validate_graph(EXAMPLE, path="evidence_graph.example.json")
    assert report.ok, report.errors


def test_a_withheld_ruler_is_equally_valid():
    """The refusal is a first-class record, not an error state: the percentile keeps rendering and only
    the rankable claim stops."""
    g = _mutated(bits=_DELETE, bits_withheld="reference_undermeasured_0.48")
    assert not _errors(g), _errors(g)


def test_a_ruler_with_neither_key_is_valid():
    """Both keys are additive. Every pre-salience ruler in the fleet, and every non-cohort frame, omits
    them — the schema must not make an unscored ruler retroactively invalid."""
    assert not _errors(_mutated(bits=_DELETE))


# ── invariant 1: a rank and the reason there is no rank cannot both be true ───────────────────────


def test_bits_and_bits_withheld_cannot_coexist():
    errs = _errors(_mutated(bits=2.308, bits_withheld="reference_undermeasured_0.48"))
    assert errs, "a record carrying BOTH a rank and a refusal was accepted"


# ── invariant 2: bits require the distribution they are a property of ────────────────────────────


@pytest.mark.parametrize(
    "override",
    [
        {"cohort_percentile": _DELETE},
        {"cohort_n": _DELETE},
        {"cohort_percentile": None},
        {"cohort_n": None},
        {"cohort_n": 0},
    ],
    ids=["no_percentile", "no_n", "null_percentile", "null_n", "empty_cohort"],
)
def test_bits_without_a_readable_cohort_are_rejected(override):
    """`cohort_n: 0` is the live failure mode: an absent atlas column returns an empty basis, and
    log2(0+1) == 0 bits reads as 'perfectly median' rather than 'never measured'."""
    errs = _errors(_mutated(**override))
    assert errs, f"bits survived {override!r} — the confident-zero-against-nothing case is admitted"


# ── invariant 3: a negative surprise is broken, not weak ─────────────────────────────────────────


def test_negative_bits_are_rejected():
    assert _errors(_mutated(bits=-0.5)), "negative bits accepted"


def test_zero_bits_are_accepted_because_median_is_a_real_answer():
    """The counterpart to the guard above, and the reason `minimum` is 0 rather than exclusive: an
    exactly-median value is worth no bits, which is a measurement and not a miss."""
    assert not _errors(_mutated(bits=0.0))


def test_bits_must_be_a_number_not_a_stringified_one():
    assert _errors(_mutated(bits="2.308")), "a stringified rank was accepted"
