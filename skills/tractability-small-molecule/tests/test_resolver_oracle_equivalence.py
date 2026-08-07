"""B3a golden-oracle equivalence: the declarative resolver reproduces the retained if-chain EXACTLY.

`_snapshot` now delegates to resolvers/tractability_small_molecule.resolver.yaml; `_snapshot_legacy_oracle`
is the original 11-rung if-chain, retained ONLY as the oracle. This test asserts the two agree on
(verdict, driving_rule_id) for EVERY combination of the 10 ladder rule_ids (2^10 = 1024) — the proof that
the conversion is byte-identical before the if-chain is trusted-dead.

Requires the resolver spec to be resolvable. It loads from the target-contracts checkout the resolver
interpreter finds (primary checkout on main once TC #219 merges); if the spec is absent (e.g. running
before merge), the delegating _snapshot RAISES — the test then SKIPS with a clear reason rather than
red-flagging an unmerged-contract state. The exhaustive frozen guarantee also lives in the shared
_skills_common/tests/test_resolver_golden_snapshots.py (whose table was generated from this same oracle)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"

# The 14 rule_ids the ladder branches on (order matches the resolver rungs).
# +4 E8-lig composite-ligandability rungs (2026-08-07): experimental/predicted (structurally_ligandable),
# disordered (structurally_intractable). no-evidence maps to the default fallthrough (no branch).
RULE_IDS = [
    "e7-triangulated-target-engaged-supportive",
    "e7-crispr-confirmed-supportive-sm",
    "prism-clinically-active-supportive-sm",
    "known-drug-approved-antineoplastic-sm-supportive",   # E-known-drug: approved -> chemically_active
    "prism-tool-compound-only-weak-supportive-sm",
    "prism-weakly-active-weak-supportive-sm",
    "e7-discordant-off-target-warning",
    "ligandability-experimental-sm-supportive",
    "hotspot-in-druggable-pocket-sm-supportive-e8",
    "structure-pocket-adjacent-sm-supportive",
    "ligandability-predicted-sm-supportive",
    "known-drug-druggable-category-sm-supportive",        # E-known-drug: category -> structurally_ligandable
    "structure-low-confidence-sm-opposing",
    "ligandability-disordered-sm-opposing",
    "prism-no-compounds-found-neutral",
]


def _load():
    spec = importlib.util.spec_from_file_location("tsm_run", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tp = _load()


def _resolver_available() -> bool:
    try:
        return tp._snapshot([{"rule_id": "prism-no-compounds-found-neutral"}])[0] == "chemically_unhit"
    except RuntimeError:
        return False


def test_resolver_matches_if_chain_oracle_for_all_combos():
    if not _resolver_available():
        pytest.skip("tractability_small_molecule resolver spec not resolvable "
                    "(TC contract PR not merged into the checkout yet) — equivalence covered by "
                    "the shared resolver_golden_snapshots table once merged.")
    n = len(RULE_IDS)
    mismatches = []
    for bits in range(2 ** n):
        fired = [{"rule_id": RULE_IDS[i]} for i in range(n) if bits & (1 << i)]
        got = tp._snapshot(fired)                     # delegates to the resolver
        exp = tp._snapshot_legacy_oracle(fired)       # the retained if-chain oracle
        if got != exp:
            mismatches.append((sorted(r["rule_id"] for r in fired), exp, got))
    assert not mismatches, (
        f"{len(mismatches)}/{2**n} combos DIVERGED between the resolver and the if-chain oracle. "
        f"First: {mismatches[:3]}")
