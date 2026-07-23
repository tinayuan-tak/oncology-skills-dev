"""Guard test: the composer's SUB_SKILL_CARDS must not silently DROP a sub-skill's cards.

The bug this catches (found 2026-07-21): `protein-abundance-celline` (Gygi) was added to
tumor-presence/run.py CARDS in PR #80 but never to target-profile's SUB_SKILL_CARDS — so the card
reached the standalone skill but was silently dropped from the COMPOSED profile (never seen by the
LLM or scorecard). This is a whole class of drift: a card wired into a sub-skill but not into the
composer.

The invariant, precisely: every card in a sub-skill's own run.py CARDS must be COMPOSED somewhere in
SUB_SKILL_CARDS — either under that sub-skill's own entry (the normal case) OR under another entry
(a deliberate cross-gate attribution, e.g. a dual-homed card credited to its primary gate). A card
in NO composer entry is a silent drop → FAIL, unless it is on the explicit, documented waiver below.

This is Bedrock-free — it only parses the CARDS/SUB_SKILL_CARDS literals via ast (no live reads).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]           # .../skills
COMPOSER = SKILLS / "target-profile" / "scripts" / "run.py"

# Cards a sub-skill lists in its run.py CARDS but which the composer DELIBERATELY does not compose
# under that sub-skill. Each entry needs a reason. Keep this SMALL and reviewed — it's the "known
# exception" list, and a new undocumented drop must fail rather than silently join it.
#   key = (sub_skill_dir, card_id) ; value = reason
WAIVED_COMPOSER_OMISSIONS: dict[tuple[str, str], str] = {
    # (2026-07-23, P4 slice 3) The ("surface-modality-fit", "normal-tissue-liability") waiver was
    # RESOLVED: normal-tissue-liability is now composed in SUB_SKILL_CARDS["surface-modality-fit"]
    # (alongside the P4 copy-number-distribution wiring), so it is no longer a real omission and the
    # waiver was removed (the stale-waiver guard would otherwise fail). No waivers currently needed.
}


def _literal_named(tree_body, name):
    for node in tree_body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if getattr(t, "id", None) == name:
                    return node.value
    return None


def _str_list(node) -> list[str]:
    return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def _composer_maps():
    tree = ast.parse(COMPOSER.read_text())
    ssc_node = _literal_named(tree.body, "SUB_SKILL_CARDS")
    ss_node = _literal_named(tree.body, "SUB_SKILLS")
    sub_skill_cards = {k.value: _str_list(v) for k, v in zip(ssc_node.keys, ssc_node.values)}
    sub_skills = [(e.elts[0].value, e.elts[1].value) for e in ss_node.elts]  # (skill_dir, short)
    return sub_skills, sub_skill_cards


def _sub_skill_cards(skill_dir: str) -> list[str] | None:
    rp = SKILLS / skill_dir / "scripts" / "run.py"
    if not rp.exists():
        return None
    node = _literal_named(ast.parse(rp.read_text()).body, "CARDS")
    return _str_list(node) if node is not None else None


def test_no_sub_skill_card_is_silently_dropped_from_the_composer():
    sub_skills, ssc = _composer_maps()
    all_composed = {c for cards in ssc.values() for c in cards}   # every card the composer composes anywhere
    violations = []
    for skill_dir, _short in sub_skills:
        own = _sub_skill_cards(skill_dir)
        if own is None:
            continue
        for card in own:
            if card in ssc.get(skill_dir, []):
                continue                                   # composed under its own entry — fine
            if card in all_composed:
                continue                                   # composed under another entry — deliberate cross-gate
            if (skill_dir, card) in WAIVED_COMPOSER_OMISSIONS:
                continue                                   # explicitly waived
            violations.append((skill_dir, card))
    assert not violations, (
        "sub-skill cards wired into run.py CARDS but DROPPED from the composer (SUB_SKILL_CARDS) and "
        f"not composed anywhere + not waived: {violations}. Either add the card to SUB_SKILL_CARDS or "
        "add a documented WAIVED_COMPOSER_OMISSIONS entry.")


def test_gygi_card_is_composed_for_tumor_presence():
    """Regression for the specific #80 bug: protein-abundance-celline reaches the composed profile."""
    _sub_skills, ssc = _composer_maps()
    assert "protein-abundance-celline" in ssc["tumor-presence"]


def test_waiver_entries_are_still_real_omissions():
    """A waiver that no longer corresponds to an actual omission is stale — fail so it gets removed
    (prevents the waiver list from silently masking a later correct wiring)."""
    _sub_skills, ssc = _composer_maps()
    all_composed = {c for cards in ssc.values() for c in cards}
    stale = []
    for (skill_dir, card) in WAIVED_COMPOSER_OMISSIONS:
        own = _sub_skill_cards(skill_dir) or []
        # a waiver is real iff the card IS in the sub-skill's CARDS and is NOT composed anywhere
        if card not in own or card in all_composed:
            stale.append((skill_dir, card))
    assert not stale, f"stale WAIVED_COMPOSER_OMISSIONS entries (no longer a real omission): {stale}"
