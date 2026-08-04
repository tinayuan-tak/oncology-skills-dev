"""Guard test: the composer's SUB_SKILL_CARDS must not silently DROP a sub-skill's cards.

The bug this catches (found 2026-07-21): `cellline-protein-abundance` (Gygi) was added to
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
    """Regression for the specific #80 bug: cellline-protein-abundance reaches the composed profile."""
    _sub_skills, ssc = _composer_maps()
    assert "cellline-protein-abundance" in ssc["tumor-presence"]


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


# ─────────────────────────────────────────────────────────────────────────────
# STRONGER GUARD (2026-07-24): resolver-DEPENDENCY completeness.
#
# The test above only checks a card is composed SOMEWHERE. That is blind to a real bug found this
# session: `alteration-role` was composed under genomic-alteration-profile but NOT under
# on-target-safety-liability — yet the SAFETY resolver's mutant-selective downgrade rungs
# (`when_all_fired: [<constraint/burden warning>, activating-driver-role-safety-context]`) need
# alteration-role's rule to fire WITHIN the safety sub-skill's fired set. The fan-out scopes each
# sub-skill to ITS OWN SUB_SKILL_CARDS entry (`card_id_filter=SUB_SKILL_CARDS[skill_dir]`), so
# "composed under another gate" does NOT make the rule available where the resolver consumes it.
# Result: the downgrade was silently DEAD in composition (KRAS wrongly held on WT-constraint).
#
# INVARIANT: for each resolver-backed sub-skill, EVERY card whose rule_id the gate's resolver
# references MUST be in that sub-skill's SUB_SKILL_CARDS entry. This is the "available where its
# rules are needed" invariant, stronger than "composed somewhere".
#
# Cross-repo (reads target-contracts resolvers + interpretation-rules) — graceful-skip if absent,
# matching the golden-snapshot test's cross-repo posture.
# ─────────────────────────────────────────────────────────────────────────────
import yaml  # noqa: E402

CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")

# sub-skill dir -> the resolver gate it calls (resolve_verdict_for_gate(fired, "<gate>")).
# Sub-skills with inline verdicts (tumor-presence, tractability-small-molecule) have no resolver
# and are intentionally absent — this guard only covers resolver-backed gates.
_GATE_BY_SUBSKILL = {
    "tumor-selectivity": "selectivity",
    "functional-requirement": "dependency",
    "mechanism-and-pharmacology": "mechanism",
    "genomic-alteration-profile": "genomic_alteration",
    "differentiation-landscape": "differentiation",
    "surface-modality-fit": "surface_modality",
    "on-target-safety-liability": "safety",
    "synthetic-lethal-partners": "synthetic_lethal_partners",
}


def _rule_id_to_card() -> dict[str, str]:
    """{rule_id: card_id} across both interpretation-rules files (a rule's `when.card_id`)."""
    out: dict[str, str] = {}
    for f in (CONTRACTS / "interpretation-rules").glob("*.rules.yaml"):
        doc = yaml.safe_load(f.read_text()) or {}
        for r in doc.get("rules", []):
            when = r.get("when") or {}
            if r.get("rule_id") and isinstance(when, dict) and when.get("card_id"):
                out[r["rule_id"]] = when["card_id"]
    return out


def _resolver_rule_ids(gate: str) -> set[str]:
    """Every rule_id a gate's resolver references (across when_fired / when_any_fired / when_all_fired)."""
    spec = yaml.safe_load((CONTRACTS / "resolvers" / f"{gate}.resolver.yaml").read_text())
    rids: set[str] = set()
    for rung in spec.get("resolve", []):
        if "when_fired" in rung:
            rids.add(rung["when_fired"])
        for key in ("when_any_fired", "when_all_fired"):
            rids.update(rung.get(key, []) or [])
    return rids


@pytest.mark.skipif(not CONTRACTS.exists(), reason="target-contracts repo not checked out (cross-repo guard)")
def test_resolver_dependency_cards_are_in_the_composer_entry():
    """Every card whose rule a gate's resolver references MUST be in that sub-skill's SUB_SKILL_CARDS
    entry — else the resolver rung can never fire in the COMPOSED profile (the alteration-role bug)."""
    _sub_skills, ssc = _composer_maps()
    rid2card = _rule_id_to_card()
    violations = []
    for skill_dir, gate in _GATE_BY_SUBSKILL.items():
        resolver_path = CONTRACTS / "resolvers" / f"{gate}.resolver.yaml"
        if not resolver_path.exists():
            continue
        composed = set(ssc.get(skill_dir, []))
        for rid in _resolver_rule_ids(gate):
            card = rid2card.get(rid)
            if card is None:
                continue  # rule not found in the rules files (may be a pseudo/lens rule) — skip
            if card not in composed:
                violations.append((skill_dir, gate, rid, card))
    assert not violations, (
        "resolver-referenced cards MISSING from the sub-skill's composer entry — the rung can never "
        f"fire in the composed profile: {violations}. Add each card to SUB_SKILL_CARDS[<sub-skill>].")
