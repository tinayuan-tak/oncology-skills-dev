"""cis-coherence — every DECLARED class/direction token is READ by a rule, and no rule reads an
undeclared one.

The bug this makes impossible (the immune-context `lymphoid_denominator_unreliable` failure mode,
reproduced on this axis by the round-2 fix package): a card gains a vocabulary token and the reader
gains the ability to emit it, while the rule corpus knows only the old tokens — so the token reaches the
skill, fires nothing, and collapses onto a bare `insufficient` indistinguishable from "no data". This
round added three such tokens at once (`cis_dosage_direction`'s pair and `silencing_lineage_confounded`),
which is exactly the situation where declaring is easy and interpreting gets forgotten.

Read against the LIVE cards + LIVE rules corpus on purpose: the claim is that these real files agree, and
a hermetic fixture would pass while the real pair drifted.

`data_unavailable` and the two untestable-panel tokens are the deliberate exceptions — they are honest
ABSTENTIONS whose whole purpose is to fire nothing and let the resolver fall to its default.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
RULES_DIR = REPO / "interpretation-rules"

# (card_id, field) -> tokens that fire NO rule by design, with the reason they are exempt.
_ABSTENTION_TOKENS = {
    ("cis-feature-expression-coherence", "cis_dosage_class"): {
        "data_unavailable",  # framework-wide "we could not read it"
        "cn_invariant_panel",  # untestable: no CN variation → the resolver must abstain, not claim
    },
    ("cellline-methylation-expression-coherence", "methylation_silencing_class"): {
        "data_unavailable",
        "methylation_invariant_panel",  # untestable: uniformly (un)methylated panel
    },
    ("cis-feature-expression-coherence", "cis_dosage_direction"): set(),
}

_CARD_FILE = {
    "cis-feature-expression-coherence": "cis-feature-expression-coherence.card.yaml",
    "cellline-methylation-expression-coherence": "cellline-methylation-expression-coherence.card.yaml",
}


def _declared(card_id: str, field: str) -> set[str]:
    card = yaml.safe_load((REPO / "cards" / _CARD_FILE[card_id]).read_text())
    vocab = ((card.get("outputs") or {}).get("summary_fields_vocabulary") or {}).get(field)
    assert vocab, f"{_CARD_FILE[card_id]} declares no `{field}` vocabulary — card/reader drift"
    return set(vocab)


def _rule_tokens(card_id: str, field: str) -> dict[str, str]:
    """{token: rule_id} for every rule keyed on (card_id, field). Handles both `equals:` and `in:`."""
    out: dict[str, str] = {}
    for path in sorted(RULES_DIR.glob("*.rules.yaml")):
        doc = yaml.safe_load(path.read_text()) or {}
        for rule in doc.get("rules") or []:
            when = rule.get("when") or {}
            if when.get("card_id") != card_id or when.get("field") != field:
                continue
            tokens = [when["equals"]] if "equals" in when else list(when.get("in") or [])
            for tok in tokens:
                out[tok] = rule.get("rule_id")
    return out


def test_every_declared_token_is_read_by_a_rule():
    for (card_id, field), exempt in _ABSTENTION_TOKENS.items():
        declared = _declared(card_id, field) - exempt
        covered = set(_rule_tokens(card_id, field))
        assert declared <= covered, (
            f"{card_id}.{field} tokens declared on the card but read by NO rule: "
            f"{sorted(declared - covered)} — such a token reaches the skill, fires nothing, and is "
            f"indistinguishable from missing data"
        )


def test_no_rule_reads_a_token_the_card_does_not_declare():
    """The other direction: a rule keyed on a token no reader can emit is dead code that reads as
    coverage. This is what a token RENAME leaves behind."""
    for card_id, field in _ABSTENTION_TOKENS:
        declared = _declared(card_id, field)
        for token, rule_id in _rule_tokens(card_id, field).items():
            assert token in declared, (
                f"rule {rule_id} reads {card_id}.{field}=={token}, which the card does not declare — "
                f"dead rule (renamed or removed token?)"
            )


def test_direction_tokens_are_read_by_rules_the_resolver_actually_uses():
    """Coverage is not enough for the direction pair: the whole point of adding it was to let the resolver
    SEPARATE amplification from deletion coupling. A direction rule that no rung references would be
    interpretation debt dressed up as a fix, so pin that both tokens' rules appear in a rung."""
    spec = yaml.safe_load((REPO / "resolvers" / "cis_coherence.resolver.yaml").read_text())
    referenced: set[str] = set()
    for rung in spec.get("resolve") or []:
        for key in ("when_fired", "when_any_fired", "when_all_fired"):
            val = rung.get(key)
            if isinstance(val, str):
                referenced.add(val)
            elif isinstance(val, list):
                referenced.update(val)
    direction_rules = set(_rule_tokens("cis-feature-expression-coherence", "cis_dosage_direction").values())
    assert direction_rules, "no rule reads cis_dosage_direction at all"
    assert direction_rules <= referenced, (
        f"direction rules that no resolver rung consumes: {sorted(direction_rules - referenced)} — the "
        f"field would be measured and interpreted but change no verdict"
    )
