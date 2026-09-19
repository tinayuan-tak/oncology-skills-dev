"""C5: the cross-stratum delta cut has ONE home — the card's `thresholds:` block.

`run.py` hardcoded `_MEANINGFUL_SUBGROUP_DELTA = 0.10` under a comment claiming it mirrored
subgroup-stratified-dependency's `meaningful_subgroup_delta`, which declares **0.3** — a 3x drift.

Why no existing test caught it: the only fixture that exercises the label
(test_dependency_verdict_by_scope.py::test_subtype_verdict_present_in_panorama_block) uses
`cross_subgroup_delta_dependency: 0.5`, which is above BOTH cuts. The parameter was unpinned, so the
suite was insensitive to its value — a green that could not fail. The behavioural test below fixes that
by probing INSIDE the gap between the old hardcode and the card's cut.

Display-only: this label never touches a resolver rung, so the fix is verdict-inert. It still matters —
`subgroup_specific_dependency` is the notable claim, and the 0.10 cut let a 0.15 Chronos spread assert
subgroup-specific dependency the card would call uniform.
"""

from __future__ import annotations

from pathlib import Path

from _skills_common.evidence_salience import contract_threshold
from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent

M = load_run_py(SKILL_DIR, "_fr_run_delta")

CARD_ID = "subgroup-stratified-dependency"
THRESHOLD_KEY = "meaningful_subgroup_delta"

# The value C5 removed. Named here for ONE purpose: to prove the behavioural probe below lands in the
# gap between it and the card's cut. Never read as a cut.
_OLD_HARDCODE = 0.10


def _card_cut():
    """The card's declared cut, with the anti-vacuity assert inline.

    A `if cut is not None:`-style guard would let every assertion in this module evaporate whenever the
    contracts sibling is unresolvable — which is exactly how a drift guard degrades into a silent pass.
    The sibling IS resolvable in CI (skills-validate checks out target-contracts) and in any adjacent
    local checkout, so demanding resolution is the strictly stronger instrument.
    """
    cut = contract_threshold(CARD_ID, THRESHOLD_KEY)
    assert cut is not None, (
        f"{CARD_ID}.{THRESHOLD_KEY} did not resolve — the contracts sibling is missing, so this guard "
        "cannot see the declared cut and must fail rather than pass vacuously"
    )
    return cut


def _pattern_for(monkeypatch, delta):
    """The display pattern label for a given cross-subgroup delta, with two MEASURED strata."""

    def _stub_resolve_cards(card_ids, target, indication, **kw):
        return [
            {
                "card_id": CARD_ID,
                "summary": {
                    "cross_subgroup_delta_dependency": delta,
                    "per_subgroup_metrics": [
                        {
                            "stratum": "MSI_H",
                            "class": "strong_dependency",
                            "evidence_state": "measured",
                            "median_chronos": -0.9,
                            "subgroup_n": 30,
                        },
                        {
                            "stratum": "MSS",
                            "class": "not_dependent",
                            "evidence_state": "measured",
                            "median_chronos": -0.9 + delta,
                            "subgroup_n": 106,
                        },
                    ],
                },
            }
        ]

    # monkeypatch the RESOLVING namespace (run.py's own binding), not the defining module
    monkeypatch.setattr(M, "resolve_cards", _stub_resolve_cards)
    pan = M._resolve_dependency_subtype_panorama("KRAS", "COADREAD", ["MSI_H", "MSS"])
    return pan["subtype_dependency_panorama"]["subtype_dependency_pattern"]


def test_meaningful_subgroup_delta_is_single_sourced_from_the_card():
    cut = _card_cut()
    assert M._MEANINGFUL_SUBGROUP_DELTA == cut, (
        f"run.py's effective cut {M._MEANINGFUL_SUBGROUP_DELTA} != the card's declared {cut}"
    )
    # contract_threshold() is fail-soft to None, so the fallback literal is a second copy BY NECESSITY.
    # Pin it to the card: if someone retunes the card, this reds instead of the fallback silently
    # re-opening the very drift C5 was.
    assert M._MEANINGFUL_SUBGROUP_DELTA_FALLBACK == cut, (
        f"the declared fallback {M._MEANINGFUL_SUBGROUP_DELTA_FALLBACK} has drifted from the card's {cut}"
    )


def test_the_single_source_is_load_bearing_not_decorative(monkeypatch, tmp_path):
    """Prove run.py READS the card rather than merely holding the right literal.

    Today the declared fallback equals the card's value, so every assertion above is satisfied even if
    the card read is deleted outright (measured: that mutant SURVIVED). Only re-pointing the contracts
    root at a card with a DIFFERENT cut can tell the two apart. `contract_threshold` imports
    `target_contracts_root` INSIDE the function body, so patching the module attribute is what the
    lookup actually resolves.
    """
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / f"{CARD_ID}.card.yaml").write_text(f"thresholds:\n  {THRESHOLD_KEY}: 0.77\n")

    import _skills_common.paths as paths_mod

    monkeypatch.setattr(paths_mod, "target_contracts_root", lambda: tmp_path)
    contract_threshold.cache_clear()  # the helper is lru_cached; a stale entry would mask the re-point
    try:
        probe_mod = load_run_py(SKILL_DIR, "_fr_run_delta_repointed")
        assert probe_mod._MEANINGFUL_SUBGROUP_DELTA == 0.77, (
            "run.py did not follow the card's declared cut — the value is a literal, not single-sourced"
        )
    finally:
        contract_threshold.cache_clear()  # never leak the synthetic root into a sibling test


def test_pattern_label_uses_the_cards_cut_not_the_old_hardcode(monkeypatch):
    cut = _card_cut()
    probe = cut / 2.0
    # The probe must sit in the gap [old hardcode, card cut). Outside it, this test would pass against
    # the PRE-FIX code too and would prove nothing about the drift.
    assert _OLD_HARDCODE <= probe < cut, (
        f"probe {probe} is not inside the regression gap [{_OLD_HARDCODE}, {cut}) — re-pick it"
    )
    assert _pattern_for(monkeypatch, probe) == "uniform_across_subgroups", (
        f"delta={probe} is below the card's cut {cut} and must read uniform; reading it as "
        "subgroup-specific is the C5 drift"
    )
    # Anti-vacuity: the notable label must still be REACHABLE above the cut, or the assertion above is
    # satisfiable by a classifier that always answers 'uniform'.
    assert _pattern_for(monkeypatch, cut * 2.0) == "subgroup_specific_dependency"
