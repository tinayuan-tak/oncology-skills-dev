"""PR-C2 skill-side consumption of the `underpowered` coverage-gap token.

`underpowered` (classifier looked but too few samples cleared the recurrence power floor) must read as
UNMEASURED, never as evidence. Two skill-side surfaces are exercised here — both PURE-python so they do
NOT depend on the (separately-landing) target-contracts resolver change, and so they stay green under the
frozen sibling-SHA pin that skills CI checks out:

  1. `_genomic_alteration_by_scope`'s inner `_measured()` — an underpowered raw class must NOT count as a
     measurement, else `evidence_present` falsely asserts "evidence exists at this scope" off an axis that
     could not be powered. This is the actual bite: `_ga_availability` / `_ga_direction` never see a raw
     class token, only the resolver VERDICT.
  2. The resolver maps an underpowered axis to the `insufficient` verdict (target-contracts PR-C2: CN joins
     the double-data-gap guard, fusion gets its own guard rung). This pins that `insufficient` — the token
     the verdict actually carries — buckets to unmeasured in `_ga_availability` / `_ga_direction` /
     `_genomic_strength`, so the end-to-end read is honest. (The resolver→verdict step itself is proven by
     the synthetic backtest run with TARGET_CONTRACTS_ROOT pointed at the PR branch; it is not a committed
     cross-repo test because the sibling pin would make it fail until bumped.)
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

gap = load_run_py(Path(__file__).resolve().parent.parent, "gap_run_underpowered")


def _card(cid, **fields):
    return {"card_id": cid, "summary": dict(fields)}


# ── 1. _measured: a coverage gap is not a measurement ────────────────────────────────────────────────


def test_measured_excludes_underpowered_like_data_unavailable():
    """`_measured` lives inside `_genomic_alteration_by_scope`; probe it through the reducer's public
    behaviour. An underpowered-ONLY axis at a scope must read evidence_present=False, identical to a
    data_unavailable-only axis and distinct from a measured class."""
    # underpowered CN + underpowered fusion, nothing else measured at the indication scope
    gapped = gap._genomic_alteration_by_scope(
        [
            _card("copy-number-distribution", copy_number_class="underpowered", patient_focal_cn_class="underpowered"),
            _card("fusion-rearrangement-landscape", fusion_class="underpowered"),
        ],
        driving_rule=None,
    )
    assert gapped["indication"]["evidence_present"] is False, (
        "an underpowered-only axis must NOT read as evidence at this scope"
    )
    assert gapped["pan_cancer"]["evidence_present"] is False

    # a REAL measured class at the same fields flips evidence_present back on (guards the exclusion from
    # over-reaching: only the two gap tokens are silenced, not every value).
    measured = gap._genomic_alteration_by_scope(
        [
            _card(
                "copy-number-distribution",
                copy_number_class="recurrently_amplified",
                patient_focal_cn_class="recurrent_focal_amplification",
            ),
            _card("fusion-rearrangement-landscape", fusion_class="recurrent_fusion_driver"),
        ],
        driving_rule=None,
    )
    assert measured["indication"]["evidence_present"] is True
    assert measured["pan_cancer"]["evidence_present"] is True

    # data_unavailable was already silenced; underpowered now reads IDENTICALLY (the parity this PR adds).
    du = gap._genomic_alteration_by_scope(
        [
            _card(
                "copy-number-distribution",
                copy_number_class="data_unavailable",
                patient_focal_cn_class="data_unavailable",
            ),
            _card("fusion-rearrangement-landscape", fusion_class="data_unavailable"),
        ],
        driving_rule=None,
    )
    assert du["indication"]["evidence_present"] is False
    assert du["pan_cancer"]["evidence_present"] is False


# ── 2. the verdict an underpowered axis earns (`insufficient`) buckets to unmeasured ─────────────────


def test_insufficient_verdict_reads_unmeasured_across_the_ga_surfaces():
    """The resolver routes an underpowered axis to `insufficient` (never a driver, never passenger). Pin
    that this verdict token reads unmeasured on every skill projection surface — the property that makes
    the resolver mapping honest end to end."""
    assert gap._ga_availability("insufficient") == "insufficient"
    assert gap._ga_direction("insufficient") == "neutral"
    assert gap._genomic_strength("insufficient") in ("none", "neutral"), (
        "insufficient must carry no directional strength"
    )
    # and it must NOT read as a positive driver on any of them
    assert gap._ga_availability("insufficient") not in ("measured_positive", "measured_negative")
    assert gap._ga_direction("insufficient") not in ("supports", "opposes")
