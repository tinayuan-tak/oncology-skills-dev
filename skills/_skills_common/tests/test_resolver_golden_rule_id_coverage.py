"""ANTI-VACUITY guard for the resolver golden oracle: a rung the table never exercises.

THE DEFECT THIS CATCHES (2026-09-12, found while fixing dependency precedence). Each gate's
frozen golden table is enumerated from `resolver_golden_snapshots.json[gate]["rule_ids"]` -- a
HAND-MAINTAINED list (regenerate_resolver_golden.py deliberately keeps it, it does not derive
it). So a rule_id that the resolver REFERENCES but the list OMITS is invisible: the enumerator
never produces a fired-set containing it, so no frozen row can reach any rung keyed on it. Those
rungs are unexercised, and -- worse -- a precedence edit touching them looks like a NO-OP.

Concretely: `dependency` listed 15 of the 22 rule ids its resolver references. Both
partner-conditional rules (Track PC, 2026-08-09) and all five data-unavailable rules (v1.1.0)
were never added, leaving 5 of 18 rungs dead to the oracle. `partner_conditional_dependent` --
a shipped verdict token, `dominant` in the nomination gate -- appeared on ZERO of the 840 frozen
rows. Raising those rungs above `discordant` (resolver v1.4.0) then moved 4/840 rows in the
committed table but 374/8,640 once the ids were listed, so the shipped oracle would have
green-lit a verdict-moving change as near-inert. Cf. the standing rule: for any check, ask
"CAN this fail?" -- for 5 of 18 dependency rungs, it could not.

WHY THIS IS A SEPARATE TEST rather than an assert inside the regenerator: the regenerator only
runs when someone deliberately re-baselines. This must fail in CI on the commit that adds an
unlisted rung, which is exactly when nobody is thinking about the oracle.

DECLARED DEBT, not a silent skip. Three gates cannot simply list their missing ids: the frozen
table is the full co-emission CROSS-PRODUCT, so each additional (card, field) dimension
multiplies the row count. Measured 2026-09-12:
    genomic_alteration          15 -> 28 ids   3,240 -> 7,464,960 rows  (~900 MB, unshippable)
    tractability_small_molecule 20 -> 22 ids  24,576 ->    73,728 rows  (+17 MB)
    surface_modality            17 -> 19 ids   8,064 ->    32,256 rows  (+7.7 MB)
For reference the whole snapshot is 14 MB today and was 41.5 MB before the co-emission migration
shrank it, so paying ~29 MB (and, for genomic_alteration, ~900 MB) to cover 18 rule ids is the
wrong trade -- the fix is a cheaper ENUMERATION REGIME (e.g. freeze all co-firing sets up to
order k plus the full set: precedence defects are pairwise, and size<=2 over 28 ids is 407 rows,
not 7.5 M), which is a design change this guard deliberately does not smuggle in. Until then the
gap is recorded below WITH its measured cost, and the assertions below let it only SHRINK.

The debt map is checked for EQUALITY, not containment, so it cannot drift in either direction:
  - add an unlisted rung to a debt gate  -> this test fails (the set no longer matches)
  - fix a debt gate by listing its ids   -> this test fails until the entry is deleted
  - add an unlisted rung to any OTHER gate -> this test fails (no entry covers it)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

SKILLS = Path(__file__).resolve().parents[2]  # .../skills
CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)
SNAPSHOT = Path(__file__).resolve().parent / "resolver_golden_snapshots.json"
_GOLDEN = json.loads(SNAPSHOT.read_text())

# gate -> rule ids the resolver references that the golden's rule_ids list does NOT carry, because
# listing them would blow the frozen cross-product up (row counts in the module docstring). Shrink
# this map; do not grow it without the measured row count that justifies the entry.
RULE_ID_COVERAGE_DEBT: dict[str, set[str]] = {
    "genomic_alteration": {
        "amp-expr-indication-scoped-context",
        "amp-expr-moderately-dependent-supportive",
        "amp-expr-strongly-dependent-supportive",
        "cn-amplified-indication-scoped-context",
        "cn-amplified-moderately-dependent-supportive",
        "cn-amplified-strongly-dependent-supportive",
        "cn-data-unavailable-insufficient",
        "fusion-landscape-recurrent-driver-supportive",
        "fusion-positive-indication-scoped-context",
        "fusion-positive-moderately-dependent-supportive",
        "fusion-positive-strongly-dependent-supportive",
        "mutant-indication-scoped-context",
        "mutation-drug-response-strongly-sensitive-supportive",
    },
    "surface_modality": {
        "exon-window-essential-liability-tce-opposing",
        "pmhc-broadly-presented-normal-tce-opposing",
    },
    "tractability_small_molecule": {
        "measured-potent-ligand-sm-supportive",
        "measured-weak-ligand-sm-supportive",
    },
}


def _referenced_rule_ids(gate: str) -> set[str]:
    """Every rule_id a resolver spec mentions, in any when-clause or as a driving_rule."""
    spec = yaml.safe_load((CONTRACTS / "resolvers" / f"{gate}.resolver.yaml").read_text())
    out: set[str] = set()
    for rung in spec.get("resolve") or []:
        for key in ("when_fired", "when_all_fired", "when_any_fired", "when_not_fired"):
            val = rung.get(key)
            if isinstance(val, str):
                out.add(val)
            elif isinstance(val, list):
                out.update(val)
        if rung.get("driving_rule"):
            out.add(rung["driving_rule"])
    return out


@pytest.mark.parametrize("gate", sorted(_GOLDEN.keys()))
def test_golden_rule_ids_cover_every_rule_the_resolver_references(gate):
    """No rung may be unreachable from the frozen table's enumeration, except as DECLARED debt."""
    missing = _referenced_rule_ids(gate) - set(_GOLDEN[gate]["rule_ids"])
    declared = RULE_ID_COVERAGE_DEBT.get(gate, set())
    assert missing == declared, (
        f"{gate}: golden rule_ids coverage drifted.\n"
        f"  unlisted but referenced : {sorted(missing) or '(none)'}\n"
        f"  declared debt           : {sorted(declared) or '(none)'}\n"
        f"Any rung keyed on an unlisted rule_id is UNEXERCISED by the golden table, so a "
        f"precedence edit touching it will look inert. Add the id to "
        f"resolver_golden_snapshots.json[{gate!r}]['rule_ids'] and re-run "
        f"regenerate_resolver_golden.py; if the resulting row count is prohibitive, extend "
        f"RULE_ID_COVERAGE_DEBT with the MEASURED count. If you FIXED a debt entry, delete it here."
    )


def test_every_referenced_rule_id_exists_in_the_rule_index():
    """Complementary direction: a resolver must not reference a rule_id no interpretation rule
    emits (a typo or a retired rule) -- that rung is dead for the opposite reason."""
    from _test_support import load_module

    coemit = load_module(SKILLS / "_skills_common" / "tests" / "coemission.py", "coemission_cov_ut")
    known = set(coemit.load_rule_index(CONTRACTS))
    dead: dict[str, list[str]] = {}
    for gate in sorted(_GOLDEN):
        unknown = sorted(_referenced_rule_ids(gate) - known)
        if unknown:
            dead[gate] = unknown
    assert not dead, f"resolvers reference rule_ids no interpretation rule emits: {dead}"


def test_the_debt_map_names_only_shipped_gates_and_real_rule_ids():
    """The debt map itself must stay honest: no entry for a retired gate, and no entry naming a
    rule_id the resolver no longer references (which would let a REAL gap hide behind a stale
    exemption of the same size)."""
    assert set(RULE_ID_COVERAGE_DEBT) <= set(_GOLDEN), (
        f"debt map names gates with no golden table: {sorted(set(RULE_ID_COVERAGE_DEBT) - set(_GOLDEN))}"
    )
    for gate, ids in RULE_ID_COVERAGE_DEBT.items():
        stale = sorted(ids - _referenced_rule_ids(gate))
        assert not stale, f"{gate}: debt names rule_ids the resolver no longer references: {stale}"


def test_dependency_gate_exercises_partner_conditional_dependent():
    """The specific regression: `partner_conditional_dependent` is a shipped verdict token and a
    `dominant` nomination-gate positive_signal, yet ZERO of the 840 frozen dependency rows could
    emit it because both partner-conditional rule ids were unlisted. Pin that it is reachable.

    Deliberately named per-verdict rather than folded into the coverage test above: the coverage
    test is about rule IDS, this is about the VERDICT the missing ids gated, which is the thing a
    reviewer actually cares about.
    """
    verdicts = {v for v, _ in _GOLDEN["dependency"]["table"].values()}
    assert "partner_conditional_dependent" in verdicts
    assert "insufficient_underpowered" in verdicts  # the other rung the 15-id list starved
