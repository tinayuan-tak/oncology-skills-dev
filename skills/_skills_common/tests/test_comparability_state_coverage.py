"""The TRUTH HALF of the `comparability_state` governance (envelope v1.1, SK#2210 Wave-0c; epic #1507).

`contracts/validators/validate_comparability_state.py` checks that
`contracts/vocabularies/comparability_state.enum.yaml` is internally coherent and pinned to the family
catalog. Nothing in contracts/ can check the one thing that actually matters: whether the code AGREES
with it. That is this module. It DRIVES the production builders and reconciles what they emit against
what the enum declares, in BOTH directions.

Why both directions. A registration that claims more than the code emits is a false claim of coverage;
a builder that emits more than the registration knows about is exactly the ungoverned-vocabulary drift
this arc exists to end. Neither is catchable from one side, so:

  * PILOTED families (`emission: piloted`) — the builder is driven over the full cross-product of its
    arms' band tokens, and the set of emitted (concordance_class, comparability_state) pairs must EQUAL
    the declared set, where a token named in `omits_state_for` must emit NO key at all. This is the
    clause that gives the OMISSION CONTRACT teeth: `single_source_only` omits the key because no
    comparison was attempted, and a builder that quietly emitted `comparable` there would be claiming a
    licence it never exercised. That mutation is green against the rung-5 conditional slot check — which
    validates the slot WHEN PRESENT and therefore cannot see a key that should not be present at all —
    and it is caught here. It was a live hole found by planting it.

  * DECLARED_ONLY families — the builder must emit NO `comparability_state`. Their state was READ from
    the catalog's `integration.comparability` prose by a human; no code resolves it. If a peer epic
    starts emitting the field from one of those 12 builders, the declaration silently becomes a
    half-truth, and this is what goes red.

DISCIPLINE. Verdict-INERT and byte-stable: this module only READS emitted artifacts and mints nothing.
Every floor names its subject INSIDE the assert with a `len()` call, because
`skills/tests/test_discovery_guards_carry_floors.py` reads floors statically and a floor bound to a
local first is invisible to it (and to the next refactor). A missing or empty enum RAISES at import
rather than degrading to an empty population: a suite that silently examines nothing is worse than a
red one.
"""

from __future__ import annotations

import itertools
import pathlib
import sys

import pytest
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # skills/ -> _skills_common
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # tests/ -> sibling test modules

from _skills_common import genomic_claims  # noqa: E402

# The per-family resolving/empty inputs live in the rung-5 suite's ENVELOPE_FAMILIES registry, which is
# the single place the fleet declares them. Importing it is deliberate: a second copy of 13 fixtures
# would drift from the first, and the whole point of this module is that a second copy of anything is a
# liability. The rung-5 module is import-safe (it builds the registry at module level and runs nothing).
from test_rung5_envelope_enforcement import ENVELOPE_FAMILIES  # noqa: E402

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_ENUM_PATH = _REPO_ROOT / "contracts" / "vocabularies" / "comparability_state.enum.yaml"
_OMITTED = "<OMITTED>"  # the sentinel this module uses to mean "the builder emitted no key"


def _load_enum() -> dict:
    """Fail-loud load. An unreadable or empty enum RAISES: every assertion below is relative to this
    document, so an empty one would make the whole module vacuously green — the exact failure the
    governance is meant to prevent."""
    if not _ENUM_PATH.is_file():
        raise RuntimeError(f"governed enum missing at {_ENUM_PATH} — this suite cannot run without it")
    doc = yaml.safe_load(_ENUM_PATH.read_text()) or {}
    if not isinstance(doc, dict) or not doc.get("families") or not doc.get("values"):
        raise RuntimeError(f"{_ENUM_PATH} has no families/values — refusing to examine an empty population")
    return doc


ENUM = _load_enum()
ENUM_FAMILIES = ENUM["families"]
STATES = frozenset(e["value"] for e in ENUM["values"] if isinstance(e, dict) and e.get("value"))
PILOTED = {f: s for f, s in ENUM_FAMILIES.items() if s.get("emission") == "piloted"}
DECLARED_ONLY = {f: s for f, s in ENUM_FAMILIES.items() if s.get("emission") == "declared_only"}


def _drive_recurrence() -> set:
    """Every (concordance_class, comparability_state | <OMITTED>) pair the recurrence builder can emit.

    Exhaustive over the cross-product of BOTH arms' band tokens, plus None and an off-roster string so
    the gap paths are covered — `_recurrence_direction` maps `data_unavailable` and any unknown token to
    None (gap != absent), and those are the inputs that reach the key-omitted branch."""
    bands = [*genomic_claims._RECURRENCE_SIGNAL, None, "off_roster_token_not_in_any_vocabulary"]
    pairs = set()
    for mc3, genie in itertools.product(bands, bands):
        claim = genomic_claims._recurrence_concordance_claim(
            {"driver_recurrence_class": mc3, "genie_driver_recurrence_class": genie}
        )
        if claim is None:
            continue
        pairs.add((claim["concordance_class"], claim.get("comparability_state", _OMITTED)))
    return pairs


# family -> a driver returning its emitted (token, state) pairs. Keyed so that a family PROMOTED to
# `piloted` without a driver here is RED (see test_every_piloted_family_has_a_driver) rather than
# silently unexamined — an unexamined pilot is the same false-coverage shape as an undeclared family.
_PILOT_DRIVERS = {"recurrence": _drive_recurrence}


def _declared_pairs(spec: dict) -> set:
    """The (token, state | <OMITTED>) pairs a piloted family's declaration promises."""
    pairs = {(t, s) for t, states in (spec.get("per_concordance_class") or {}).items() for s in states}
    return pairs | {(t, _OMITTED) for t in (spec.get("omits_state_for") or [])}


def test_population_is_not_vacuous():
    # Floors name their subject INSIDE the assert, with len(), so the repo's floor guard can see them.
    assert len(ENUM_FAMILIES) == 13, f"enum declares {len(ENUM_FAMILIES)} families, expected 13"
    assert len(STATES) == 3, f"expected 3 governed states, found {sorted(STATES)}"
    assert len(PILOTED) >= 1, "NO piloted family — every reconciliation below would examine nothing"
    assert len(DECLARED_ONLY) >= 1, "NO declared_only family — the no-emission clause would be vacuous"
    assert len(PILOTED) + len(DECLARED_ONLY) == len(ENUM_FAMILIES), (
        f"{len(ENUM_FAMILIES) - len(PILOTED) - len(DECLARED_ONLY)} famil(ies) carry an `emission` value "
        f"that is neither piloted nor declared_only"
    )


def test_every_piloted_family_has_a_driver():
    """Anti-drift: a family promoted to `piloted` in the enum without a driver here would leave its
    emission unexamined while the enum advertises it. The set equality is deliberate in both
    directions — a driver for a family that is no longer piloted is dead code that would keep passing."""
    assert set(_PILOT_DRIVERS) == set(PILOTED), (
        f"piloted-family drivers are out of sync: declared piloted but undriven "
        f"{sorted(set(PILOTED) - set(_PILOT_DRIVERS))}; driven but not declared piloted "
        f"{sorted(set(_PILOT_DRIVERS) - set(PILOTED))}"
    )


@pytest.mark.parametrize("family", sorted(_PILOT_DRIVERS))
def test_piloted_family_emissions_equal_its_declaration(family):
    """THE load-bearing reconciliation. What the builder emits and what the enum declares must be the
    same set of (concordance_class, comparability_state) pairs — with `<OMITTED>` a first-class member,
    which is what makes the omission contract enforceable rather than merely documented."""
    emitted = _PILOT_DRIVERS[family]()
    declared = _declared_pairs(ENUM_FAMILIES[family])
    assert emitted, f"{family}: the driver produced NO pairs — it examined nothing"
    assert emitted == declared, (
        f"{family}: emitted vs declared (concordance_class, comparability_state) pairs disagree.\n"
        f"  emitted but NOT declared: {sorted(emitted - declared)}\n"
        f"  declared but NOT emitted: {sorted(declared - emitted)}\n"
        f"An emitted-but-undeclared pair is ungoverned vocabulary; a declared-but-unemitted pair is a "
        f"false claim of coverage. `{_OMITTED}` means the builder emitted no key at all, which is the "
        f"contract for a token in `omits_state_for`."
    )


@pytest.mark.parametrize("family", sorted(DECLARED_ONLY))
def test_declared_only_families_emit_nothing(family):
    """Declaration is not emission. These 12 states were read from the catalog's prose by a human; if a
    builder starts emitting the field, the declaration becomes a half-truth and the enum must be
    updated (promoting the family to `piloted`, which its validator then holds to a per-token map)."""
    spec = ENVELOPE_FAMILIES.get(family)
    assert spec is not None, (
        f"{family} is declared in the enum but absent from ENVELOPE_FAMILIES — this clause would silently "
        f"examine nothing for it"
    )
    claim = spec["builder"](spec["resolving"])
    assert claim is not None, f"{family}: its resolving fixture no longer emits a claim"
    assert "comparability_state" not in claim, (
        f"{family} is `emission: declared_only` but its builder EMITTED "
        f"comparability_state={claim['comparability_state']!r}. Either revert the emission or promote the "
        f"family to `emission: piloted` in the enum and give it a per_concordance_class map"
    )


def test_every_emitted_state_is_a_governed_token():
    """The narrow version of the rung-5 conditional check, over the real driven population rather than a
    single fixture: every state any piloted builder can produce is in the governed roster."""
    produced = {s for fam in _PILOT_DRIVERS for _t, s in _PILOT_DRIVERS[fam]() if s != _OMITTED}
    assert produced, "no piloted builder produced any state — the clause examined nothing"
    ungoverned = sorted(produced - STATES)
    assert not ungoverned, f"builders emit state(s) {ungoverned} absent from the governed roster {sorted(STATES)}"


def test_the_states_no_family_emits_are_declared_as_such():
    """`normalized_to_compare` is declared by 3 families and emitted by none, and the enum records that
    in `documented_not_emitted`. This pins the two together so the record cannot rot: a state that stops
    being emitted must be added to that block, and one that STARTS being emitted must be removed from it.

    Deliberately NOT a gate on the unemitted COUNT — 12 of 13 families are declared_only by design and a
    count gate would block the arc. It gates only the CONSISTENCY of the claim with reality."""
    produced = {s for fam in _PILOT_DRIVERS for _t, s in _PILOT_DRIVERS[fam]() if s != _OMITTED}
    recorded = {e["state"] for e in (ENUM.get("documented_not_emitted") or []) if isinstance(e, dict)}
    really_unemitted = STATES - produced
    assert recorded == really_unemitted, (
        f"`documented_not_emitted` lists {sorted(recorded)} but the driven population shows "
        f"{sorted(really_unemitted)} are unemitted. Declared-unemitted but actually emitted: "
        f"{sorted(recorded - really_unemitted)}; emitted by nothing but undocumented: "
        f"{sorted(really_unemitted - recorded)}"
    )
