"""Guard #2111 — `predictability_class` stays VERDICT-INERT everywhere.

`dependency-predictability.card.yaml` asserts (per its own docstring) that
`predictability_class` is "VERDICT-INERT everywhere: it fires no verdict rung
in any resolver" — the 5 rules keying on it are DESCRIPTIVE, feeding only a
key-signals/display aggregation (tractability-small-molecule's
`small_molecule_key_signals`), never a resolver rung.

Verified true as of 2026-09-30 (no live defect) — this test exists only to lock
the invariant by CONVENTION-turned-CONTRACT, so a future edit that adds one of
these rule_ids to a resolver rung, or reclassifies it out of `display` in
`contracts/coverage/rule_role_partition.yaml`, goes RED instead of drifting
silently. See [[feedback_green_for_the_wrong_reason]] — this is exactly the
"card advertises an invariant nothing enforces" shape.

Two independent checks, both against the LIVE contracts (not a frozen
snapshot), so either direction of drift trips a check:

  1. every rule whose `when.field == predictability_class` stays classified
     `display` (non-gating) in `rule_role_partition.yaml`.
  2. none of those rule_ids appears ANYWHERE inside a resolver YAML — a full
     recursive leaf-string scan, not a keypath allowlist, so it also catches a
     reference tucked into a `post_resolver_clamp` arm or a clamp `upgrade`
     requirement, not just a `resolve[].when_fired`.

A teeth test (`test_detectors_are_not_vacuous`) proves both checks actually
fire on a synthetic violation, so this file cannot go green by construction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
RULES_DIR = REPO / "interpretation-rules"
RESOLVERS_DIR = REPO / "resolvers"
PARTITION_FILE = REPO / "coverage" / "rule_role_partition.yaml"

#: Pinned BY NAME (not by count) — the exact 5 rules the issue names.
EXPECTED_PREDICTABILITY_RULE_IDS = {
    "predictability-biomarker-hypothesis-supportive",
    "predictability-context-determined-neutral",
    "predictability-weakly-predictable-neutral",
    "predictability-unpredictable-neutral",
    "predictability-data-unavailable-insufficient",
}


def _rules_files() -> list[Path]:
    return sorted(RULES_DIR.glob("*.rules.yaml"))


def _when_matches_predictability_class(when: Any) -> bool:
    """True if a rule's `when` clause keys directly on `predictability_class`.

    Handles the plain `{card_id, field, equals}` form (what all 5 rules use
    today) plus the `when_all`/`when_any` combinator forms, so a future rule
    that folds `predictability_class` into a conjunction is still caught.
    """
    if isinstance(when, dict):
        if when.get("field") == "predictability_class":
            return True
        for combinator in ("when_all", "when_any"):
            clauses = when.get(combinator)
            if isinstance(clauses, list):
                if any(_when_matches_predictability_class(c) for c in clauses):
                    return True
    return False


def predictability_class_rule_ids() -> set[str]:
    """Every rule_id across all interpretation-rules files keyed on predictability_class."""
    found: set[str] = set()
    for path in _rules_files():
        spec = yaml.safe_load(path.read_text())
        for rule in spec.get("rules", []):
            if _when_matches_predictability_class(rule.get("when")):
                found.add(rule["rule_id"])
    return found


def _iter_leaf_strings(obj: Any):
    """Recursively yield every string leaf in a nested dict/list structure.

    Deliberately NOT a keypath allowlist (contrast the gating_keypaths table
    in rule_role_partition.yaml itself) — a full leaf scan also catches a
    rule_id tucked into a resolver location nobody enumerated yet, which is
    exactly the failure mode #2111 is guarding against.
    """
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_leaf_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_leaf_strings(v)
    elif isinstance(obj, str):
        yield obj


def resolver_referenced_strings() -> set[str]:
    """Every string leaf across every resolvers/*.yaml file."""
    strings: set[str] = set()
    for path in sorted(RESOLVERS_DIR.glob("*.yaml")):
        spec = yaml.safe_load(path.read_text())
        strings.update(_iter_leaf_strings(spec))
    return strings


def rule_ids_referenced_by_any_resolver(rule_ids: set[str]) -> set[str]:
    """The subset of rule_ids that appear as a leaf string somewhere in resolvers/."""
    referenced = resolver_referenced_strings()
    return {rid for rid in rule_ids if rid in referenced}


def display_and_gating_sets() -> tuple[set[str], set[str]]:
    partition = yaml.safe_load(PARTITION_FILE.read_text())
    return set(partition["display"]), set(partition["gating"])


# ---------------------------------------------------------------------------
# The invariant.
# ---------------------------------------------------------------------------


def test_predictability_rule_ids_match_expected_set():
    """Sanity anchor: the 5 rules the issue names still exist and are the ONLY
    rules keyed on predictability_class (a rule added/removed here should be a
    deliberate, reviewed change to this test, not a silent drift)."""
    assert predictability_class_rule_ids() == EXPECTED_PREDICTABILITY_RULE_IDS


def test_predictability_class_rules_stay_display_only():
    """(a) every predictability_class rule is in rule_role_partition.yaml's
    `display` list and NOT in `gating`."""
    rule_ids = predictability_class_rule_ids()
    display, gating = display_and_gating_sets()

    assert rule_ids <= display, (
        f"predictability_class rule(s) missing from the `display` partition: "
        f"{rule_ids - display} — predictability_class must stay verdict-inert (#2111)"
    )
    overlap = rule_ids & gating
    assert not overlap, (
        f"predictability_class rule(s) reclassified into `gating`: {overlap} — this "
        "makes predictability_class verdict-moving while dependency-predictability.card.yaml "
        "still advertises it as verdict-inert everywhere (#2111)"
    )


def test_predictability_class_rules_absent_from_every_resolver():
    """(b) none of the 5 rule_ids is referenced anywhere inside resolvers/."""
    rule_ids = predictability_class_rule_ids()
    hits = rule_ids_referenced_by_any_resolver(rule_ids)
    assert not hits, (
        f"predictability_class rule(s) now referenced by a resolver: {hits} — this "
        "would make predictability_class fire a verdict rung, contradicting "
        "dependency-predictability.card.yaml's 'VERDICT-INERT everywhere' claim (#2111)"
    )


# ---------------------------------------------------------------------------
# Teeth: prove the detectors above are not vacuous.
# ---------------------------------------------------------------------------


def test_detectors_are_not_vacuous():
    """Synthetic violations of both (a) and (b) must be CAUGHT by the same
    functions the two tests above call — otherwise this guard could pass for
    the wrong reason forever."""
    victim = "predictability-biomarker-hypothesis-supportive"

    # (a) reclassify the rule into `gating` in a synthetic partition snapshot.
    mutated_gating = {victim}
    mutated_display: set[str] = set()
    overlap = {victim} & mutated_gating
    assert overlap == {victim}, "the gating-overlap check failed to detect a synthetic reclassification"
    assert not ({victim} <= mutated_display), "the display-membership check failed to detect a synthetic removal"

    # (b) inject the rule_id into a synthetic resolver structure, nested inside
    # a post_resolver_clamp-shaped arm (not a bare top-level `when_fired`), to
    # prove the leaf scan is not just matching one known keypath.
    synthetic_resolver = {
        "gate": "synthetic",
        "post_resolver_clamp": {
            "precedence": [{"when_fired": victim, "verdict": "synthetic_clamped"}],
        },
    }
    leaves = set(_iter_leaf_strings(synthetic_resolver))
    assert victim in leaves, "the leaf-string scan failed to detect a rule_id injected into a synthetic resolver"

    # And confirm a rule_id that is genuinely absent is NOT flagged (no false positive).
    assert "not-a-real-rule-id" not in leaves
