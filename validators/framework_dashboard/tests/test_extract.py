"""CI-safe unit tests for framework_dashboard.extract.

These exercise the extraction on the IN-REPO target-contracts artifacts (cards,
interpretation-rules, resolvers) only — they do NOT require the sibling skills /
data-catalog checkouts, so they run under the checkout-only contracts-validate CI
(mirroring framework_health's --self-check philosophy).
"""
from pathlib import Path

import pytest

from validators.framework_dashboard import extract

TC = Path(__file__).resolve().parents[3]  # …/target-contracts


def test_parse_all_cards():
    cards = list((TC / "cards").glob("*.card.yaml"))
    assert cards, "no cards found — repo layout changed?"
    for p in cards:
        c = extract.parse_card(p)
        assert c["card_id"], f"{p.name}: missing card_id"
        # outputs/methods/required_inputs are always lists (never None)
        assert isinstance(c["summary_fields"], list)
        assert isinstance(c["methods"], list)
        assert isinstance(c["required_inputs"], list)


def test_resolvers_and_rules_link():
    rules_by_card, rule_index = extract.parse_rules(TC)
    resolvers, rule_to_verdicts = extract.parse_resolvers(TC)
    assert resolvers, "no resolvers parsed"
    # every gate declares at least one verdict
    for gate, r in resolvers.items():
        assert r["verdicts"], f"resolver {gate} has no verdicts"
    # at least some rules feed a resolver verdict (the card→rule→verdict chain exists)
    assert rule_to_verdicts, "no rule→verdict wiring found"
    # a known load-bearing chain: pan-essential-killer → dependency verdict
    if "pan-essential-killer" in rule_index:
        assert any(v["gate"] == "dependency" for v in rule_to_verdicts.get("pan-essential-killer", []))


def test_indication_family_detection():
    # a synthetic catalog index with an indication-parameterized family
    idx = {f"{ind}-dge-tumor-vs-normal-sensitivity-v1": {} for ind in ("coadread", "luad", "brca", "paad")}
    fam = extract.detect_indication_family("coadread-dge-tumor-vs-normal-sensitivity-v1", idx)
    assert fam["is_family"] and fam["count"] == 4
    # a non-indication product is not a family
    assert not extract.detect_indication_family("depmap-consortium-26q1", idx)["is_family"]


def test_gap_notes_categorized():
    # uncataloged refs resolve to a categorized gap, not a bare miss
    r = extract.resolve_dataset("tempus-rwd-stratified-expression", {})
    assert r["in_catalog"] is False
    assert r["gap_category"] == "commercial"
    assert r["gap_note"]


@pytest.mark.parametrize("gate", ["dependency", "safety", "genomic_alteration"])
def test_expected_resolvers_present(gate):
    resolvers, _ = extract.parse_resolvers(TC)
    assert gate in resolvers, f"expected resolver gate '{gate}' missing"
