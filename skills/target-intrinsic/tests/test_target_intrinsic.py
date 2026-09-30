"""Guards for the target-intrinsic subskill: CARDS↔SKILL.md consistency, the descriptive-no-verdict
contract, and that every consumed card is genuinely tier:target (indication-independent).

S3-free — parses the run.py CARDS literal + the SKILL.md composition + the card tier fields."""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent

from _skills_common.paths import target_contracts_root  # noqa: E402

# Env-aware (TARGET_CONTRACTS_ROOT, else the canonical sibling checkout). The former
# `SKILLS_ROOT.parent.parent / "…target-contracts"` derivation resolved to /tmp/… from a git WORKTREE,
# so the grain guard below silently SKIPPED in exactly the environment every workstream runs in.
CONTRACTS = target_contracts_root()


def _cards_from_runpy() -> list[str]:
    tree = ast.parse((SKILL_DIR / "scripts" / "run.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "CARDS":
                    return [
                        e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    ]
    raise AssertionError("CARDS literal not found in run.py")


def _skill_md_composition() -> dict:
    txt = (SKILL_DIR / "SKILL.md").read_text()
    fm = yaml.safe_load(txt.split("---")[1])
    return fm["composition"]


def test_cards_match_skill_md():
    """run.py CARDS must equal SKILL.md composition.cards_used (the standard consistency invariant)."""
    assert set(_cards_from_runpy()) == set(_skill_md_composition()["cards_used"])


def test_measurement_types_parity():
    """DATA_TO_SKILL_CONTRACT Rule 3: every consumed card pulls one measurement_type, so
    measurement_types_pulled must have the SAME cardinality as cards_used. Guards the drift that
    shipped when target-development-level was added to cards_used but NOT to
    measurement_types_pulled (18 vs 19), uncaught because test_cards_match_skill_md only checks
    CARDS↔cards_used."""
    comp = _skill_md_composition()
    n_cards = len(comp["cards_used"])
    n_mtypes = len(comp["measurement_types_pulled"])
    assert n_mtypes == n_cards, (
        f"measurement_types_pulled ({n_mtypes}) != cards_used ({n_cards}) — each consumed card must "
        f"declare its pulled measurement_type (DATA_TO_SKILL_CONTRACT Rule 3)."
    )


def test_descriptive_no_verdict_contract():
    """target-intrinsic is DESCRIPTIVE: synthesis: none, empty rules_scope (no nomination — that is
    indication-conditioned). Pins the one-directional-gate-at-the-grain-level design."""
    comp = _skill_md_composition()
    assert comp["synthesis"] == ["none"]
    assert comp.get("rules_scope", []) == []
    # run.py must pass verdict_fn=None
    assert "verdict_fn=None" in (SKILL_DIR / "scripts" / "run.py").read_text()


def test_all_cards_are_indication_independent():
    """Every consumed card must be tier:target (or blank/pan-cancer) — NOT tier:indication or subtype.
    A tier:indication card in a target-intrinsic skill would be a grain violation (it needs an
    indication this skill doesn't take). Skips gracefully if target-contracts isn't checked out."""
    cards_dir = CONTRACTS / "cards"
    if not cards_dir.is_dir():
        import pytest

        pytest.skip("target-contracts not checked out alongside")
    forbidden = {"indication", "subtype"}
    violations = []
    for cid in _cards_from_runpy():
        spec_path = cards_dir / f"{cid}.card.yaml"
        assert spec_path.is_file(), f"card spec missing: {cid}"
        tier = (yaml.safe_load(spec_path.read_text()) or {}).get("tier")
        if tier in forbidden:
            violations.append((cid, tier))
    assert not violations, (
        f"target-intrinsic consumes indication/subtype-grain card(s): {violations} — "
        f"a target-intrinsic skill must only consume tier:target (indication-independent) cards."
    )


def _cards_read_in_headline() -> set[str]:
    """Card_ids surfaced in the dossier, AST-parsed from the _HEADLINE_SPEC table (element [1] of each
    (headline_key, card_id, card_field) tuple). target-intrinsic has NO verdict spine, so this table
    is the ONLY place a card's signal reaches output — a card in CARDS but absent here resolves
    invisibly (resolved, counted in cards_available, but its data never surfaces). AST parse (vs the
    former g(\"...\") regex) is structural: it reads the actual table, not source text."""
    tree = ast.parse((SKILL_DIR / "scripts" / "run.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_HEADLINE_SPEC" for t in node.targets
        ):
            out: set[str] = set()
            for elt in node.value.elts:  # each row: (key, card_id, field)
                if isinstance(elt, (ast.Tuple, ast.List)) and len(elt.elts) >= 2:
                    cid = elt.elts[1]
                    if isinstance(cid, ast.Constant) and isinstance(cid.value, str):
                        out.add(cid.value)
            return out
    raise AssertionError("_HEADLINE_SPEC literal not found in run.py")


def test_every_card_is_surfaced_in_headline():
    """DRIFT GUARD: every card in CARDS must appear in the _HEADLINE_SPEC table.

    A descriptive skill (verdict_fn=None) has no ladder to force a card's signal into output, so
    a card added to CARDS but never surfaced resolves INVISIBLY — it costs a live read and
    inflates cards_available, but its data is silently dropped. That is exactly what happened to
    domain-modality-relevance (in CARDS but unread until 2026-08-08). This asserts it
    cannot recur: CARDS ⊆ cards-in-_HEADLINE_SPEC."""
    cards = set(_cards_from_runpy())
    read = _cards_read_in_headline()
    unsurfaced = cards - read
    assert not unsurfaced, (
        f"card(s) in CARDS but absent from _HEADLINE_SPEC: {sorted(unsurfaced)} — "
        f"they resolve invisibly (counted in cards_available but their signal never surfaces). "
        f'Add a ("<headline_key>", "<card-id>", "<field>") row to _HEADLINE_SPEC, or drop the card from CARDS.'
    )
