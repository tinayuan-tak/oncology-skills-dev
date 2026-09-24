"""Gate on `presence_cardboard_figure._bucket` — the function that turns a card summary value into a
coloured glyph. It is the last hop before a human reads the card board, and it used to guess.

WHAT THIS GATE PROVES, and it is deliberately structural: for every value the target-contracts card
vocabulary declares, the mapping is TOTAL (no value falls through), EXACT (a value cannot borrow the
polarity of a token it merely contains), UNAMBIGUOUS (no value is claimed by two polarity sets), and
PER-CARD NON-DEGENERATE (a card whose every value renders identically is a decorative column).

WHAT IT DOES NOT PROVE: that a given polarity is semantically right — that `tumor_intrinsic` is
favourable and `microenvironment_confounded` is not. Contracts declares vocabularies as plain string
lists with no polarity metadata, so nothing here can derive it; asserting it from a literal in this
file would just build a second private mirror of the vocabulary, which is the failure this repo has
already settled elsewhere. Polarity is a code-review question and the reasoning is recorded inline
beside each set in the module.

WHY THE OBVIOUS VERSION OF THIS GATE IS NOT ENOUGH. "Every declared value lands in one of
_SIGNAL/_NO_SIGNAL" passes both defects that motivated the file:
  * `tumor_intrinsic` IS in _SIGNAL and still rendered no_signal, because _NO_SIGNAL was tested
    first and its last entry is the 2-character token `ns`, inside tumor_intri-ns-ic. 17 packages.
  * `sc-normal-celltype-expression` had ALL FOUR of its values land in the enumerated `liability`
    bucket with zero fall-through — because the comparator cascade never lowercased and that card
    declares UPPERCASE — so clean_window was unreachable for it and the column was constant on
    504/504 corpus packages.
Hence: exactness is checked behaviourally (affix a value, it must go unknown), and degeneracy is
checked per card.

READS CONTRACTS, NOT A LITERAL. Same env var and default as test_card_output_emission.py, and like
that module it ASSERTS the checkout is present rather than skipping — a cross-repo test that skips
when the sibling is missing is a test that passes for the wrong reason.

MUTATION-TESTED: restoring substring matching reds the exactness test AND the inversion pin;
restoring the comparator cascade reds the degeneracy test for sc-normal-celltype-expression;
restoring any terminal polarity default reds the per-role unknown test.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from _skills_common.presence_cardboard_figure import (
    _COMPARATOR_CLEAN,
    _COMPARATOR_LIABILITY,
    _GLYPH,
    _NO_SIGNAL,
    _NOT_MEASURED,
    _RELIABILITY,
    _SIGNAL,
    _SPEC,
    _bucket,
    _subtype_axis_gated_bucket,
)

_CONTRACTS = Path(
    os.environ.get(
        "TARGET_CONTRACTS_ROOT",
        "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts",
    )
)
_CARDS_DIR = _CONTRACTS / "cards"

# _bucket's FIRST guard catches these before any vocabulary is consulted, so they are not evidence
# that the vocabulary covers anything. They MUST be excluded from the degeneracy check: every card
# declares data_unavailable, so counting it would hand every card a second bucket for free and the
# check would pass vacuously on exactly the constant column it exists to catch.
_GUARD_HANDLED = frozenset({"data_unavailable", ""})

# Cards whose primary field _SPEC registers but whose contracts vocabulary block OMITS it. This is a
# DECLARATION GAP, not an undeclared card: the block exists and holds other fields. A card with no
# block at all could be skipped with a clear conscience; a block that omits a field _SPEC actively
# registers is the card most likely to be wrong, so the skip is pinned by identity here and asserted
# below — it cannot grow, and it cannot silently shrink once contracts fixes it either.
_DECLARATION_GAPS = {
    "tumor-rna-distribution-by-subtype": "subtype_stratification_class",
}

_POLARITY_SETS = {
    "signal": {"_SIGNAL": _SIGNAL, "_NO_SIGNAL": _NO_SIGNAL, "_NOT_MEASURED": _NOT_MEASURED},
    "comparator": {
        "_COMPARATOR_LIABILITY": _COMPARATOR_LIABILITY,
        "_COMPARATOR_CLEAN": _COMPARATOR_CLEAN,
        "_NOT_MEASURED": _NOT_MEASURED,
    },
    "reliability": {"_RELIABILITY": frozenset(_RELIABILITY), "_NOT_MEASURED": _NOT_MEASURED},
}


def _declared():
    """[(card_id, field, role, values)] for _SPEC cards with a declared vocabulary, plus the gaps."""
    declared, gaps = [], {}
    for cid, _claim, field, role in _SPEC:
        path = _CARDS_DIR / f"{cid}.card.yaml"
        if not path.is_file():
            gaps[cid] = field
            continue
        outputs = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("outputs") or {}
        vocab = outputs.get("summary_fields_vocabulary") or {}
        if field not in vocab:
            gaps[cid] = field
            continue
        declared.append((cid, field, role, [v for v in list(vocab[field]) if isinstance(v, str)]))
    return declared, gaps


_DECLARED, _GAPS = _declared()
_IDS = [f"{cid}:{field}" for cid, field, _role, _values in _DECLARED]


def test_the_gate_reads_a_live_contracts_checkout():
    """Non-vacuity anchor. Everything below is quantified over the contracts vocabulary, so if the
    checkout is missing every other test here passes over an empty set."""
    assert _CARDS_DIR.is_dir(), f"target-contracts cards dir not found: {_CARDS_DIR}"
    assert len(_DECLARED) >= 11, (
        f"only {len(_DECLARED)} of {len(_SPEC)} registered cards yielded a declared vocabulary — "
        f"the contracts checkout is stale or the card layout moved. gaps={_GAPS}"
    )
    total_values = sum(len(v) for _c, _f, _r, v in _DECLARED)
    assert total_values >= 55, f"expected >=55 declared values across the board, read {total_values}"


def test_the_declaration_gap_list_is_exact():
    """The skip list is pinned by IDENTITY, both directions. A NEW gap must fail loudly rather than
    quietly shrinking this gate's coverage; and once target-contracts declares the missing field,
    this must also fail, so the stale exemption gets deleted instead of outliving its reason."""
    assert _GAPS == _DECLARATION_GAPS, (
        f"declaration gaps moved.\n  measured: {_GAPS}\n  pinned:   {_DECLARATION_GAPS}\n"
        "If a gap closed, delete it from _DECLARATION_GAPS. If a new one opened, either declare the "
        "field in target-contracts or record it here with the reason."
    )


@pytest.mark.parametrize("cid,field,role,values", _DECLARED, ids=_IDS)
def test_every_declared_value_maps_to_an_enumerated_bucket(cid, field, role, values):
    """TOTALITY. `unknown` must be unreachable for anything contracts declares — that is what makes
    it safe for `unknown` to be the terminal default instead of a polarity."""
    unmapped = [v for v in values if _bucket(v, role) == "unknown"]
    assert not unmapped, (
        f"{cid}.{field} ({role}): declared values with no bucket: {sorted(unmapped)}. "
        "Add each to the polarity set that matches its meaning in presence_cardboard_figure.py."
    )


@pytest.mark.parametrize("cid,field,role,values", _DECLARED, ids=_IDS)
def test_matching_is_exact_and_not_substring(cid, field, role, values):
    """EXACTNESS, checked through the function rather than by reading it. A value that merely
    CONTAINS a declared token must not inherit its bucket. This is the test that catches the class of
    bug `ns` was: under substring matching, affixing a declared token leaves the bucket unchanged."""
    leaked = []
    for v in values:
        if v in _GUARD_HANDLED:
            continue
        for probe in (f"zz{v}", f"{v}zz"):
            got = _bucket(probe, role)
            if got != "unknown":
                leaked.append((probe, got))
    assert not leaked, (
        f"{cid}.{field} ({role}): matching is not exact — these non-vocabulary strings were bucketed: "
        f"{leaked}. A substring/prefix test somewhere is letting a value borrow another's polarity."
    )


@pytest.mark.parametrize("cid,field,role,values", _DECLARED, ids=_IDS)
def test_no_declared_value_is_claimed_by_two_polarity_sets(cid, field, role, values):
    """UNAMBIGUITY. If a value sits in two sets, its bucket is decided by test ORDER inside _bucket,
    which is exactly how an exact _SIGNAL member came to render as a measured negative."""
    collisions = {}
    for v in values:
        owners = [name for name, members in _POLARITY_SETS[role].items() if v in members]
        if len(owners) > 1:
            collisions[v] = owners
    assert not collisions, f"{cid}.{field} ({role}): values claimed by multiple polarity sets: {collisions}"


@pytest.mark.parametrize("cid,field,role,values", _DECLARED, ids=_IDS)
def test_no_card_renders_a_constant_column(cid, field, role, values):
    """NON-DEGENERACY. A column whose every declared value renders identically carries zero bits
    while looking like a measurement. sc-normal-celltype-expression was exactly this: four declared
    values, all liability, clean_window unreachable, constant across all 504 corpus packages.

    data_unavailable is excluded on purpose — it is handled by _bucket's first guard and every card
    declares it, so including it would give every card a free second bucket and make this vacuous."""
    meaningful = [v for v in values if v not in _GUARD_HANDLED]
    buckets = {_bucket(v, role) for v in meaningful}
    assert len(buckets) >= 2, (
        f"{cid}.{field} ({role}) is a CONSTANT column: all {len(meaningful)} declared values render "
        f"{buckets}. Either the polarity map collapses them or the card's vocabulary is not "
        "discriminative; a constant glyph column should not be drawn as if it were a reading."
    )


@pytest.mark.parametrize("role", sorted(_POLARITY_SETS))
def test_unknown_is_the_terminal_default_for_every_role(role):
    """PER-ROLE default direction. _bucket holds three independent lookups; each previously ended in
    its OWN polarity — signal to signal (favourable), reliability to proxy_partial (middling),
    comparator to liability (alarming) — so an unrecognised token asserted something different
    depending on which column it landed in. A gate written for one role would have gone green on the
    fixed cascade and stayed blind on the other two."""
    got = _bucket("a_token_no_contract_declares", role)
    assert got == "unknown", (
        f"role {role!r} still has a polarity default: an undeclared token rendered {got!r}. "
        "An unrecognised value must assert nothing, in every role."
    )


def test_the_coverage_gap_tokens_are_not_rendered_as_measured():
    """The module's stated honesty rule, pinned on the two tokens that broke it. `no_signal` means
    we looked and found nothing; `not_measured` means we could not look. These two say the second in
    plain language and were rendered as the first (on 40 packages) and as a middling measured proxy
    quality (proxy_partial) respectively."""
    assert _bucket("insufficient_paired_samples", "signal") == "not_measured"
    assert _bucket("insufficient_paired_tumors", "reliability") == "not_measured"


def test_the_inversion_that_motivated_this_gate_stays_fixed():
    """Regression pin on the single measured inversion: an EXACT _SIGNAL member that rendered as a
    measured negative. Kept as its own named test so a future reader sees the concrete case, not
    only the general rule."""
    assert "tumor_intrinsic" in _SIGNAL
    assert _bucket("tumor_intrinsic", "signal") == "signal", (
        "tumor_intrinsic is declared favourable and must render as a signal; it rendered no_signal "
        "for as long as _NO_SIGNAL was substring-tested first and contained the 2-char token 'ns'."
    )
    # 'ns' itself is a DECLARED legacy key (tumor-presence/run.py:884-893 maps it exactly) and must
    # keep working as a measured negative — the fix was exactness, not deleting the token.
    assert _bucket("ns", "signal") == "no_signal"


def test_every_reachable_bucket_has_a_glyph():
    """A bucket name with no _GLYPH entry renders as the inline ? fallback — i.e. a typo in a bucket
    string would look exactly like an unrecognised vocabulary value. Enumerate what is reachable."""
    reachable = {"unknown"}
    for _cid, _field, role, values in _DECLARED:
        reachable |= {_bucket(v, role) for v in values}
    missing = sorted(reachable - set(_GLYPH))
    assert not missing, f"buckets reachable from the declared vocabulary with no _GLYPH entry: {missing}"


def test_the_undeclared_subtype_vocabulary_is_covered():
    """tumor-rna-distribution-by-subtype is the ONE registered card whose primary field target-contracts
    declares no vocabulary for (see _DECLARATION_GAPS), so every parametrized test above skips it — and
    it was the LARGEST instance of the defect: subtype_axis_unavailable rendered ● favourable on 199 of
    504 corpus packages, on exactly the packages that had no subtype axis to read. A field nothing
    declares is the field most likely to fall through, which is the opposite of where a vocabulary-
    driven gate naturally looks, so these are pinned by name.

    Polarities are sourced, not inferred. Two NEIGHBOURING tokens are deliberately excluded:
    subtype_depleted is a value of the `subtype_signal` field and no_subtype_signal is the
    target-profile subtype facet's `verdict`. Adopting either here would make this module a second
    home for another field's vocabulary — the drift this repo has already paid for once."""
    # Coverage gaps. tp_facets_subtype.py:268 states this polarity in as many words: "no shard for
    # this indication (coverage gap), not a measured negative". presence_question_table.py:193 groups
    # both tokens with data_unavailable for this same field.
    assert _bucket("subtype_axis_unavailable", "signal") == "not_measured"
    assert _bucket("no_subtype_axis", "signal") == "not_measured"
    # Positive selection signals: presence_question_table.py:201 groups these with the enriched /
    # restricted values that were already mapped favourable.
    assert _bucket("subtype_restricted_with_window", "signal") == "signal"
    assert _bucket("subtype_differential", "signal") == "signal"
    # Tokens belonging to OTHER fields must stay unknown rather than be silently adopted. This pin is
    # falsifiable in the useful direction: if a producer really starts emitting one of these for
    # subtype_stratification_class, this reds and the fix is to add it WITH a source and drop it here.
    for foreign in ("subtype_depleted", "no_subtype_signal"):
        assert _bucket(foreign, "signal") == "unknown", (
            f"{foreign} is not a subtype_stratification_class value in this tree; it must not inherit "
            "a polarity from a field this module does not render"
        )


def test_exploratory_axis_differential_class_renders_not_measured_not_signal():
    """SK#1518. `subtype_stratification_class` is derived from the MEASURED strata alone, so a single
    measured-enriched stratum in an `exploratory` (or weaker) family yields a differential class while
    `subtype_axis_quality` says the axis is not powered. `_bucket` alone would render that favourable ●
    (the class IS a declared SIGNAL member); the axis-quality gate must route it to ▨ (a coverage/power
    gap, not a measured negative ○). Only a `powered` axis keeps the differential signal. Verdict-inert."""
    cid = "tumor-rna-distribution-by-subtype"
    for cls in ("subtype_enriched", "subtype_restricted", "subtype_differential", "subtype_restricted_with_window"):
        assert _bucket(cls, "signal") == "signal", "the class itself is still a declared signal member"
        # powered: the differential stands.
        assert _subtype_axis_gated_bucket(cid, {"subtype_axis_quality": "powered"}, cls, "signal") == "signal"
        # every non-powered grade (and None): downgraded to a coverage/power gap, never ● favourable.
        for grade in ("exploratory", "underpowered", "unevaluable", "empty", "unavailable", None):
            assert _subtype_axis_gated_bucket(cid, {"subtype_axis_quality": grade}, cls, "signal") == "not_measured", (
                f"{cls} on a {grade} axis must not render as a favourable signal"
            )
    # a non-differential class (uniform) is untouched by the gate; other cards are never affected.
    assert (
        _subtype_axis_gated_bucket(cid, {"subtype_axis_quality": "exploratory"}, "pan_subtype_uniform", "signal")
        == "signal"
    )
    assert _subtype_axis_gated_bucket("tumor-rna-distribution", {}, "broadly_high", "signal") == "signal"
