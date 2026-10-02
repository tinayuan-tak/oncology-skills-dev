"""L1-A1 (SK#2491, epic #1937 thread A1): genomic's L2a `source_properties` goes through the SHARED
`source_properties_core` typed-anchor path, so its anchors carry the disposition its own ledger declares.

WHAT WAS WRONG BEFORE. `genomic_claims` hand-rolled the recipe loop and a `_typed_genomic_anchor` that
emitted the bare {field, value, scale} envelope, justified by a comment asserting
genomic-alteration-profile "carries no field-disposition ledger". That stopped being true when the
reviewed ledger landed (`skills/genomic-alteration-profile/field_disposition.yaml`, #1891, 2026-09-27):
the role was DECLARED and silently DROPPED on every emitted anchor. This file is the guard that it is
sourced from the ledger and keeps following it.

THE CLAIMS, each of which can fail:

  1. EXTRACTION EQUIVALENCE — the migrated map equals the hand-rolled map modulo the additive
     `semantic_role` key: same entries in the same order, same `property_field` / `property` /
     `comparability` / conditional `context` / `reliability`, same anchor list and anchor key ORDER. The
     hand-rolled reference is reconstructed HERE from the recipe table + the card summary (not a stored
     copy of the producer's own output), so it fails the moment the shared helper diverges in any key
     other than the one the owner ruled additive (SK#2491 re-ruled acceptance criterion).
  2. ROLE IS SOURCED, NOT HARDCODED — the emitted `semantic_role` equals the role re-read from the
     ledger FILE for that (card_id, field), and when the ledger row is MUTATED the emitted value
     follows. A fixture of literals copied out of today's ledger could never fail (a fixture of derived
     values can never fail — the mutation is the teeth).
  3. REACH IS DECLARED AND CARRIED — genomic's ledger now declares the reach axis (SK#1525) on every row
     (A2/A4, epic #1937; census-derived 2026-10-02), so `reach_map` is non-empty and every emitted anchor
     carries the ledger-declared `interpretation_reach`. This was a PURE data change in the ledger: the
     anchor-typing code here was already wired, proven before the data landed by pointing the SAME call at
     a synthetic ledger that declared it. The positive assertion is paired with a reach-strip mutation so
     it cannot pass by fabricating the axis — the strip must drop it from the anchor.
  4. RELIABILITY FACET PRESERVED — the typed `reliability` facet (#2306) genomic already emitted on the
     hand-rolled path survives the migration AND stays sourced from each recipe's own spec: mutating a
     recipe's `n_effective_anchor` moves `n_effective`.

Identity note: a role is per (SKILL, card_id, field) — the same card field is a different role in a
different skill's ledger — so every assertion below reads genomic-alteration-profile's OWN ledger.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from _skills_common.field_disposition_ledger import LEDGER_NAME, iter_rows, load_ledger
from _skills_common.genomic_claims import (
    _GENOMIC_ANCHOR_SCALE,
    _GENOMIC_SKILL,
    _SOURCE_PROPERTY_RECIPES_GENOMIC,
    _source_properties,
)
from _skills_common.source_properties_core import build_source_properties, reach_map

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
LEDGER_PATH = SKILL_DIR / LEDGER_NAME
FIXTURES = SKILL_DIR / "tests" / "fixtures"


def _ledger_roles() -> dict:
    """{(card_id, field): role} re-read from the ledger FILE — never a literal copied into this test."""
    return {(cid, field): spec.get("role") for cid, field, spec in iter_rows(load_ledger(LEDGER_PATH))}


def _synthetic_cards() -> dict:
    """A cards-by-id map populating EVERY `property_field` / anchor / `context` field the recipe table
    names, so the equivalence claim is measured over the FULL shape (the frozen dossiers resolve all
    seven sources but not every anchor)."""
    cards: dict = {}
    for recipe in _SOURCE_PROPERTY_RECIPES_GENOMIC:
        summ = cards.setdefault(recipe["card_id"], {})
        summ[recipe["property_field"]] = "synthetic_class_token"
        for i, field in enumerate(recipe["anchors"]):
            summ[field] = 1.5 + i
        for field in recipe["context"]:
            summ[field] = f"ctx::{field}"
    return cards


def _discover_dossiers():
    """The frozen dossiers this module DISCOVERS by glob — the half of the subject set that can empty."""
    return sorted(FIXTURES.glob("*.yaml"))


# Evaluated at import, exactly like the parametrize below, so the floor test pins the SAME set the
# parametrized claims consume (see test_the_discovered_card_map_corpus_is_not_vacuous).
_DISCOVERED_DOSSIERS = _discover_dossiers()


def _card_maps():
    """The synthetic all-fields map + every discovered dossier (real card summaries, keyed by card_id)."""
    yield "synthetic_all_fields", _synthetic_cards()
    for fx in _DISCOVERED_DOSSIERS:
        yield fx.stem, yaml.safe_load(fx.read_text())


def _strip_roles(props: dict) -> dict:
    """Strip the ADDITIVE disposition-typing keys (`semantic_role` from the role axis AND
    `interpretation_reach` from the reach axis, SK#1525) so the remainder can be compared byte-for-byte
    against the pre-migration hand-rolled builder. Both axes are additive beside the {field, value, scale}
    envelope; everything else must be identical."""
    out = copy.deepcopy(props)
    for entry in out.values():
        for anchor in entry["anchors"]:
            anchor.pop("semantic_role", None)
            anchor.pop("interpretation_reach", None)
    return out


def _hand_rolled_reference(cards: dict) -> dict:
    """The PRE-migration builder, reconstructed from the recipe table + card summaries: the exact shape
    `genomic_claims` emitted before #2491 (bare {field, value, scale} anchors, no ledger typing). Not a
    stored copy of the producer's output, so this is an independent reference."""
    out: dict = {}
    for recipe in _SOURCE_PROPERTY_RECIPES_GENOMIC:
        summ = cards.get(recipe["card_id"], {}) or {}
        prop = summ.get(recipe["property_field"])
        if not prop or prop == "data_unavailable":
            continue
        entry = {
            "card_id": recipe["card_id"],
            "property_field": recipe["property_field"],
            "property": prop,
            "anchors": [
                {"field": f, "value": summ[f], "scale": _GENOMIC_ANCHOR_SCALE.get(f, "raw")}
                for f in recipe["anchors"]
                if summ.get(f) is not None
            ],
            "comparability": dict(recipe["comparability"]),
        }
        context = {f: summ[f] for f in recipe["context"] if summ.get(f) is not None}
        if context:
            entry["context"] = context
        from _skills_common.reliability import _derive_reliability

        entry["reliability"] = _derive_reliability(entry["anchors"], recipe["reliability"])
        out[recipe["name"]] = entry
    return out or None


# ── 0. DENOMINATOR FIRST: the discovered subject set cannot go vacuous ─────────────────────────────────


def test_the_discovered_card_map_corpus_is_not_vacuous():
    """`_card_maps` DISCOVERS half its subject set by globbing `tests/fixtures/*.yaml`, and it feeds the
    parametrize below. If that glob ever returns nothing (fixtures renamed/moved/pruned), every
    equivalence case would silently stop running and this module would pass green-by-vacuity — the exact
    defect `skills/tests/test_discovery_guards_carry_floors.py` ratchets against. Floor the DISCOVERED set
    itself, at counts justified by the committed corpus and the recipe table:

      * >= 3 cases     — the synthetic all-fields map + the TWO frozen dossiers (kras, braf) committed in
                         `tests/fixtures/` (the same pair `test_genomic_replay.py` replays);
      * >= 2 globbed    — so the glob half specifically cannot collapse to zero while the hand-written
                         synthetic half keeps the count up;
      * 7 properties    — every recipe in `_SOURCE_PROPERTY_RECIPES_GENOMIC` resolves on every case, so an
                         equivalence case can never shrink to a one-entry comparison unnoticed;
      * >= 20 anchors   — the measured typed-anchor denominator (22 on the synthetic map, 20 on each
                         dossier); the role assertions below are only as strong as this count.
    """
    assert len(_DISCOVERED_DOSSIERS) >= 2, (
        f"the dossier glob found {len(_DISCOVERED_DOSSIERS)} fixtures under {FIXTURES} (expected >= 2)"
    )
    cases = dict(_card_maps())
    assert len(dict(_card_maps())) >= 3, (
        f"only {len(cases)} card maps discovered — the parametrized claims would thin out"
    )
    n_recipes = len(_SOURCE_PROPERTY_RECIPES_GENOMIC)
    assert n_recipes >= 7, f"the recipe table declares only {n_recipes} properties"
    for name, cards in cases.items():
        emitted = _source_properties(cards)
        assert emitted and len(emitted) == n_recipes, (
            f"{name}: {len(emitted or {})}/{n_recipes} source properties resolved — this case no longer "
            f"exercises the full shape"
        )
        n_anchors = sum(len(e["anchors"]) for e in emitted.values())
        assert n_anchors >= 20, f"{name}: only {n_anchors} retained anchors (expected >= 20)"


# ── 1. extraction equivalence: identical modulo the additive `semantic_role` ───────────────────────────


@pytest.mark.parametrize("case", [c[0] for c in _card_maps()])
def test_migrated_map_equals_hand_rolled_modulo_additive_semantic_role(case):
    """json.dumps comparison — so key INSERTION ORDER is part of the claim, at both the entry and the
    anchor level. Everything except the added disposition-typing keys (`semantic_role` from the role axis
    AND, since A2/A4 of #1937, `interpretation_reach` from the reach axis) must be byte-identical to the
    pre-migration builder (SK#2491's re-ruled acceptance criterion — both axes are additive)."""
    cards = dict(_card_maps())[case]
    emitted = _source_properties(cards)
    reference = _hand_rolled_reference(cards)
    assert emitted and reference, f"{case}: no source resolved — the comparison would be vacuous"
    assert list(emitted) == list(reference), f"{case}: entry order/set changed"
    assert json.dumps(_strip_roles(emitted)) == json.dumps(reference), (
        f"{case}: the migrated map differs from the hand-rolled one in MORE than the additive "
        f"`semantic_role` + `interpretation_reach` disposition keys"
    )
    # ... and the delta is not empty either: the typing is actually being attached.
    assert json.dumps(emitted) != json.dumps(reference), (
        f"{case}: no anchor gained a disposition-typing key — the ledger lookup is not wired (or the "
        f"ledger stopped declaring role/reach), which would make the strip-and-compare above vacuous"
    )


def test_every_recipe_source_is_exercised_by_the_synthetic_map():
    """Anti-vacuity floor for the parametrized claim above: the synthetic map must resolve EVERY recipe,
    and at least one anchor must carry each declared role kind the ledger gives genomic's anchors."""
    emitted = _source_properties(_synthetic_cards())
    assert set(emitted) == {r["name"] for r in _SOURCE_PROPERTY_RECIPES_GENOMIC}
    roles = {a["semantic_role"] for e in emitted.values() for a in e["anchors"] if "semantic_role" in a}
    assert roles == {"signal", "context"}, f"expected both declared role kinds on genomic anchors, got {roles}"


# ── 2. the role is SOURCED from the ledger, and follows a mutation of it ───────────────────────────────


def test_anchor_semantic_role_equals_the_role_declared_in_the_ledger_file():
    """Per (SKILL, card_id, field) — read from the ledger FILE, never a literal pinned here. An anchor
    whose field the ledger does NOT classify must carry no `semantic_role` at all."""
    declared = _ledger_roles()
    emitted = _source_properties(_synthetic_cards())
    checked = 0
    for name, entry in emitted.items():
        for anchor in entry["anchors"]:
            key = (entry["card_id"], anchor["field"])
            if key in declared:
                assert anchor.get("semantic_role") == declared[key], (
                    f"{name}/{anchor['field']}: emitted role {anchor.get('semantic_role')!r} != ledger-declared "
                    f"{declared[key]!r}"
                )
                checked += 1
            else:
                assert "semantic_role" not in anchor, (
                    f"{name}/{anchor['field']}: the ledger classifies this field on no row, so the anchor "
                    f"must not fabricate a role"
                )
    assert checked >= 20, f"only {checked} anchors were covered by the ledger — the assertion is near-vacuous"


def _ledger_root(tmp_path: Path, mutate) -> Path:
    """A throwaway skills_root holding ONLY a copy of genomic's ledger, with `mutate(doc)` applied. The
    role/reach maps are cached per (root, skill), so a fresh tmp root per test is a fresh lookup."""
    doc = load_ledger(LEDGER_PATH)
    mutate(doc)
    skill_dir = tmp_path / _GENOMIC_SKILL
    skill_dir.mkdir(parents=True)
    (skill_dir / LEDGER_NAME).write_text(yaml.safe_dump(doc, sort_keys=True))
    return tmp_path


_MUTANT_CARD = "mutation-stratified-dependency"
_MUTANT_FIELD = "delta_chronos_hotspot_mut_vs_wt"  # the ONE genomic anchor the ledger calls role: signal


def _emit(cards, skills_root=None):
    return build_source_properties(
        cards,
        _SOURCE_PROPERTY_RECIPES_GENOMIC,
        anchor_scale=_GENOMIC_ANCHOR_SCALE,
        skill=_GENOMIC_SKILL,
        skills_root=skills_root,
    )


def _anchor(props, prop_name, field):
    return next(a for a in props[prop_name]["anchors"] if a["field"] == field)


def test_emitted_role_follows_a_mutated_ledger_row(tmp_path):
    """THE TEETH on claim 2: flip the ledger's declared role for one (card_id, field) and the emitted
    `semantic_role` must flip with it. A hardcoded or name-shape-inferred role passes the equality test
    above and FAILS here."""
    cards = _synthetic_cards()
    baseline = _anchor(_source_properties(cards), "alteration_conferred_dependency", _MUTANT_FIELD)
    assert baseline["semantic_role"] == "signal"

    def flip(doc):
        doc[_MUTANT_CARD][_MUTANT_FIELD]["role"] = "provenance"

    mutated = _emit(cards, skills_root=str(_ledger_root(tmp_path, flip)))
    assert _anchor(mutated, "alteration_conferred_dependency", _MUTANT_FIELD)["semantic_role"] == "provenance"


def test_a_ledger_that_declares_no_role_for_a_field_omits_the_key(tmp_path):
    """Absence discipline, made to FIRE: drop the row and the anchor loses the key rather than keeping a
    stale or defaulted role."""

    def drop(doc):
        del doc[_MUTANT_CARD][_MUTANT_FIELD]

    emitted = _emit(_synthetic_cards(), skills_root=str(_ledger_root(tmp_path, drop)))
    assert "semantic_role" not in _anchor(emitted, "alteration_conferred_dependency", _MUTANT_FIELD)


# ── 3. interpretation_reach: now DECLARED (A2/A4, epic #1937) and carried onto the anchors ─────────────


def test_the_real_ledger_now_declares_the_reach_axis_and_anchors_carry_it():
    """A2/A4 (epic #1937, SK#1525): genomic's ledger NOW declares `interpretation_reach` on every row
    (census-derived via field_disposition_contract.interpretation_reach_for, captured 2026-10-02) — the
    inverse of the omission this test formerly pinned. `reach_map` is non-empty and equals the ledger's
    declared reach rows, and every emitted anchor carries the ledger-declared reach, never fabricated and
    never dropped. Drop the reach rows (or stop wiring the lookup) and this reds."""
    declared = {
        (cid, field): spec["interpretation_reach"]
        for cid, field, spec in iter_rows(load_ledger(LEDGER_PATH))
        if spec.get("interpretation_reach")
    }
    assert len(declared) >= 300, (
        f"only {len(declared)} rows declare interpretation_reach — the A2/A4 axis population regressed"
    )
    rm = reach_map(_GENOMIC_SKILL, str(SKILLS_ROOT))
    assert rm == declared, "reach_map disagrees with the ledger-declared interpretation_reach rows"
    checked = 0
    for name, entry in _source_properties(_synthetic_cards()).items():
        for anchor in entry["anchors"]:
            key = (entry["card_id"], anchor["field"])
            assert anchor.get("interpretation_reach") == declared.get(key), (
                f"{name}/{anchor['field']}: emitted reach {anchor.get('interpretation_reach')!r} != "
                f"ledger-declared {declared.get(key)!r}"
            )
            checked += 1
    assert checked >= 20, f"only {checked} anchors carried the reach axis — the assertion is near-vacuous"


def test_removing_a_reach_row_drops_the_axis_from_its_anchor(tmp_path):
    """THE TEETH on the reach wiring (the paired fire for the positive assertion above): strip
    `interpretation_reach` from the signal anchor row and the emitted anchor loses the axis — proving each
    anchor's reach is SOURCED from the ledger per (card_id, field), not fabricated. A hardcoded reach would
    survive this strip and FAIL here."""

    def strip(doc):
        doc[_MUTANT_CARD][_MUTANT_FIELD].pop("interpretation_reach", None)

    emitted = _emit(_synthetic_cards(), skills_root=str(_ledger_root(tmp_path, strip)))
    assert "interpretation_reach" not in _anchor(emitted, "alteration_conferred_dependency", _MUTANT_FIELD)


def test_a_ledger_that_declares_the_reach_axis_types_the_anchor_with_no_code_change(tmp_path):
    """The paired POSITIVE case that keeps the omission above from being vacuous: point the same call at a
    ledger whose row DOES declare `interpretation_reach` and the anchor gains the axis — which is why the
    sibling ledger issue needs no change in this module."""
    from _skills_common.field_disposition_contract import INTERPRETATION_REACH

    reach = sorted(INTERPRETATION_REACH)[0]

    def declare(doc):
        doc[_MUTANT_CARD][_MUTANT_FIELD]["interpretation_reach"] = reach

    emitted = _emit(_synthetic_cards(), skills_root=str(_ledger_root(tmp_path, declare)))
    anchor = _anchor(emitted, "alteration_conferred_dependency", _MUTANT_FIELD)
    assert anchor["interpretation_reach"] == reach
    # order is part of the byte output: the typing keys come after the envelope triple.
    assert list(anchor) == ["field", "value", "scale", "semantic_role", "interpretation_reach"]


# ── 4. the reliability facet survives, still sourced from the recipe spec ──────────────────────────────


def test_reliability_facet_is_present_on_every_entry_and_follows_its_recipe_spec():
    """The facet genomic already emitted must survive the migration (presence + value), and it must still
    be derived from the RECIPE's own n-anchor spec: re-point that spec at a different anchor and
    `n_effective` follows. A facet copied from a stored fixture would pass the first half and fail here."""
    cards = _synthetic_cards()
    emitted = _source_properties(cards)
    assert all("reliability" in e for e in emitted.values())
    spec_field = next(
        r["reliability"]["n_effective_anchor"]
        for r in _SOURCE_PROPERTY_RECIPES_GENOMIC
        if r["name"] == "alteration_conferred_dependency"
    )
    entry = emitted["alteration_conferred_dependency"]
    # `n_effective` is the designated anchor's value projected to int (reliability.py: a sample count).
    assert entry["reliability"]["n_effective"] == int(
        _anchor(emitted, "alteration_conferred_dependency", spec_field)["value"]
    )

    other = "n_hotspot_wildtype"
    assert other != spec_field
    mutated_recipes = tuple(
        {**r, "reliability": {**r["reliability"], "n_effective_anchor": other}}
        if r["name"] == "alteration_conferred_dependency"
        else r
        for r in _SOURCE_PROPERTY_RECIPES_GENOMIC
    )
    mutated = build_source_properties(
        cards,
        mutated_recipes,
        anchor_scale=_GENOMIC_ANCHOR_SCALE,
        skill=_GENOMIC_SKILL,
    )
    assert mutated["alteration_conferred_dependency"]["reliability"]["n_effective"] == int(
        _anchor(emitted, "alteration_conferred_dependency", other)["value"]
    )
    assert (
        mutated["alteration_conferred_dependency"]["reliability"]["n_effective"] != entry["reliability"]["n_effective"]
    ), "the two anchors carry the same value — the mutation could not have been observed"
