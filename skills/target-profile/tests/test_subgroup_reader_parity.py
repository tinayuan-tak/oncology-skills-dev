"""Composed sub-group panel must be built with the SAME reader spec + classifier the standalone run uses.

The composed fan-out derives each sub-skill's `subgroup_signals` itself (tp_fanout, at the point it
stashes the synthesis_facet's skill_report), because the fan-out is NOT a sub-run of the sub-skill's
run.py — it never goes through `run_wired_skill`, which is where a standalone run passes its tuned
`subgroup_reader_spec` / `subgroup_classify`. Before this guard, composition called
`subgroup_signals_for(...)` BARE, so every panel-tuning skill's tuning was silently dropped and the
composed panel fell back to `_heuristic_reader` (binds the FIRST `*_class` key in summary-dict order)
plus `default_classify` (a lens-blind substring heuristic that returns `absent` for any value lacking a
strong/moderate/weak keyword). Concretely, on target-intrinsic's committed EGFR golden: a `Tclin` target —
the STRONGEST chemical-precedent tier there is, an approved drug acting through this target's mode — read
`strong` standalone and `absent` composed, because "Tclin" contains no keyword the substring heuristic
knows. The same evidence, two opposite reads, in two artifacts of the same run.

`_load_sub_skill_subgroup_reader` recovers the tuning by CONVENTION from the sub-skill module: a
`_<SHORT>_VALUE_TIERS` dict becomes the classifier (via `make_value_classifier`) and a
`_<SHORT>_SUBGROUP_READER` dict becomes the reader spec. Convention beats a hand-maintained registry
here ONLY as long as the convention actually holds fleet-wide — which is exactly what this test pins, by
AST-reading what each skill's own source passes and asserting the discovery returns the same objects.

Covers both call shapes in the fleet: the 11+ skills that pass the kwargs to `run_wired_skill`, and
`genomic-alteration-profile`, which calls `subgroup_signals_for` directly in its run.py. A skill that
tunes NOTHING must discover `(None, None)` so its composed panel keeps the documented default.

VERDICT-INERT throughout: `subgroup_signals` is a display/routing panel on the skill_report spine; no
assertion here touches a verdict, and the fan-out swallows any fault in this path.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pytest  # noqa: E402
import tp_common  # noqa: E402,F401 — puts the skills root on sys.path so `_skills_common` imports
import tp_fanout  # noqa: E402

SKILLS_DIR = Path(tp_fanout.SKILLS_DIR)


def _run_py_ast(skill_dir: str) -> ast.Module | None:
    p = SKILLS_DIR / skill_dir / "scripts" / "run.py"
    if not p.exists():
        return None
    return ast.parse(p.read_text(), filename=str(p))


def _kw(call: ast.Call, name: str) -> ast.expr | None:
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _declared_tuning(tree: ast.Module) -> tuple[str | None, str | None]:
    """(reader_spec_name, value_tiers_name) the skill's OWN source passes for its sub-group panel, read
    from every `run_wired_skill(...)` / `subgroup_signals_for(...)` call site. Names only — the AST is
    deliberately not evaluated, so this stays an independent statement of intent rather than a re-run of
    the discovery logic it checks."""
    spec_name = tiers_name = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
        if fname not in ("run_wired_skill", "subgroup_signals_for"):
            continue
        # reader spec: `subgroup_reader_spec=_X_SUBGROUP_READER` (run_wired_skill) or the
        # `reader_spec=_X_SUBGROUP_READER` kwarg on a direct subgroup_signals_for call.
        for kwname in ("subgroup_reader_spec", "reader_spec"):
            v = _kw(node, kwname)
            if isinstance(v, ast.Name):
                spec_name = v.id
        # classifier: `subgroup_classify=make_value_classifier(_X_VALUE_TIERS)` / `classify=...`
        for kwname in ("subgroup_classify", "classify"):
            v = _kw(node, kwname)
            if isinstance(v, ast.Call) and getattr(v.func, "id", getattr(v.func, "attr", None)) == (
                "make_value_classifier"
            ):
                if v.args and isinstance(v.args[0], ast.Name):
                    tiers_name = v.args[0].id
    return spec_name, tiers_name


_SKILL_DIRS = sorted({d for d in tp_fanout.SUB_SKILL_CARDS})


def _tuning_skills() -> list[str]:
    out = []
    for d in _SKILL_DIRS:
        tree = _run_py_ast(d)
        if tree is None:
            continue
        if any(_declared_tuning(tree)):
            out.append(d)
    return out


def test_the_fleet_actually_tunes_its_panels():
    """Guard the guard: if this drops to zero the parity test below becomes VACUOUS (it would assert
    nothing about any real skill). The fleet had 12 panel-tuning skills when the discovery was written."""
    tuning = _tuning_skills()
    assert len(tuning) >= 10, f"expected the panel-tuning fleet, found {tuning}"


@pytest.mark.parametrize("skill_dir", _SKILL_DIRS)
def test_discovered_tuning_matches_what_the_skill_declares(skill_dir):
    """For EVERY composed sub-skill: the objects `_load_sub_skill_subgroup_reader` hands the composed
    panel are IDENTICAL (same object) to the module-level literals that skill's own source passes — and a
    skill that declares no tuning discovers (None, None), not a partial or a wrong-skill spec."""
    tree = _run_py_ast(skill_dir)
    if tree is None:
        pytest.skip(f"{skill_dir} has no scripts/run.py")
    spec_name, tiers_name = _declared_tuning(tree)

    spec, classify = tp_fanout._load_sub_skill_subgroup_reader(skill_dir)
    module = tp_fanout._SUBSKILL_MODULE_CACHE.get(skill_dir)
    if module is None:
        pytest.skip(f"{skill_dir} module not importable in this environment")

    if spec_name is None:
        assert spec is None, f"{skill_dir} declares no reader spec but discovery returned one"
    else:
        assert spec is getattr(module, spec_name), f"{skill_dir}: discovered spec is not {spec_name}"

    if tiers_name is None:
        assert classify is None, f"{skill_dir} declares no value tiers but discovery returned a classifier"
    else:
        # The classifier is built fresh by make_value_classifier, so compare BEHAVIOUR over the declared
        # vocabulary rather than identity: every value in the tier map must classify to its declared tier.
        tiers = getattr(module, tiers_name)
        assert callable(classify), f"{skill_dir}: no classifier discovered despite {tiers_name}"
        for value, tier in tiers.items():
            assert classify(value) == tier, f"{skill_dir}: {value!r} → {classify(value)!r}, declared {tier!r}"


@pytest.mark.parametrize("skill_dir", _SKILL_DIRS)
def test_convention_is_unambiguous(skill_dir):
    """The suffix convention is only sound while each module holds AT MOST ONE literal of each kind —
    otherwise discovery's last-wins loop would silently bind an arbitrary one. Pin that here so a future
    second `_*_VALUE_TIERS` in some skill fails HERE rather than quietly mis-tuning a composed panel."""
    tp_fanout._load_sub_skill_subgroup_reader(skill_dir)  # populate the module cache
    module = tp_fanout._SUBSKILL_MODULE_CACHE.get(skill_dir)
    if module is None:
        pytest.skip(f"{skill_dir} module not importable in this environment")
    names = [n for n, v in vars(module).items() if n.startswith("_") and isinstance(v, dict)]
    tiers = [n for n in names if n.endswith(tp_fanout._SUBGROUP_TIERS_SUFFIX)]
    readers = [n for n in names if n.endswith(tp_fanout._SUBGROUP_READER_SUFFIX)]
    assert len(tiers) <= 1, f"{skill_dir} has {len(tiers)} value-tier maps ({tiers}) — convention ambiguous"
    assert len(readers) <= 1, f"{skill_dir} has {len(readers)} reader specs ({readers}) — convention ambiguous"


def test_composed_derivation_diverges_from_the_bare_default_on_real_cards():
    """The end-to-end consequence, on target-intrinsic's committed EGFR golden cards: deriving the panel
    the way composition USED to (bare `subgroup_signals_for`) and the way it does now (threading the
    discovered spec + classifier) produce DIFFERENT signals for the same evidence. This is the test that
    would have caught the original defect; the parametrized tests above only pin the wiring."""
    import json

    from _skills_common.subgroup_derivation import subgroup_signals_for

    golden = SKILLS_DIR / "target-intrinsic" / "tests" / "fixtures" / "target_intrinsic_egfr_full_decision.json"
    if not golden.exists():
        pytest.skip("target-intrinsic golden fixture unavailable")
    cards = json.loads(golden.read_text())["cards"]
    skill_dir = SKILLS_DIR / "target-intrinsic"

    def _signals(panel):
        return {k: v.get("signal") for k, v in (panel or {}).items() if isinstance(v, dict)}

    bare = _signals(subgroup_signals_for(skill_dir, cards))
    spec, classify = tp_fanout._load_sub_skill_subgroup_reader("target-intrinsic")
    tuned = _signals(subgroup_signals_for(skill_dir, cards, reader_spec=spec, classify=classify))

    assert bare and tuned, "no sub-group panel derived at all — the comparison would be vacuous"
    assert bare != tuned, "bare and tuned derivations agree on this fixture — pick a discriminating one"
    # the specific regression: the strongest chemical-precedent tier read as `absent` under the bare
    # default because `Tclin` carries no strong/moderate/weak keyword for the substring heuristic.
    assert bare["TRACTABILITY_PRECEDENT"] == "absent"
    assert tuned["TRACTABILITY_PRECEDENT"] == "strong"


def test_target_intrinsic_composed_panel_is_not_the_blind_default():
    """The motivating case, end to end: target-intrinsic declares BOTH literals, and its discovered
    classifier reads `potent_measured_ligand` as a real tier — the value `default_classify` (the bare
    fallback composition used to get) scores `absent` because it carries no strong/moderate/weak keyword."""
    from _skills_common.subgroup_derivation import default_classify

    spec, classify = tp_fanout._load_sub_skill_subgroup_reader("target-intrinsic")
    assert isinstance(spec, dict) and spec, "target-intrinsic reader spec not discovered"
    assert callable(classify)
    assert classify("potent_measured_ligand") != default_classify("potent_measured_ligand")
    assert default_classify("potent_measured_ligand") == "absent"
