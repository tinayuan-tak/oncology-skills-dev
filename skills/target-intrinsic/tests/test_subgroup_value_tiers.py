"""Vocabulary-coverage guard for the signals-first sub-group panel's VALUE→TIER map.

WHY (2026-09-12 assessment): the panel binds ONE `*_class` field per source card — subgroup_derivation's
`_heuristic_reader` picks the FIRST `*_class` field of the card summary — and tiers its value with
`make_value_classifier(_TARGET_INTRINSIC_VALUE_TIERS)`. Any token the map OMITS falls through to the
lens-blind `default_classify` substring heuristic, which returns `absent` for anything lacking a
strong/moderate/weak/partial/sparse keyword. That silently INVERTED two live EGFR signals:
`potent_measured_ligand` (the strongest tractability precedent this roster carries) and
`secretome_proxy_shed` both read `absent` in the emitted panel.

The check is DATA-DRIVEN off the card contracts, so a new/renamed token in any source card's
`summary_fields_vocabulary` fails HERE instead of quietly becoming `absent` in a figure.

VERDICT-INERT: the map feeds only the `--figures` sub-group panel — never the spine, claim_vector,
rules or narrator. S3-free (contracts + the run.py literal only).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
if str(SKILLS_ROOT) not in sys.path:  # so `_skills_common` resolves when run outside skills/conftest.py
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common.paths import target_contracts_root  # noqa: E402
from _skills_common.subgroup_derivation import (  # noqa: E402
    _TIERS,
    _TIERV,
    UNMEASURED,
    default_classify,
    is_measured,
    make_value_classifier,
)

CONTRACTS = target_contracts_root()

# Tokens deliberately LEFT to default_classify, pinned to the tier it must return. A token belongs here
# only when the heuristic already lands on the right tier; the pin makes that reliance explicit (and fails
# if default_classify's keyword list ever changes underneath us).
_DEFAULT_SAFE = {
    "strong": "strong",  # structure-features-static pdb_coverage_class — keyword-matched by the heuristic
}

# Source cards with NO `*_class` field in their summary: the heuristic reader binds nothing, so the card
# contributes no panel source. Pinned so a card that GAINS a class field must be tiered here.
_NON_SOURCE_CARDS = {"target-identity-summary"}


def _run_py_literal(name: str):
    tree = ast.parse((SKILL_DIR / "scripts" / "run.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} literal not found in run.py")


def _card(card_id: str) -> dict:
    p = CONTRACTS / "cards" / f"{card_id}.card.yaml"
    if not p.exists():
        pytest.skip(f"target-contracts not available ({p})")
    return yaml.safe_load(p.read_text()) or {}


def _source_measurement_types() -> set[str]:
    """The measurement_types that BIND a sub-group source — `questions[*].measurement_types` only.

    `context_types` are NOT read by derive_subgroups (a documented asymmetry: the 8 safety-genetics cards
    are context-only, which is why they carry no panel tier)."""
    hier = yaml.safe_load((SKILL_DIR / "question_hierarchy.yaml").read_text())
    return {
        mt
        for sg in hier.get("sub_groups", [])
        for q in sg.get("questions", [])
        for mt in q.get("measurement_types", [])
    }


def _panel_sources() -> list[tuple[str, str, list[str]]]:
    """[(card_id, bound_class_field, vocabulary)] for every card that is a panel signal source.

    The bound field comes from run.py's EXPLICIT `_TARGET_INTRINSIC_SUBGROUP_READER` spec (the source of
    truth passed to derive_subgroups), NOT from the order-dependent `_heuristic_reader` fallback."""
    src_mt = _source_measurement_types()
    spec_by_mt = _run_py_literal("_TARGET_INTRINSIC_SUBGROUP_READER")
    out: list[tuple[str, str, list[str]]] = []
    for cid in _run_py_literal("CARDS"):
        card = _card(cid)
        mt = card.get("measurement_type")
        if mt not in src_mt:
            continue
        assert mt in spec_by_mt, (
            f"{cid} (measurement_type {mt!r}) binds a sub-group question but the reader spec does not "
            f"declare it — add a {{'class','n','label'}} entry (or an explicit None) to "
            f"_TARGET_INTRINSIC_SUBGROUP_READER, else it silently falls back to the order-dependent "
            f"_heuristic_reader."
        )
        spec = spec_by_mt[mt]
        outputs = card.get("outputs") or {}
        fields = [f for f in (outputs.get("summary_fields") or []) if isinstance(f, str)]
        if not spec:  # declared NON-source
            assert cid in _NON_SOURCE_CARDS, f"{cid} is declared non-source in run.py but not pinned here."
            assert not any(f.endswith("_class") for f in fields), (
                f"{cid} is declared a NON-source but its contract now declares a *_class field "
                f"({[f for f in fields if f.endswith('_class')]}) — it can carry a panel signal; give it a "
                f"reader-spec entry and tier its vocabulary."
            )
            continue
        assert cid not in _NON_SOURCE_CARDS, f"{cid} is pinned as a non-source but run.py declares a reader."
        bound = spec["class"]
        assert bound in fields, (
            f"{cid} reader spec binds {bound!r}, which the card contract does not declare in "
            f"outputs.summary_fields — a renamed reader field (the panel would read None)."
        )
        for nf in spec.get("n") or []:
            assert nf in fields, f"{cid} reader spec lists power field {nf!r}, absent from the contract."
        vocab = ((outputs.get("summary_fields_vocabulary") or {}).get(bound)) or []
        out.append((cid, bound, [str(v) for v in vocab]))
    return out


def test_panel_binds_every_source_card():
    """Fail-closed roster: all 11 panel sources bind a spec-declared class field, and the only
    class-field-less source card is the pinned identity card."""
    sources = _panel_sources()
    assert len(sources) == 11, f"expected 11 panel source cards, got {len(sources)}: {[c for c, _, _ in sources]}"
    assert {c for c, _, _ in sources}.isdisjoint(_NON_SOURCE_CARDS)


def test_reader_spec_declares_only_real_source_types():
    """No dead entries: every measurement_type in the reader spec must actually bind a sub-group question
    (a typo'd key would be silently ignored, restoring the heuristic fallback for that card)."""
    src_mt = _source_measurement_types()
    stale = sorted(set(_run_py_literal("_TARGET_INTRINSIC_SUBGROUP_READER")) - src_mt)
    assert not stale, f"reader-spec keys that bind no sub-group question: {stale}"


def test_every_source_class_field_declares_a_vocabulary():
    """A source field with no declared vocabulary is un-auditable — this guard could not see its tokens."""
    missing = [(c, f) for c, f, v in _panel_sources() if not v]
    assert not missing, f"card contracts declare no summary_fields_vocabulary for panel-bound fields: {missing}"


def test_every_live_class_token_is_tiered_or_knowingly_defaulted():
    """THE guard: every token of every panel-bound class field is either explicitly in
    _TARGET_INTRINSIC_VALUE_TIERS or listed in _DEFAULT_SAFE with the tier default_classify returns."""
    tiers = {str(k).lower(): v for k, v in _run_py_literal("_TARGET_INTRINSIC_VALUE_TIERS").items()}
    unmapped: list[str] = []
    for cid, field, vocab in _panel_sources():
        for tok in vocab:
            key = tok.lower()
            if key in tiers:
                continue
            if key in _DEFAULT_SAFE:
                got = default_classify(tok)
                assert got == _DEFAULT_SAFE[key], (
                    f"{cid}.{field}={tok!r} is allow-listed as default-safe expecting "
                    f"{_DEFAULT_SAFE[key]!r} but default_classify now returns {got!r}."
                )
                continue
            unmapped.append(f"{cid}.{field}={tok} (default_classify -> {default_classify(tok)})")
    assert not unmapped, (
        "live class tokens are neither tiered nor allow-listed — they fall through to the lens-blind "
        "default_classify and will read `absent` in the sub-group panel:\n  " + "\n  ".join(unmapped)
    )


def test_declared_tiers_are_valid():
    """Typo guard: an unknown tier string falls through to default_classify (make_value_classifier drops
    anything outside strong/moderate/weak/absent/unmeasured), i.e. a typo silently disables the entry."""
    bad = {k: v for k, v in _run_py_literal("_TARGET_INTRINSIC_VALUE_TIERS").items() if v not in _TIERS}
    assert not bad, f"tier values outside {sorted(_TIERS)}: {bad}"


def test_the_two_regressed_tokens_no_longer_read_absent():
    """Regression pin for the two live EGFR mis-tiers this map completion fixed."""
    classify = make_value_classifier(_run_py_literal("_TARGET_INTRINSIC_VALUE_TIERS"))
    assert classify("potent_measured_ligand") == "strong"
    assert classify("secretome_proxy_shed") == "moderate"
    assert default_classify("potent_measured_ligand") == "absent"  # what it used to be


def test_data_unavailable_is_unmeasured_not_a_measured_negative():
    """The tripwire this test used to carry (`assert "unmeasured" not in _TIERV`) has now FIRED and been
    acted on: the shared ladder gained the off-axis abstention, so a coverage gap is no longer encoded as
    a measured negative. `unmeasured` is deliberately NOT in _TIERV — it is not a quantity of signal — so
    the two collections are asserted separately here."""
    tiers = {str(k).lower(): v for k, v in _run_py_literal("_TARGET_INTRINSIC_VALUE_TIERS").items()}
    assert tiers.get("data_unavailable") == UNMEASURED
    assert UNMEASURED not in _TIERV, "the abstention must stay OFF the presence ordinal"
    assert UNMEASURED in _TIERS, "...but must be a valid tier, or make_value_classifier drops the entry"
    classify = make_value_classifier(_run_py_literal("_TARGET_INTRINSIC_VALUE_TIERS"))
    assert classify("data_unavailable") == UNMEASURED  # the map is actually honoured, not dropped
    assert not is_measured(UNMEASURED) and is_measured("absent")
