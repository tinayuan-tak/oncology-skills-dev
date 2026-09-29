"""The three by-subtype arms must spell `subtype_signal` in ONE vocabulary, so a cross-layer read can
join them on token equality.

WHY THIS FILE EXISTS. `subtype_signal` is declared per-arm in
`outputs.summary_fields_record_schemas.per_subgroup_metrics`, and the arms diverged: the tumour RNA arm
used PREFIXED tokens (`subtype_enriched`, ...) while the cell-line RNA and tumour protein arms used BARE
ones (`enriched`, ...). Nothing joined the arms, so nothing was wrong today — and that is exactly the
shape of defect that is invisible until the first consumer compares the tokens across cards, at which
point two arms silently never match and a fall-through is not an error.

WHY THE PREFIXED FORM IS THE TARGET — measured, not preferred:
  * THREE rules key on the prefixed tokens and ZERO key on the bare form (asserted below), so
    prefixing the bare arms touches no rule while de-prefixing the tumour arm would rewrite three
    fired-signal-bearing rules;
  * both bare arms ALREADY declare `subtype_stratification_class` in the prefixed form, so the bare
    per-stratum tokens were the odd ones out WITHIN their own cards;
  * `subtype_restricted` has no bare counterpart to de-prefix onto.

WHAT THESE TESTS PIN. They pin the TARGET vocabulary (every arm declares the three prefixed tokens),
the COVERAGE statement (`subtype_restricted` is tumour-only), and — since the removal step landed
2026-09-18 — the END STATE (no arm declares a bare token). The bare tokens were a TRANSITIONAL union
while the emitters still produced them (removing a token before its producer stops emitting it would
make a method emit rows its own card rejects); that producer migration landed in AM#667 (45eb5d2), so
the bare half was then removed from both enums. `test_the_bare_vocabulary_is_fully_removed` pins that
end state, because the moment the bare half is gone
`test_any_bare_token_is_a_transitional_superset_never_a_swap` goes VACUOUS (its guard body never runs)
— without the end-state pin a regression that re-added a bare token would pass silently.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CARDS = REPO / "cards"
RULES_DIR = REPO / "interpretation-rules"

# The three arms of the subtype layer, keyed by the label used in review discussion.
BY_SUBTYPE_ARMS = {
    "tumour-rna": "tumor-rna-distribution-by-subtype",
    "cellline-rna": "cellline-rna-distribution-by-subtype",
    "tumour-protein": "tumor-protein-distribution-by-subtype",
}
TARGET_VOCABULARY = {"subtype_enriched", "subtype_depleted", "subtype_uniform"}
BARE_VOCABULARY = {"enriched", "depleted", "uniform"}
# Tumour-only, and structurally so: it means "detectable in this stratum while broadly absent pooled",
# which the tumour classifier computes from detectable_fraction + pooled_detectable. The other two
# classifiers are handed two medians and have no detectability input, so declaring this token on them
# would declare a value the producer emits 0x BY CONSTRUCTION.
DETECTABILITY_TOKEN = "subtype_restricted"
DETECTABILITY_ARM = "tumour-rna"


def _signal_spec(card_id: str) -> dict:
    card = yaml.safe_load((CARDS / f"{card_id}.card.yaml").read_text())
    schemas = (card.get("outputs") or {}).get("summary_fields_record_schemas") or {}
    per_subgroup = schemas.get("per_subgroup_metrics") or {}
    return per_subgroup.get("subtype_signal") or {}


def _declared(card_id: str) -> set:
    return set(_signal_spec(card_id).get("enum") or [])


def _subtype_signal_rules() -> list:
    """Every rule on EVERY axis whose in_record keys on subtype_signal, with the card it names.

    Scans all rule files rather than the one axis that has them today: an arm added on another axis is
    exactly the case where a single-file scan would report a clean result for the wrong reason.
    """
    out = []
    for path in sorted(RULES_DIR.glob("*.rules.yaml")):
        doc = yaml.safe_load(path.read_text()) or {}
        for rule in doc.get("rules") or []:
            in_record = (rule.get("when") or {}).get("in_record")
            if isinstance(in_record, dict) and "subtype_signal" in in_record:
                out.append(
                    {
                        "axis_file": path.name,
                        "rule_id": rule.get("rule_id"),
                        "card_id": (rule.get("when") or {}).get("card_id"),
                        "signal": in_record["subtype_signal"],
                    }
                )
    return out


def test_all_three_arms_declare_a_subtype_signal_enum():
    """ANTI-VACUITY, and it runs first on purpose: every assertion below quantifies over these three
    cards, so if a card were renamed or the field moved out of per_subgroup_metrics, the other tests
    would quantify over an empty or partial set and pass while measuring nothing."""
    missing = {label: cid for label, cid in BY_SUBTYPE_ARMS.items() if not _declared(cid)}
    assert not missing, (
        f"no per_subgroup_metrics.subtype_signal enum found for {missing} — either the card was "
        "renamed or the field moved, and every other test in this file would then be vacuous"
    )
    assert len(BY_SUBTYPE_ARMS) == 3, "the subtype layer is three arms; update this file if that changes"


def test_every_arm_declares_the_prefixed_target_vocabulary():
    """The joinable namespace. A consumer comparing tokens across arms needs the same three strings to
    be legal on each; this is the assertion the alignment exists to make true."""
    for label, card_id in BY_SUBTYPE_ARMS.items():
        declared = _declared(card_id)
        assert TARGET_VOCABULARY <= declared, (
            f"{label} ({card_id}) is missing {sorted(TARGET_VOCABULARY - declared)} from its "
            f"subtype_signal enum {sorted(declared)} — a cross-arm join on token equality cannot "
            "match a token this arm may not emit"
        )


def test_the_detectability_token_is_declared_only_where_it_can_be_produced():
    """`subtype_restricted` is a COVERAGE statement, not an oversight. Widening it to an arm whose
    classifier has no detectability input would declare a token that arm emits 0x by construction —
    an absence a consumer is entitled to read as a measurement."""
    for label, card_id in BY_SUBTYPE_ARMS.items():
        declared = _declared(card_id)
        if label == DETECTABILITY_ARM:
            assert DETECTABILITY_TOKEN in declared, (
                f"{card_id} must keep {DETECTABILITY_TOKEN}: three interpretation rules key on it"
            )
        else:
            assert DETECTABILITY_TOKEN not in declared, (
                f"{card_id} declares {DETECTABILITY_TOKEN}, but its classifier is handed two medians "
                "and no detectability input, so it cannot emit that token — declaring it makes a "
                "producer-side impossibility look like a measurable-but-never-seen value"
            )


def test_any_bare_token_is_a_transitional_superset_never_a_swap():
    """The migration is add -> consume -> remove. A bare token is legal ONLY alongside the prefixed
    form, so no arm can be left speaking bare-only (which is what a straight rename would produce if
    it were applied to the card before the method). Passes unchanged once the bare half is removed."""
    for label, card_id in BY_SUBTYPE_ARMS.items():
        declared = _declared(card_id)
        if declared & BARE_VOCABULARY:
            assert TARGET_VOCABULARY <= declared, (
                f"{label} ({card_id}) declares bare {sorted(declared & BARE_VOCABULARY)} without the "
                "full prefixed vocabulary — a swap, not a transitional union"
            )


def test_every_rule_keys_on_a_token_its_own_card_declares():
    """THE CONSUMER LINK, and the assertion that makes the removal step safe to attempt: a rule's
    in_record value must be declared by the card the rule names. Removing a token some rule keys on
    reds here instead of silently producing a rule that can never match."""
    rules = _subtype_signal_rules()
    assert len(rules) >= 3, (
        f"expected at least the three subtype-expression context rules, found {len(rules)} — a scan "
        "that finds nothing would make this test pass while checking no rule at all"
    )
    for rule in rules:
        declared = _declared(rule["card_id"])
        assert declared, f"{rule['rule_id']} names card {rule['card_id']}, which declares no subtype_signal enum"
        assert rule["signal"] in declared, (
            f"{rule['rule_id']} ({rule['axis_file']}) keys on subtype_signal={rule['signal']!r}, which "
            f"{rule['card_id']} does not declare {sorted(declared)} — the rule can never match"
        )


def test_no_rule_keys_on_the_bare_vocabulary():
    """The measured basis for choosing the prefixed direction. If this ever fails, the migration's
    'touches no rule' premise is void and the bare tokens have become verdict-bearing somewhere."""
    offenders = [r for r in _subtype_signal_rules() if r["signal"] in BARE_VOCABULARY]
    assert not offenders, (
        f"{[r['rule_id'] for r in offenders]} key on bare subtype_signal tokens — the alignment "
        "direction assumed zero rules do, so removing the bare half would erase these rules' match"
    )


def test_the_bare_vocabulary_is_fully_removed():
    """END STATE, added when the removal step landed 2026-09-18. The producer stopped emitting the bare
    tokens in AM#667 (45eb5d2), so no arm may declare them any longer. This is the assertion that
    `test_any_bare_token_is_a_transitional_superset_never_a_swap` can no longer make: its guard body
    stops running once the bare half is gone, so without this pin a re-introduced bare token would slip
    through green."""
    offenders = {
        label: sorted(_declared(card_id) & BARE_VOCABULARY)
        for label, card_id in BY_SUBTYPE_ARMS.items()
        if _declared(card_id) & BARE_VOCABULARY
    }
    assert not offenders, (
        f"{offenders} still declare bare subtype_signal tokens — the migration removed them once the "
        "producer (AM#667) stopped emitting them, so a bare token here is now a regression, not a "
        "transitional union"
    )
