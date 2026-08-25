"""M5 rule-role partition — the verdict-inert rules as an EXPLICIT display channel. Pins that the
committed snapshot is a well-formed, non-overlapping partition of EVERY rule, matches the live
contracts (no drift), and that gating rules are exactly those a resolver references."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validators"))
import build_rule_role_partition as brp  # noqa: E402


def _committed():
    return yaml.safe_load((ROOT / "coverage" / "rule_role_partition.yaml").read_text())


def test_committed_snapshot_matches_live_contracts():
    ok, errs = brp.self_check()
    assert ok, f"rule_role_partition.yaml drifted — regenerate: {errs}"


def test_partition_is_complete_and_disjoint():
    p = _committed()
    gating, display = set(p["gating"]), set(p["display"])
    assert gating.isdisjoint(display), "a rule cannot be both gating and display"
    all_rules = set(brp._all_rules())
    assert gating | display == all_rules, "partition must cover every defined rule"
    assert p["counts"] == {"total": len(all_rules), "gating": len(gating), "display": len(display)}


def test_gating_is_exactly_resolver_referenced():
    p = _committed()
    refs = brp._resolver_referenced_rule_ids()
    all_rules = set(brp._all_rules())
    # gating = defined rules a resolver references; display = the rest (annotation-only)
    assert set(p["gating"]) == {r for r in all_rules if r in refs}
    assert set(p["display"]) == {r for r in all_rules if r not in refs}


def test_display_channel_is_the_inert_majority():
    # sanity: the audit's finding — the majority of rules are annotation-only, not verdict-driving
    p = _committed()
    assert p["counts"]["display"] > p["counts"]["gating"]
