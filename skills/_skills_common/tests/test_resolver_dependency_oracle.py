"""GOLDEN-ORACLE equivalence: the declarative dependency resolver == the Python if-chain.

The migration is safe ONLY because we prove the spec reproduces the existing
functional-requirement._verdict byte-for-byte (verdict AND driving_rule_id) BEFORE the
if-chain is deleted. There are 14 dependency rule_ids the if-chain references, so 2^14 =
16,384 fired-set combinations are FULLY ENUMERABLE — this asserts equivalence on EVERY one.
If they ever diverge, this fails, and the if-chain stays as the source of truth.

This is the framework's measured-vs-null discipline applied to its own refactor: don't
trust the new path until it's measured against the old one, exhaustively.
"""
from __future__ import annotations

import importlib.util
import itertools
from pathlib import Path

import pytest

SKILLS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills")
CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")


def _load(mod_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# the Python if-chain (the ORACLE) — load functional-requirement/run.py with a stubbed
# dispatcher so the __main__ import doesn't require the full package.
import sys
import types
if "_skills_common" not in sys.modules:
    sys.path.insert(0, str(SKILLS))
_fr = _load("fr_oracle", SKILLS / "functional-requirement" / "scripts" / "run.py")

_resolver = _load("resolver_under_test", SKILLS / "_skills_common" / "resolver.py")

# the 14 rule_ids the dependency if-chain references
DEPENDENCY_RULE_IDS = [
    "common-essential-underpowered-insufficient",
    "rnai-common-essential-underpowered-insufficient",
    "pan-essential-killer",
    "rnai-pan-essential-killer",
    "concordant-dependent-supportive-dominant",
    "lineage-selective-supportive",
    "strongly-selective-supportive",
    "rnai-strongly-selective-supportive",
    "concordance-discordant-warning",
    "non-dependent-underpowered-insufficient",
    "strong-paralog-buffering-degrader-preferred",
    "non-dependent-killer",
    "broadly-dependent-neutral",
    "rnai-broadly-dependent-neutral",
]

_SPEC = _resolver.load_resolver("dependency", contracts_repo=CONTRACTS)


def test_spec_loads():
    assert _SPEC is not None, "dependency.resolver.yaml must be loadable"
    assert _SPEC["gate"] == "dependency"


def test_exhaustive_equivalence_all_16384_combinations():
    """EVERY subset of the 14 dependency rule_ids: resolver spec == Python _verdict,
    both verdict AND driving_rule_id. 2^14 combinations."""
    mismatches = []
    n = len(DEPENDENCY_RULE_IDS)
    for bits in range(2 ** n):
        fired_ids = [DEPENDENCY_RULE_IDS[i] for i in range(n) if bits & (1 << i)]
        fired = [{"rule_id": rid} for rid in fired_ids]
        oracle = _fr._verdict(fired)
        spec_out = _resolver.resolve_verdict(fired, _SPEC)
        if oracle != spec_out:
            mismatches.append((fired_ids, oracle, spec_out))
            if len(mismatches) <= 5:
                continue
    assert not mismatches, (
        f"{len(mismatches)} of {2**n} combinations diverge. First few:\n" +
        "\n".join(f"  fired={m[0]}\n    oracle={m[1]}  spec={m[2]}" for m in mismatches[:5]))


def test_compound_paralog_case_explicit():
    """The compound when_all_fired case (the reason the resolver DSL needs conjunction):
    non-dependent-killer AND strong paralog buffer → non_dependent_paralog_buffered,
    driving_rule = the buffer rule (provenance anchor), escaping the veto."""
    fired = [{"rule_id": "non-dependent-killer"},
             {"rule_id": "strong-paralog-buffering-degrader-preferred"}]
    assert _resolver.resolve_verdict(fired, _SPEC) == (
        "non_dependent_paralog_buffered", "strong-paralog-buffering-degrader-preferred")
    # and it MUST match the oracle
    assert _resolver.resolve_verdict(fired, _SPEC) == _fr._verdict(fired)


def test_when_any_fired_driving_rule_is_first_listed():
    """when_any_fired driving_rule fidelity: CRISPR pan-essential listed before RNAi, so
    if only RNAi fires, driving_rule is the RNAi rule; if both, the CRISPR one (first)."""
    only_rnai = [{"rule_id": "rnai-pan-essential-killer"}]
    assert _resolver.resolve_verdict(only_rnai, _SPEC)[1] == "rnai-pan-essential-killer"
    both = [{"rule_id": "pan-essential-killer"}, {"rule_id": "rnai-pan-essential-killer"}]
    assert _resolver.resolve_verdict(both, _SPEC)[1] == "pan-essential-killer"
    # both match the oracle
    assert _resolver.resolve_verdict(only_rnai, _SPEC) == _fr._verdict(only_rnai)
    assert _resolver.resolve_verdict(both, _SPEC) == _fr._verdict(both)


def test_empty_is_default_insufficient():
    assert _resolver.resolve_verdict([], _SPEC) == ("insufficient", None)
    assert _resolver.resolve_verdict([], _SPEC) == _fr._verdict([])
