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
# SUB_SKILLS / SUB_SKILL_CARDS moved from run.py to tp_fanout.py in the 2026-08-16 god-module split.
COMPOSER = SKILLS / "target-profile" / "scripts" / "tp_fanout.py"

# Cards a sub-skill lists in its run.py CARDS but which the composer DELIBERATELY does not compose
# under that sub-skill. Each entry needs a reason. Keep this SMALL and reviewed — it's the "known
# exception" list, and a new undocumented drop must fail rather than silently join it.
#   key = (sub_skill_dir, card_id) ; value = reason
WAIVED_COMPOSER_OMISSIONS: dict[tuple[str, str], str] = {
    # (2026-07-23, P4 slice 3) The ("surface-modality-fit", "normal-tissue-liability") waiver was
    # RESOLVED: normal-tissue-liability is now composed in SUB_SKILL_CARDS["surface-modality-fit"]
    # (alongside the P4 copy-number-distribution wiring), so it is no longer a real omission and the
    # waiver was removed (the stale-waiver guard would otherwise fail).
    ("tumor-presence", "cellline-rna-distribution-by-subtype"):
        # (2026-08-17, WS-C) DepMap driver-mutation subtype panorama of the cell-line RNA distribution.
        # DISPLAY-ONLY / verdict-inert and COADREAD-only (pattern proof). Deliberately NOT composed into
        # the target-profile fan-out yet: it is a tumor-presence render facet, not a nomination signal,
        # and composing it would add a proof-stage card to every composed profile. Promote to
        # SUB_SKILL_CARDS["tumor-presence"] when it graduates beyond the COADREAD proof.
        "WS-C proof-stage display facet; tumor-presence-only until it graduates past COADREAD.",
}

# REVERSE-direction waiver (2026-08-13, compose-core convergence final stage): a card DELIBERATELY
# composed under a sub-skill's SUB_SKILL_CARDS entry even though it is NOT in that sub-skill's own
# run.py CARDS — a cross-lens ADDITION (the card's rule is attributed to this gate's lens for firing,
# though the standalone skill does not list the card). Currently EMPTY: today every composed card is
# a home card of its entry (composer[dir] ⊆ own(dir).CARDS; the 5 multi-homed cards each compose under
# a lens that DOES own them). Keep SMALL + reviewed — a new undocumented foreign card must FAIL rather
# than silently join here.
#   key = (sub_skill_dir, card_id) ; value = reason
WAIVED_FOREIGN_COMPOSER_CARDS: dict[tuple[str, str], str] = {}


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


def test_composer_entry_composes_no_card_foreign_to_the_sub_skill():
    """REVERSE of the drop guard (compose-core convergence final stage): a card composed under a
    sub-skill's SUB_SKILL_CARDS entry must be a real card in that sub-skill's own run.py CARDS.

    A composed card that is NOT a home card of its entry is a stale / typo'd / mis-attributed entry
    — e.g. left behind after a card RENAME (the composer still names the old id), or a rule attributed
    to a lens whose standalone skill never produces that card (so the fan-out's card_id_filter would
    scope a rule to a card the sub-skill does not read). This closes the OTHER direction of the #80
    silent-drift class. A DELIBERATE cross-lens attribution must be documented in
    WAIVED_FOREIGN_COMPOSER_CARDS rather than pass silently. Holds today (composer[dir] ⊆ own(dir))."""
    sub_skills, ssc = _composer_maps()
    violations = []
    for skill_dir, _short in sub_skills:
        own = _sub_skill_cards(skill_dir)
        if own is None:
            continue
        own_set = set(own)
        for card in ssc.get(skill_dir, []):
            if card in own_set:
                continue
            if (skill_dir, card) in WAIVED_FOREIGN_COMPOSER_CARDS:
                continue
            violations.append((skill_dir, card))
    assert not violations, (
        "cards composed under a SUB_SKILL_CARDS entry but NOT in that sub-skill's own run.py CARDS "
        f"(stale / typo'd / mis-attributed): {violations}. Fix the entry, or — for a deliberate "
        "cross-lens attribution — add a documented WAIVED_FOREIGN_COMPOSER_CARDS entry.")


def test_foreign_composer_waivers_are_still_real():
    """A WAIVED_FOREIGN_COMPOSER_CARDS entry that is now EITHER a home card of the sub-skill OR no
    longer composed under that entry is stale — fail so it gets removed (mirrors the omission-waiver
    staleness guard, keeping the waiver list from masking a later correct wiring)."""
    _sub_skills, ssc = _composer_maps()
    stale = []
    for (skill_dir, card) in WAIVED_FOREIGN_COMPOSER_CARDS:
        own = set(_sub_skill_cards(skill_dir) or [])
        if card in own or card not in ssc.get(skill_dir, []):
            stale.append((skill_dir, card))
    assert not stale, f"stale WAIVED_FOREIGN_COMPOSER_CARDS entries: {stale}"


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
# Only tumor-presence has a genuinely inline verdict (no resolver) and is intentionally absent.
# WHY (reaffirmed 2026-08-11 prod review): the resolver models ONE gate verdict over the flat
# fired-set with no grouping, but tumor-presence ALSO emits per-(measurement, sample_context)
# sub-verdicts (_per_modality_verdicts) that rank within CARD_CONTEXT buckets — a decomposition the
# resolver grammar can't express. Its inline ladder is frozen by the golden + G1/G2/G5 regressions
# in tumor-presence/tests/, not un-migrated debt. See tumor-presence/scripts/run.py::_verdict.
# NOTE (2026-08-10): tractability-small-molecule was MIGRATED to the declarative resolver
# (tractability-small-molecule/scripts/run.py calls resolve_verdict_for_gate(fired,
# "tractability_small_molecule"), resolvers/tractability_small_molecule.resolver.yaml v1.3.0), but
# this map still excluded it — so the measured_potent_ligand rung's card (measured-potency-tractability)
# could be dropped from the composer with the guard staying green. Added. test_gate_map_matches_resolver_calls
# (below) now keeps this map in lockstep with the actual resolve_verdict_for_gate() call sites.
_GATE_BY_SUBSKILL = {
    "tumor-selectivity": "selectivity",
    "functional-requirement": "dependency",
    "mechanism-and-pharmacology": "mechanism",
    "genomic-alteration-profile": "genomic_alteration",
    "differentiation-landscape": "differentiation",
    "tractability-small-molecule": "tractability_small_molecule",
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


def _gate_from_run_py(skill_dir: str) -> str | None:
    """The gate string a sub-skill passes to the shared resolver, or None if the skill has an
    inline verdict (never calls the resolver). Parsed via ast — no live reads. Recognizes both
    the low-level resolve_verdict_for_gate(fired, "<gate>") and the raise-on-missing wrapper
    resolve_or_raise(fired, "<gate>") that most skills' _verdict now delegates to."""
    rp = SKILLS / skill_dir / "scripts" / "run.py"
    if not rp.exists():
        return None
    for node in ast.walk(ast.parse(rp.read_text())):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", None) in ("resolve_verdict_for_gate", "resolve_or_raise")
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            return node.args[1].value
    return None


def test_gate_map_matches_resolver_calls():
    """SELF-AUDIT: _GATE_BY_SUBSKILL must equal the set of gates actually resolved in each sub-skill's
    run.py. This is what prevents the map from silently going stale (the L6 hole, 2026-08-10): when a
    sub-skill is migrated to the declarative resolver, this test fails until the gate is added, so the
    stronger card-availability guard below can never be blind to a resolver-backed sub-skill again.

    Derives ground truth from the resolve_verdict_for_gate(...) call sites, not from a hand list."""
    _sub_skills, _ssc = _composer_maps()
    discovered = {}
    for skill_dir, _short in _sub_skills:
        gate = _gate_from_run_py(skill_dir)
        if gate is not None:
            discovered[skill_dir] = gate
    missing = {k: v for k, v in discovered.items() if k not in _GATE_BY_SUBSKILL}
    stale = {k: _GATE_BY_SUBSKILL[k] for k in _GATE_BY_SUBSKILL if k not in discovered}
    mismatched = {k: (_GATE_BY_SUBSKILL[k], discovered[k])
                  for k in _GATE_BY_SUBSKILL if k in discovered and _GATE_BY_SUBSKILL[k] != discovered[k]}
    assert not (missing or stale or mismatched), (
        "_GATE_BY_SUBSKILL is out of sync with the resolve_verdict_for_gate() call sites.\n"
        f"  resolver-backed sub-skills MISSING from the map (add them): {missing}\n"
        f"  map entries with NO resolver call (remove them): {stale}\n"
        f"  gate-name mismatches (map != run.py): {mismatched}")


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
