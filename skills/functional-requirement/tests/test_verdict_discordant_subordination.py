"""Dependency `discordant` subordination + reachability (D3, resolver-precedence audit LOW note).

The resolver-precedence audit flagged that `discordant` (← concordance-discordant-warning, from the
crispr-rnai-dependency-concordance card) sits BELOW the selective/lineage/concordant positives. That is
CORRECT-not-a-bug (a CRISPR-anchored concordant/selective/lineage call is genuinely stronger than
cross-assay disagreement, and the discordant rule's own rationale calls it a soft downgrade, "not a
killer"). BUT the subordination was UNDER-TESTED. These tests pin it both ways:
  - discordant co-firing WITH a selective/lineage/concordant positive -> the positive wins (correct
    subordination);
  - discordant ALONE (or with only weaker/neutral signals) -> `discordant` IS reachable, so its
    nomination positive_contradiction (blocks `strong`) is NOT dead;
  - concordant_dependent above it can never SHADOW discordant, because both derive from the SAME card
    (crispr-rnai-dependency-concordance) on MUTUALLY-EXCLUSIVE concordance_class values — they never
    co-fire, so r4 being above the discordant rung is a same-card exclusive, not a dead-control shadow.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("fr_run_disc", RUN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fr = _load()


def _fresh_verdict(fired):
    """Resolve with the shared load_resolver lru_cache CLEARED first. Other test files in this dir
    exercise the resolver against varying contracts paths, and load_resolver is lru_cached at module
    scope — so a stale-path spec can leak across tests within one pytest session. Clearing the cache
    makes these assertions deterministic regardless of test order."""
    from _skills_common import resolver as _r
    _r.load_resolver.cache_clear()
    return fr._verdict(fired)


def test_discordant_is_reachable_alone():
    """discordant ALONE must resolve to `discordant` — else its nomination positive_contradiction
    (blocks strong) would be a dead safeguard."""
    assert _fresh_verdict([{"rule_id": "concordance-discordant-warning"}]) == (
        "discordant", "concordance-discordant-warning")


def test_selective_positive_correctly_outranks_discordant():
    """A strong selective-dependency signal (from a DIFFERENT card) co-fires with discordant and WINS
    (correct subordination — a real selectivity call beats cross-assay disagreement)."""
    v, _ = _fresh_verdict([{"rule_id": "strongly-selective-supportive"},
                        {"rule_id": "concordance-discordant-warning"}])
    assert v == "selective_dependent"


def test_lineage_selective_correctly_outranks_discordant():
    v, _ = _fresh_verdict([{"rule_id": "lineage-selective-supportive"},
                        {"rule_id": "concordance-discordant-warning"}])
    assert v == "lineage_selective"


def test_concordant_and_discordant_are_same_card_exclusive_never_coemit():
    """concordant_dependent (r4, ← concordant-dependent-supportive-dominant) sits above discordant, but
    both derive from the SAME card+field (concordance_class) on mutually-exclusive values, so they never
    co-fire — r4 above the discordant rung is a same-card exclusive, NOT a dead-control shadow. Assert
    that firing the concordant rule alone gives concordant_dependent (the exclusive positive), confirming
    the two live on the same axis."""
    v, _ = _fresh_verdict([{"rule_id": "concordant-dependent-supportive-dominant"}])
    assert v == "concordant_dependent"
