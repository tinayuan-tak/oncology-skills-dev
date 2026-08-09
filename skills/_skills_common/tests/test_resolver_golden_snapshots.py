"""FROZEN golden-snapshot regression for every declarative resolver (gap #5, 2026-07-20;
CO-EMISSION-AWARE since D5, 2026-08-09).

WHY a frozen table, not a live spec==_verdict comparison: once each skill's _verdict was
swapped to DELEGATE to the interpreter (step 4), a "spec == _verdict" oracle became
tautological (spec == spec). The pre-swap oracle already PROVED spec == the original
if-chain byte-for-byte (merged PRs #90/#91 — 16,384 dependency combos + all flat gates).
This test freezes that VERIFIED behavior as a committed snapshot
(resolver_golden_snapshots.json) and asserts each spec still reproduces it EXACTLY. So it:
  - survives the if-chain deletion (no longer needs the old code to compare against),
  - catches any FUTURE drift in a spec (a precedence edit that changes a verdict fails CI),
  - stays exhaustive over the reachable state space (see below), both verdict AND driving_rule_id.

CO-EMISSION-AWARE ENUMERATION (D5, 2026-08-09): the snapshot no longer freezes the full 2**n
power set of a gate's rule_ids. Most power-set combos are CARD-CO-EMISSION-IMPOSSIBLE — a single
card field holds one value, so rules keying on different values of that field are mutually
exclusive and can never co-fire (the trap behind the T1.1 dead-`discordant` finding). The table now
enumerates only the fired-sets that are genuinely co-emission-reachable, derived from the
interpretation-rules' (card_id, field) bindings (see _skills_common/coemission.py). This:
  - SHRINKS the file (~105k -> ~4k rows across 9 gates; 41.5 MB -> <1 MB) so EVERY gate freezes
    its FULL rule set (retiring tractability's core-16 subset + the separate 2**18 100 MB-workaround
    oracle — the power set couldn't be stored past ~17 rungs under GitHub's 100 MB limit), and
  - is HONEST — every frozen combo is a physically-possible card state.

COVERAGE PRESERVED (test_coemission_is_reachable_subset below proves it): every co-emission fired-set
is a subset of the old power set (nothing invented), and every co-emission-reachable power-set combo is
still enumerated — only provably-impossible combos are dropped.

The snapshot is trustworthy BECAUSE it was generated from specs the pre-swap oracle proved correct.
Regenerating it is a deliberate, reviewed act (a verdict-contract change) — run
regenerate_resolver_golden.py and commit the new JSON alongside the resolver edit.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

# Load the shared modules (resolver.py, coemission.py) RELATIVE TO THIS TEST FILE so the harness runs
# correctly from any checkout/worktree (a new sibling module added on a branch is visible before merge).
# CONTRACTS stays an env-overridable canonical pin (the resolver specs + interpretation-rules under test).
SKILLS = Path(__file__).resolve().parents[2]           # .../skills
CONTRACTS = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT",
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))
SNAPSHOT = Path(__file__).resolve().parent / "resolver_golden_snapshots.json"

if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))


def _load(mod_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = m
    spec.loader.exec_module(m)
    return m


_resolver = _load("resolver_snap_ut", SKILLS / "_skills_common" / "resolver.py")
_coemit = _load("coemission_snap_ut", SKILLS / "_skills_common" / "coemission.py")
_GOLDEN = json.loads(SNAPSHOT.read_text())
_RULE_INDEX = _coemit.load_rule_index(CONTRACTS)


def _coemission_fired_sets(gate: str):
    return _coemit.coemission_fired_sets_for_gate(_GOLDEN[gate]["rule_ids"], _RULE_INDEX)


def test_snapshot_covers_all_shipped_resolver_gates():
    """Guard: the frozen snapshot must cover every shipped resolver spec (so a NEW gate
    can't be added without a golden table)."""
    shipped = {p.stem.replace(".resolver", "")
               for p in (CONTRACTS / "resolvers").glob("*.resolver.yaml")}
    assert set(_GOLDEN.keys()) == shipped, (
        f"snapshot gates {set(_GOLDEN.keys())} != shipped resolvers {shipped}")


@pytest.mark.parametrize("gate", list(_GOLDEN.keys()))
def test_spec_reproduces_frozen_golden_table(gate):
    """EXHAUSTIVE over the co-emission-reachable state space: for every reachable fired-set the
    current spec must produce the EXACT (verdict, driving_rule_id) the frozen table holds."""
    entry = _GOLDEN[gate]
    spec = _resolver.load_resolver(gate, contracts_repo=CONTRACTS)
    assert spec is not None, f"resolver spec for {gate} must load"
    table = entry["table"]
    fired_sets = _coemission_fired_sets(gate)
    # every reachable fired-set is IN the frozen table (no reachable combo left unfrozen) and the
    # table has no stale keys -- the enumeration and the committed table agree exactly.
    keys_from_sets = {",".join(sorted(fs)) for fs in fired_sets}
    assert keys_from_sets == set(table.keys()), (
        f"[{gate}] co-emission fired-sets != frozen table keys "
        f"(missing {len(keys_from_sets - set(table))}, stale {len(set(table) - keys_from_sets)}). "
        f"Regenerate the snapshot (regenerate_resolver_golden.py).")
    # ...and each reproduces its frozen (verdict, driving_rule_id).
    mismatches = []
    for fs in fired_sets:
        key = ",".join(sorted(fs))
        exp_v, exp_drv = table[key]
        got_v, got_drv = _resolver.resolve_verdict([{"rule_id": r} for r in sorted(fs)], spec)
        if [got_v, got_drv] != [exp_v, exp_drv]:
            mismatches.append((key, [exp_v, exp_drv], [got_v, got_drv]))
    assert not mismatches, (
        f"[{gate}] {len(mismatches)}/{len(table)} combos DRIFTED from the frozen golden table. "
        f"If intentional, regenerate the snapshot (a reviewed verdict-contract change). First:\n" +
        "\n".join(f"  fired={m[0]}\n    golden={m[1]} spec={m[2]}" for m in mismatches[:5]))


@pytest.mark.parametrize("gate", list(_GOLDEN.keys()))
def test_coemission_is_reachable_subset(gate):
    """COVERAGE-PRESERVATION INVARIANT (D5): every frozen combo must be a valid power-set member
    (never invents a rule) AND physically possible (<=1 fired rule per mutual-exclusivity group). This
    is the structural proof that the co-emission table drops ONLY impossible combos — the enumerator
    covers every group-choice x free-toggle, so nothing reachable is missed; here we assert each frozen
    key obeys the exclusivity structure derived from the interpretation-rules."""
    rule_ids = _GOLDEN[gate]["rule_ids"]
    groups, _free = _coemit.build_exclusivity_groups(rule_ids, _RULE_INDEX)
    group_of = {r: gi for gi, g in enumerate(groups) for r in g}
    allowed = set(rule_ids)
    for key in _GOLDEN[gate]["table"]:
        fired = [r for r in key.split(",") if r]
        assert set(fired) <= allowed, f"[{gate}] frozen key {key!r} has non-gate rule(s)"
        seen_groups = [group_of[r] for r in fired if r in group_of]
        assert len(seen_groups) == len(set(seen_groups)), (
            f"[{gate}] frozen key {key!r} co-fires >1 rule from one exclusivity group "
            f"(card-co-emission-impossible — should never be in a co-emission table)")


def test_tractability_full_rule_set_is_frozen():
    """REGRESSION for the D5 motivation: tractability_small_molecule (16 rule_ids) previously could not
    freeze its full rule set (a core-16 subset + a SEPARATE live 2**18 oracle, because the full power
    set was 127 MB > GitHub's 100 MB). The co-emission table freezes ALL of it in-file. Assert its
    table equals the full co-emission enumeration over all 16 rule_ids (not a truncated subset)."""
    gate = "tractability_small_molecule"
    assert gate in _GOLDEN
    assert len(_GOLDEN[gate]["rule_ids"]) == 16
    assert len(_GOLDEN[gate]["table"]) == len(_coemission_fired_sets(gate)) > 2000
