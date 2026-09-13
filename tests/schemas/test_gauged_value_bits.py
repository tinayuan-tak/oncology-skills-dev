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


# ── cohort_scope: the cohort a percentile was drawn from ─────────────────────────────────────────


def test_cohort_scope_is_additive_and_optional():
    """Every pre-scoping cohort ruler in the fleet omits cohort_scope; adding the key must not make an
    existing pan-cancer ruler retroactively invalid, and a reader treats a missing scope as pan_cancer.
    This is the property that lets the skills reader ship cohort_scope without a lockstep re-emit of
    every already-frozen gauge."""
    assert not _errors(_mutated(cohort_scope=_DELETE)), _errors(_mutated(cohort_scope=_DELETE))
    assert not _errors(_mutated(cohort_scope="pan_cancer")), _errors(_mutated(cohort_scope="pan_cancer"))


def test_a_scored_ruler_can_name_an_indication_scope():
    """The step-3 shape: an indication-scoped percentile still scores, now with an auditable scope, so a
    reader can tell an indication percentile from the pan-cancer fallback wearing the same number."""
    g = _mutated(cohort_scope="COADREAD")  # the shipped ruler already carries bits + cohort_percentile + cohort_n
    assert not _errors(g), _errors(g)


def test_cohort_scope_must_be_a_string():
    """The scope names a cohort; a number is a category error. A schema that accepted it would let a
    cohort index leak in where a code belongs."""
    assert _errors(_mutated(cohort_scope=42)), "a numeric cohort_scope was accepted"


# ── tier_rarity: an ordinal ladder placed as its cohort rarity ───────────────────────────────────


def _tier_rarity_frame():
    """A minimal ordered ladder: the tiers ride in anchors as role=tier, value=index."""
    return {
        "kind": "tier_rarity",
        "anchors": [
            {"role": "tier", "label": "none", "value": 0},
            {"role": "tier", "label": "moderate", "value": 1},
            {"role": "tier", "label": "strong", "value": 2},
        ],
    }


def test_a_tier_rarity_gauge_validates_and_reuses_the_cohort_triplet():
    """The step-4 shape: an ordinal-only axis (no continuous numeric to percentile) scored by cohort
    rarity. It reuses cohort_percentile / cohort_n / bits under the new frame.kind, so the bits
    machinery and its invariants apply unchanged — the value is the tier index, cohort_percentile the
    fraction of the cohort at a tier at-or-beyond this one."""
    g = _mutated(
        frame=_tier_rarity_frame(),
        scale="ordinal_tier",
        value=2,
        cohort_percentile=92,
        cohort_n=213,
        bits=2.1,
        cohort_scope="pan_cancer",
    )
    assert not _errors(g), _errors(g)


def test_tier_rarity_bits_still_require_the_cohort_basis():
    """The reuse must not weaken invariant 2: a tier_rarity bits with no cohort_n is the same
    confident-zero-against-nothing failure the continuous frame has, and the existing allOf — which is
    frame-agnostic — must still catch it. If this passed, reusing the triplet would have opened a hole."""
    g = _mutated(
        frame=_tier_rarity_frame(),
        scale="ordinal_tier",
        value=2,
        cohort_percentile=92,
        cohort_n=_DELETE,
        bits=2.1,
    )
    assert _errors(g), "tier_rarity bits survived a missing cohort_n — the reuse opened a confident-zero hole"


def test_an_unknown_frame_kind_is_still_rejected():
    """Anti-vacuity for adding tier_rarity to the enum: proves the enum is a real gate. Otherwise
    'tier_rarity validates' would be true of any string and this PR would have declared nothing."""
    g = _mutated(frame={"kind": "tier_scarcity_typo", "anchors": []})
    assert _errors(g), "an off-enum frame.kind was accepted — the enum is not gating"
