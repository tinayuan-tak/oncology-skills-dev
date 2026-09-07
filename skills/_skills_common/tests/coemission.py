"""Co-emission-aware fired-set enumeration for resolver golden snapshots (D5, 2026-08-09).

## Why this exists

The frozen golden-snapshot regression (tests/test_resolver_golden_snapshots.py) enumerated the
FULL POWER SET of a gate's rule_ids — 2**n fired-sets — and froze (verdict, driving_rule_id) for
each. Two problems that grow with the framework:

  1. IT DOES NOT SCALE. 2**18 (tractability's 18 rungs) = 262,144 rows = 127 MB > GitHub's 100 MB
     object limit. tractability was pinned at a "core-16" subset with a SEPARATE live 2**18
     oracle-equivalence test as a workaround. The next gate to cross ~17 rungs hits the same wall.

  2. IT IS DISHONEST. Most power-set combos are CARD-CO-EMISSION-IMPOSSIBLE. A single card field
     (e.g. prism_activity_class, concordance_class) holds exactly ONE value per evaluation, so the
     rules that key on DIFFERENT values of that ONE field are MUTUALLY EXCLUSIVE — at most one fires.
     The power set enumerates `prism-clinically-active AND prism-tool-compound-only` co-firing, which
     can NEVER happen. Those fake rows both bloat the table and give false coverage confidence (they
     were the trap behind the T1.1 dead-`discordant` finding: 256 "reachable" combos were impossible).

## What it computes

The set of fired-sets that are actually CO-EMISSION-REACHABLE, derived from the interpretation-rules
themselves (the single source of truth). Each rule declares `when: {card_id, field, equals|in: <v>}`.
Rules that share the same `(card_id, field)` form a MUTUALLY-EXCLUSIVE GROUP: the field takes one
value, so the fired rule is whichever group member's value-set contains it — at most one, plus the
"field takes a value no rule matches / card absent" none-state. Rules whose `(card_id, field)` is
unique (or that use a non-value condition) are INDEPENDENT and toggle on/off freely.

Enumeration = cartesian product over [ each group: (none) + one-per-member ] x [ each free rule: off/on ].
  co-emission-reachable count = prod(group_size + 1 for each group) * 2**(n_free)

vs the power set's 2**n. For the 9 shipped gates this is ~5,000 combos total vs ~105,000 (21x smaller),
and every gate now fits a single frozen table over its FULL rule set (no core-N subset, no 100 MB wall).

## Coverage-preservation invariant (the safety proof)

Every co-emission fired-set is a SUBSET of the power set (we never invent a combo). And every power-set
combo that is co-emission-REACHABLE (no two fired rules collide on a shared value-disjoint (card,field)
group) IS enumerated here. So the ONLY combos dropped are provably impossible ones. The harness asserts
this explicitly (see tests/test_resolver_golden_snapshots.py::test_coemission_is_reachable_subset).

REQUIREMENT for grouping (verified by the harness): members of a shared-(card,field) group must have
PAIRWISE-DISJOINT value-sets (so "the field's value" selects at most one member). If a future rule adds
an OVERLAPPING value-set on a shared field, `build_exclusivity_groups` raises — grouping them would be
unsound (two could co-fire), so the author must reconcile the rules or the model. Fail-loud, never
silently under-cover.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Iterable, Optional

import yaml


def _rule_condition(when: dict) -> tuple[Optional[str], Optional[str], Optional[frozenset]]:
    """(card_id, field, value_set) for a rule's `when` block. value_set is None when the rule
    does not key on a discrete field value (a threshold / compound / other condition) — such a rule
    is treated as INDEPENDENT (never grouped)."""
    card_id = when.get("card_id")
    field = when.get("field")
    if "equals" in when:
        return card_id, field, frozenset([when["equals"]])
    if "in" in when:
        return card_id, field, frozenset(when["in"])
    return card_id, field, None


def load_rule_index(contracts_root: Path) -> dict[str, tuple[Optional[str], Optional[str], Optional[frozenset]]]:
    """rule_id -> (card_id, field, value_set) over ALL interpretation-rules files. The single
    source of truth for a rule's card-field binding."""
    idx: dict[str, tuple] = {}
    rules_dir = Path(contracts_root) / "interpretation-rules"
    for f in sorted(rules_dir.glob("*.rules.yaml")):
        doc = yaml.safe_load(f.read_text())
        for r in doc.get("rules") or []:
            rid = r.get("rule_id")
            if rid:
                idx[rid] = _rule_condition(r.get("when") or {})
    return idx


def build_exclusivity_groups(
    rule_ids: list[str],
    rule_index: dict[str, tuple],
) -> tuple[list[list[str]], list[str]]:
    """Partition a gate's rule_ids into mutually-exclusive GROUPS + FREE (independent) rules.

    A group = the rules sharing one (card_id, field) where every member keys on a discrete value-set
    (equals/in). Members must be PAIRWISE VALUE-DISJOINT (the field's single value selects <=1 member)
    — else raises ValueError (grouping would be unsound). A (card,field) with a single value-keyed rule,
    or any rule with no value condition, is FREE.

    Returns (groups, free) where groups is a list of rule_id lists (each >=2) and free is a flat list.
    Group order + within-group order follow rule_ids (deterministic).
    """
    # bucket by (card, field), preserving rule_ids order
    buckets: dict[tuple, list[str]] = {}
    order: list[tuple] = []
    for rid in rule_ids:
        if rid not in rule_index:
            raise KeyError(f"rule_id {rid!r} not found in interpretation-rules index")
        card, field, vals = rule_index[rid]
        key = (card, field)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(rid)

    groups: list[list[str]] = []
    free: list[str] = []
    for key in order:
        members = buckets[key]
        value_keyed = [m for m in members if rule_index[m][2] is not None]
        # group only if >=2 members AND all are value-keyed (a discrete field value picks the winner)
        if len(members) >= 2 and len(value_keyed) == len(members):
            # pairwise value-set disjointness (soundness requirement)
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    vi, vj = rule_index[members[i]][2], rule_index[members[j]][2]
                    if vi & vj:
                        raise ValueError(
                            f"cannot group {members[i]!r} and {members[j]!r} on {key}: "
                            f"value-sets overlap on {set(vi & vj)} (both could fire — grouping unsound). "
                            f"Reconcile the rules or exclude from co-emission grouping."
                        )
            groups.append(list(members))
        else:
            free.extend(members)
    return groups, free


def enumerate_coemission_fired_sets(
    groups: list[list[str]],
    free: list[str],
) -> Iterable[frozenset]:
    """Yield every co-emission-reachable fired-set as a frozenset of rule_ids.

    Cartesian product over [each group: (none) + exactly-one-member] x [each free rule: off/on].
    """
    # per group: options are None (field value matches no member / card absent) + each member
    group_options = [[None, *g] for g in groups]
    for combo in itertools.product(*group_options):
        chosen_from_groups = [c for c in combo if c is not None]
        for free_bits in range(2 ** len(free)):
            chosen_free = [free[i] for i in range(len(free)) if free_bits & (1 << i)]
            yield frozenset(chosen_from_groups + chosen_free)


def coemission_fired_sets_for_gate(
    rule_ids: list[str],
    rule_index: dict[str, tuple],
) -> list[frozenset]:
    """Convenience: groups+free -> sorted, de-duplicated list of co-emission-reachable fired-sets.
    Sorted by (size, sorted-tuple) for deterministic, review-stable golden ordering."""
    groups, free = build_exclusivity_groups(rule_ids, rule_index)
    seen = set(enumerate_coemission_fired_sets(groups, free))
    return sorted(seen, key=lambda fs: (len(fs), tuple(sorted(fs))))
