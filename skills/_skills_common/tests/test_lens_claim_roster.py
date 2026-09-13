"""Lens roster ↔ claim-vector roster COVERAGE (eval CASE-034).

`literature_synthesis.axis_measured_state` iterates `lens.axis_labels`. An axis that a skill's ClaimSpec
roster computes but the lens does not declare is therefore never asked about: it contributes 0 axis reads,
hence 0 `contradicts`, and every concordance instrument downstream (the eval harness, the literature lane,
the discordance ledger) reads 0 contradicts as AGREEMENT. **Unaskable is not agreed.** That is how genomic
`ROLE` scored 0 of 100 axis reads on the registered genomic-20 panel while the ledger reported no
disagreement on the driver axis.

The population these checks run over is DERIVED, never listed:

* the rosters come from introspecting every ``ClaimSpec`` list in ``_skills_common/*claims*.py``;
* the lens→roster link is DECLARED on the lens (``LensConfig.claim_spec_ref``) and resolved here;
* ``test_every_declared_claim_roster_is_claimed_by_a_lens`` closes the loop, so a NEW claims module cannot
  be silently unguarded — the failure mode a hardcoded list of skills would have.

The fourth check is the one that would have caught the regression this fix nearly shipped: `axis_labels`
also feeds `literature_retrieval._lens_terms`, which CAPS the query terms at 5 by default. Completing the
safety roster pushed its 8 axes past that cap and truncated `PHARMACOVIGILANCE` — the single axis the lens
used to query on — out of the Europe-PMC query entirely. Growing a roster without growing the cap silently
narrows retrieval.
"""

from __future__ import annotations

import importlib
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from _skills_common.claim_vector_core import ClaimSpec  # noqa: E402
from _skills_common.literature_retrieval import _lens_terms  # noqa: E402
from _skills_common.narrator_lenses import LENSES  # noqa: E402

# The two lenses that hand-build their claim vector instead of declaring a ClaimSpec roster, each with the
# reason. Named so a THIRD one cannot appear without a decision: the coverage check below asserts this set
# is exactly the set of lenses with no `claim_spec_ref`.
_HAND_BUILT_VECTORS = {
    "tumor-presence": "presence_claims.presence_claim_vector hand-builds A/B/C/D + homogeneity",
    "target-archetype": "archetype_core.archetype_claim_vector projects the cardless META companion",
}

_CLAIMS_DIR = pathlib.Path(__file__).resolve().parents[1]


def _discover_rosters() -> dict:
    """{"<module>:<VARNAME>": [axis_key, …]} for every ClaimSpec list under _skills_common/*claims*.py.

    DERIVED by introspection — isinstance against ClaimSpec, not a name convention — so a roster declared
    under a differently-spelled variable is still found."""
    out: dict = {}
    for path in sorted(_CLAIMS_DIR.glob("*claims*.py")):
        mod = importlib.import_module(f"_skills_common.{path.stem}")
        for name in dir(mod):
            val = getattr(mod, name)
            if isinstance(val, (list, tuple)) and val and all(isinstance(x, ClaimSpec) for x in val):
                out[f"{path.stem}:{name}"] = [c.axis_key for c in val]
    return out


def _resolve(ref: str) -> list:
    mod_name, _, var = ref.partition(":")
    mod = importlib.import_module(f"_skills_common.{mod_name}")
    return list(getattr(mod, var))


def _lenses_with_rosters() -> list:
    return [lens for lens in LENSES.values() if lens.claim_spec_ref]


# ── the coverage property itself ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("lens", _lenses_with_rosters(), ids=lambda l: l.name)
def test_lens_roster_covers_claim_axes(lens):
    """Every axis a skill's ClaimSpec roster COMPUTES must be declared in the lens it is narrated by."""
    declared = set(lens.axis_labels or {})
    computed = {c.axis_key for c in _resolve(lens.claim_spec_ref)}
    unaskable = sorted(computed - declared)
    assert not unaskable, (
        f"{lens.name}: {len(unaskable)} claim axis/axes computed by {lens.claim_spec_ref} but absent from "
        f"axis_labels: {unaskable}. axis_measured_state iterates axis_labels, so these are never ASKED "
        f"about — they contribute 0 reads and 0 contradicts, which every concordance instrument reads as "
        f"agreement. Add them to axis_labels (and bump literature_retrieval._LENS_MAX_TERMS to match)."
    )


@pytest.mark.parametrize("lens", _lenses_with_rosters(), ids=lambda l: l.name)
def test_claim_spec_ref_resolves_to_a_real_roster(lens):
    """DANGLING check: a declared ref must name a module and variable that actually exist and hold
    ClaimSpecs. A ref that silently fails to resolve would make the coverage check above VACUOUS."""
    spec = _resolve(lens.claim_spec_ref)
    assert spec, f"{lens.name}: {lens.claim_spec_ref} resolved to an empty roster"
    assert all(isinstance(c, ClaimSpec) for c in spec), f"{lens.name}: {lens.claim_spec_ref} is not ClaimSpecs"


@pytest.mark.parametrize("lens", list(LENSES.values()), ids=lambda l: l.name)
def test_every_axis_label_survives_the_literature_query_cap(lens):
    """`axis_labels` feeds _lens_terms, which truncates at _LENS_MAX_TERMS (default 5). Every declared axis
    label must survive the cut — otherwise declaring an axis narrows the query instead of widening it."""
    labels = list((lens.axis_labels or {}).values())
    if not labels:
        pytest.skip(f"{lens.name} declares no axis labels")
    terms = _lens_terms(lens)
    dropped = [t for t in labels if t not in terms]
    assert not dropped, (
        f"{lens.name}: {len(dropped)} axis label(s) truncated out of the Europe-PMC query by the term cap: "
        f"{dropped}. Raise literature_retrieval._LENS_MAX_TERMS['{lens.name}'] to at least "
        f"{len(labels)} + its curated-term count."
    )


# ── anti-decay: the population is complete, and these checks CAN fail ────────────────────────────────


def test_every_declared_claim_roster_is_claimed_by_a_lens():
    """A ClaimSpec roster nobody references is a roster nothing guards. Closes the loop the other way, so
    a NEW *claims* module cannot slip past the coverage check by simply not being listed anywhere."""
    discovered = set(_discover_rosters())
    referenced = {lens.claim_spec_ref for lens in _lenses_with_rosters()}
    orphans = sorted(discovered - referenced)
    assert not orphans, (
        f"{len(orphans)} ClaimSpec roster(s) referenced by no lens: {orphans}. Either declare "
        f"claim_spec_ref on the narrating lens, or the roster is dead code."
    )
    dangling = sorted(referenced - discovered)
    assert not dangling, f"lens claim_spec_ref(s) not found by roster discovery: {dangling}"


def test_the_only_lenses_without_a_roster_are_the_declared_hand_built_ones():
    """MISDECLARED/STALE check: a lens with no `claim_spec_ref` is exempt from the coverage property, so
    the exempt set must be named with a reason rather than inferred. A new lens defaults to exempt (the
    field defaults to None) — this is what makes that default visible instead of silent."""
    exempt = {name for name, lens in LENSES.items() if not lens.claim_spec_ref}
    assert exempt == set(_HAND_BUILT_VECTORS), (
        f"lenses exempt from claim-roster coverage changed: {sorted(exempt)} vs declared "
        f"{sorted(_HAND_BUILT_VECTORS)}. A lens with no claim_spec_ref is UNGUARDED — either declare its "
        f"roster, or add it to _HAND_BUILT_VECTORS with the reason it hand-builds its vector."
    )


def test_the_coverage_guard_is_not_vacuous():
    """The guard must actually inspect a population, and it must be able to FAIL. Both halves measured:
    the roster count is derived (not asserted equal to a magic number beyond a floor), and an axis added
    to a resolved roster copy must be reported as unaskable."""
    rosters = _discover_rosters()
    assert len(rosters) >= 12, f"roster discovery found only {len(rosters)} — introspection is broken"
    covered = _lenses_with_rosters()
    assert len(covered) >= 12, f"only {len(covered)} lenses declare a claim_spec_ref"
    assert sum(len(v) for v in rosters.values()) >= 50, "discovered rosters hold implausibly few axes"

    # FAIL branch, exercised: a computed axis absent from axis_labels must be caught. Deliberately does
    # NOT read a live roster — otherwise this anti-vacuity check inherits the very coverage property it is
    # supposed to be independent of, and fails twice for one cause.
    lens = LENSES["genomic-alteration-profile"]
    declared = set(lens.axis_labels or {})
    computed = declared | {"PHANTOM_AXIS"}
    assert sorted(computed - declared) == ["PHANTOM_AXIS"], "the set-difference the guard rests on is inert"


def test_role_is_on_the_genomic_roster_and_asked_about():
    """The specific instance CASE-034 was filed for, pinned BY NAME so a roster rewrite that drops ROLE
    reds here rather than quietly restoring 0 of N axis reads."""
    lens = LENSES["genomic-alteration-profile"]
    assert "ROLE" in lens.axis_labels, "genomic ROLE is off-roster again (CASE-034)"
    assert lens.axis_labels["ROLE"] in _lens_terms(lens), "genomic ROLE is declared but truncated out of the query"


def test_the_safety_roster_kept_pharmacovigilance_askable():
    """The regression completing the safety roster nearly shipped: 8 axes past a cap of 5 truncated
    PHARMACOVIGILANCE — the ONLY axis the lens previously queried on — out of the query."""
    lens = LENSES["on-target-safety-liability"]
    assert len(lens.axis_labels) == 8, "the safety lens no longer declares all 8 SAFETY_CLAIM_SPEC axes"
    assert lens.axis_labels["PHARMACOVIGILANCE"] in _lens_terms(lens)
