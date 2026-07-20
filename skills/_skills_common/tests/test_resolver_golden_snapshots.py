"""FROZEN golden-snapshot regression for every declarative resolver (gap #5, 2026-07-20).

WHY a frozen table, not a live spec==_verdict comparison: once each skill's _verdict was
swapped to DELEGATE to the interpreter (step 4), a "spec == _verdict" oracle became
tautological (spec == spec). The pre-swap oracle already PROVED spec == the original
if-chain byte-for-byte (merged PRs #90/#91 — 16,384 dependency combos + all flat gates).
This test freezes that VERIFIED behavior as a committed snapshot
(resolver_golden_snapshots.json) and asserts each spec still reproduces it EXACTLY across
all fired-set combinations. So it:
  - survives the if-chain deletion (no longer needs the old code to compare against),
  - catches any FUTURE drift in a spec (a precedence edit that changes a verdict fails CI),
  - stays exhaustive (every 2^n fired-set, both verdict AND driving_rule_id).

The snapshot is trustworthy BECAUSE it was generated from specs the pre-swap oracle proved
correct. Regenerating it is a deliberate, reviewed act (a verdict-contract change).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SKILLS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills")
CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
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
_GOLDEN = json.loads(SNAPSHOT.read_text())


def test_snapshot_covers_all_seven_resolver_gates():
    """Guard: the frozen snapshot must cover every shipped resolver spec (so a NEW gate
    can't be added without a golden table)."""
    shipped = {p.stem.replace(".resolver", "")
               for p in (CONTRACTS / "resolvers").glob("*.resolver.yaml")}
    assert set(_GOLDEN.keys()) == shipped, (
        f"snapshot gates {set(_GOLDEN.keys())} != shipped resolvers {shipped}")


@pytest.mark.parametrize("gate", list(_GOLDEN.keys()))
def test_spec_reproduces_frozen_golden_table(gate):
    """EXHAUSTIVE: for every fired-set combination in the frozen table, the current spec
    must produce the EXACT (verdict, driving_rule_id) it was verified to produce."""
    entry = _GOLDEN[gate]
    rule_ids = entry["rule_ids"]
    spec = _resolver.load_resolver(gate, contracts_repo=CONTRACTS)
    assert spec is not None, f"resolver spec for {gate} must load"
    n = len(rule_ids)
    mismatches = []
    for bits in range(2 ** n):
        fired = [{"rule_id": rule_ids[i]} for i in range(n) if bits & (1 << i)]
        key = ",".join(sorted(r["rule_id"] for r in fired))
        exp_v, exp_drv = _GOLDEN[gate]["table"][key]
        got_v, got_drv = _resolver.resolve_verdict(fired, spec)
        if [got_v, got_drv] != [exp_v, exp_drv]:
            mismatches.append((key, [exp_v, exp_drv], [got_v, got_drv]))
    assert not mismatches, (
        f"[{gate}] {len(mismatches)}/{2**n} combos DRIFTED from the frozen golden table. "
        f"If intentional, regenerate the snapshot (a reviewed verdict-contract change). First:\n" +
        "\n".join(f"  fired={m[0]}\n    golden={m[1]} spec={m[2]}" for m in mismatches[:5]))
