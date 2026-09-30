"""Which readers have opted into the finer evidence grades — asserted at the CALL SITES.

`panorama.evidence_state()` is additive: called with two positional arguments it returns the
historical `{measured, underpowered, absent}` trichotomy, and the two keyword arguments unlock
`exploratory` / `unevaluable`. That design means the set of readers emitting the wider vocabulary
is not visible in `panorama.py` at all — it is spread across eleven call sites in eight modules.

This module pins that set, because getting it wrong is silent in BOTH directions:

  * opting a reader in too early makes it emit a grade its card's RESTRICTIVE
    `outputs.summary_fields_record_schemas.<field>.evidence_state.enum` rejects — the producer
    emits a row its own contract refuses, and nothing in this repo validates against the card;
  * leaving one of the three by-subtype arms out makes the cards' declaration inert, i.e. a
    vocabulary declared but emitted 0x, which no test can see by reading the card alone.

Six cards still declare the narrow enum (subgroup-stratified-{copy-number,dependency,fusion,
mutation-frequency} + tumor-vs-normal-{percentile-crossing-by-subtype,selectivity}); three declare
the wider one as of contracts e21a8e8. 3 + 6 = 9 reconciles with the nine cards
`panorama.evidence_state`'s docstring names, so this partition is complete rather than a sample.

Structural (AST over the source) rather than behavioural on purpose: a behavioural test can only
exercise the substrates a fixture can reach, and five of these readers need live shards the others
do not. The keyword-argument list at a call site is the whole opt-in, so it is exactly the thing to
assert. The per-file counts are the anti-vacuity control — if a call site is moved, renamed or
deleted the count stops matching and this fails loudly instead of passing over an empty search.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

_CALLEE_NAMES = {"evidence_state", "_evstate"}

# The three by-subtype arms of the tumor-presence stack. Their cards declare
# {measured, exploratory, underpowered, unevaluable, absent}, so they may pass the kwargs.
_ARM_SITES: dict[str, int] = {
    # 3 sites (AM#2180 F1): the computed-n final return + TWO constant-n=0 templates — the
    # membership-missing `empty` template (evaluated=_stratum_evaluated) and the detection-missing
    # branch (a populated stratum with every value below-LOD/non-finite, forced evaluated=False so it
    # abstains as `unevaluable` rather than grading a measured `absent`). Both n=0 sites opt in via
    # `evaluated=`, and `unevaluable` is already in this card's enum.
    "onc_methods/cptac_protein_distribution/read.py": 3,
    "onc_methods/depmap_expression_distribution/read.py": 1,
    "onc_methods/tcga_gtex_expression_distribution/read.py": 2,
}

# Every OTHER production call site. Their cards still declare the narrow trichotomy, so these must
# stay two-positional-arguments-only. Do not "tidy" these into the arm set to make things uniform:
# widening one requires its card to be widened FIRST, in target-contracts, in its own PR.
_NARROW_ENUM_SITES: dict[str, int] = {
    "onc_methods/depmap_chronos/read.py": 1,
    "onc_methods/dge_deseq2/read/__init__.py": 1,
    "onc_methods/gdc_somatic_hotspot/read.py": 1,
    "onc_methods/tcga_fusion_consensus/stratified.py": 1,
    "onc_methods/tcga_patient_cn/stratified.py": 1,
}

_ALLOWED_KWARGS = {"evaluated", "exploratory_floor"}


def _call_sites(rel: str) -> list[ast.Call]:
    path = REPO / rel
    assert path.is_file(), f"{rel} has moved — this guard's file list is stale, not satisfied"
    tree = ast.parse(path.read_text())
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        # Only bare-name calls; `panorama.evidence_state(...)` would be an Attribute and no
        # production site uses that form today. Deliberately NOT widened to Attribute: a new
        # dotted call site should trip the count assertion and be reviewed, not silently absorbed.
        if isinstance(fn, ast.Name) and fn.id in _CALLEE_NAMES:
            out.append(node)
    return out


@pytest.mark.parametrize("rel,expected", sorted(_NARROW_ENUM_SITES.items()))
def test_narrow_enum_readers_pass_no_grade_kwargs(rel: str, expected: int):
    """A reader whose card declares only {measured, underpowered, absent} must not opt in."""
    calls = _call_sites(rel)
    assert len(calls) == expected, (
        f"{rel}: expected {expected} evidence_state call site(s), found {len(calls)}. "
        f"Re-derive the partition in this module's docstring rather than adjusting the count."
    )
    for c in calls:
        kwargs = sorted(k.arg for k in c.keywords)
        assert kwargs == [], (
            f"{rel}:{c.lineno} passes {kwargs} to evidence_state, but this reader feeds a card that "
            f"still declares the NARROW evidence_state enum. Widen the card in target-contracts "
            f"first; emitting `exploratory`/`unevaluable` here makes the producer violate its own "
            f"record schema, and nothing in this repo would catch it."
        )


@pytest.mark.parametrize("rel,expected", sorted(_ARM_SITES.items()))
def test_by_subtype_arms_have_opted_in(rel: str, expected: int):
    """Each by-subtype arm passes at least `exploratory_floor=`, so the cards are not inert."""
    calls = _call_sites(rel)
    assert len(calls) == expected, f"{rel}: expected {expected} call site(s), found {len(calls)}"
    for c in calls:
        kwargs = {k.arg for k in c.keywords}
        assert kwargs, f"{rel}:{c.lineno} has not opted in; the card's wider enum would be inert"
        unknown = kwargs - _ALLOWED_KWARGS
        assert not unknown, f"{rel}:{c.lineno} passes unexpected kwarg(s) {sorted(unknown)}"


def _n_is_constant_zero(call: ast.Call) -> bool:
    """True when the site hardcodes subgroup_n=0 (a known-empty-stratum template)."""
    return bool(call.args) and isinstance(call.args[0], ast.Constant) and call.args[0].value == 0


def test_exploratory_band_is_enabled_on_every_arm_site_that_can_reach_it():
    """`exploratory_floor=` must be passed wherever the 10-29 band is REACHABLE.

    Reachability is the qualifier, and it is not decoration: a site that passes a literal `0` for
    `subgroup_n` (CPTAC's known-empty-stratum template) can only ever take evidence_state's
    `subgroup_n == 0` branch, so `exploratory_floor` there would be an inert argument — the same
    never-varies defect this module guards against in the other direction. Every site with a
    computed n must pass it, or that arm's `exploratory` declaration is inert.
    """
    checked = 0
    for rel in _ARM_SITES:
        for c in _call_sites(rel):
            if _n_is_constant_zero(c):
                # Sanity: such a site must not claim the band either.
                assert "exploratory_floor" not in {k.arg for k in c.keywords}, (
                    f"{rel}:{c.lineno} passes exploratory_floor with a hardcoded subgroup_n=0"
                )
                continue
            assert "exploratory_floor" in {k.arg for k in c.keywords}, (
                f"{rel}:{c.lineno} omits exploratory_floor on a computed-n site"
            )
            checked += 1
    # Anti-vacuity: if every arm site were a constant-zero template the loop above would assert
    # nothing. Four of the five arm sites compute n.
    assert checked == 4, f"expected 4 computed-n arm sites, checked {checked}"


def test_tumor_arm_does_not_pass_evaluated():
    """The tumor arm's `unevaluable` is UNREACHABLE by construction, so passing the flag would be
    a field that never varies.

    `tcga_gtex_expression_distribution` derives its strata from `is_member == True` rows, so every
    stratum it loops over has >=1 CLASSIFIED member and `stratum_evaluability(...).evaluated` is
    necessarily True. The DepMap/CPTAC arms differ because they are handed `subgroups` by the
    CALLER and can be asked about a stratum nobody was ever assigned to.

    If the stratum enumeration is ever changed to include strata absent from the is_member==True
    set, this test SHOULD fail: delete it in the same commit and pass `evaluated=` at both sites.
    """
    rel = "onc_methods/tcga_gtex_expression_distribution/read.py"
    for c in _call_sites(rel):
        assert "evaluated" not in {k.arg for k in c.keywords}, (
            f"{rel}:{c.lineno} passes evaluated=, but this arm enumerates strata from "
            f"is_member==True rows, so the flag is constant True. See the docstring."
        )


def test_unevaluable_is_reachable_from_at_least_one_arm():
    """Anti-vacuity for the pair above: SOME arm must pass `evaluated=`.

    Without this, a refactor that dropped the kwarg everywhere would leave
    `test_tumor_arm_does_not_pass_evaluated` passing while `unevaluable` — declared in all three
    cards — became unreachable across the whole repo.
    """
    opted = {rel for rel in _ARM_SITES for c in _call_sites(rel) if "evaluated" in {k.arg for k in c.keywords}}
    assert opted, "no arm passes evaluated=; `unevaluable` is declared in 3 cards but emitted 0x"
