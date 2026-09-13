"""A card's `methods[]` block must name a reader that EXISTS, and every card must have SOME reader.

Why this check exists (foundation audit 2026-09-13): the whole build asked what a card DECLARES —
schema shape, thresholds, product ids, figures, measurement types — and nothing asked whether the code
that produces it can be reached. Two gaps, in opposite directions:

  RESOLUTION. `module` + `entrypoint` is resolved by the skills live-reader layer as
  `getattr(__import__("methods." + module), entrypoint)`. Because the generic dispatcher is only a
  FALLBACK behind the bespoke `CARD_DISPATCHERS` registry, a card with a bespoke reader can carry a
  declaration that resolves to nothing forever. Three `wired` cards did: the function existed in a
  SUBMODULE the package `__init__` never re-exported, so `grep def` found it and `getattr` did not.
  Fixed at the source by pointing `module` at the defining submodule; this file is the ratchet.

  ROUTABILITY. A card with neither an `entrypoint` nor a dispatcher entry emits nothing on every run,
  and no other check notices — the required-cards gate reads `status`, the figure check reads emitters.
  Nine cards are in that state today and all nine DECLARE a non-live status, so the exemption is by
  declaration. `KNOWN_UNROUTED_CARDS` pins them BY NAME so a new orphan is an error, not a new
  exemption, and a stale waiver on a now-wired card is an error too.

Hermetic by default: the behavioural tests build their own card directories and their own fake
methods/ trees. Three deliberate LIVE-corpus tests are the ratchet, and two anti-vacuity tests assert
the live populations are non-empty — a resolution loop over zero declarations, or a routability check
against an empty dispatcher set, would pass by measuring nothing.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
CARDS = REPO / "cards"


def _load(mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, REPO / "validators" / f"{mod_name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


VC = _load("validate_cards")

# The nine cards with no reader on any path, pinned BY NAME (not by count, and not by re-reading the
# validator's own set — a test that iterates the declaration it is checking is green under a swap).
_EXPECTED_UNROUTED = {
    "antigen-internalization",
    "antigen-prevalence",
    "antigen-prevalence-protein",
    "functional-blockade-rationale",
    "lineage-restriction-evidence",
    "rwd-stratified-expression",
    "sc-surface-normal-safety-solid",
    "subgroup-stratified-expression",
    "temporal-setting-expression-shift",
}

_ANALYSIS_METHODS_PRESENT = VC._analysis_methods_available()


@pytest.fixture(autouse=True)
def _clear_wiring_caches():
    """`_method_module_bindings` and `_analysis_methods_available` are lru_cached, and several tests
    repoint `_ANALYSIS_METHODS_REPO` at a fake tree. A warm cache would make those tests
    order-dependent and silently vacuous, so clear both around every test."""
    VC._method_module_bindings.cache_clear()
    VC._analysis_methods_available.cache_clear()
    yield
    VC._method_module_bindings.cache_clear()
    VC._analysis_methods_available.cache_clear()


def _card(cid: str, *, methods=None, status=None) -> dict:
    spec: dict = {"card_id": cid, "version": "1.0.0", "methods": methods if methods is not None else []}
    if status is not None:
        spec["status"] = status
    return spec


def _write_cards(tmp_path: Path, specs: list[dict]) -> Path:
    d = tmp_path / "cards"
    d.mkdir(exist_ok=True)
    for spec in specs:
        (d / f"{spec['card_id']}.card.yaml").write_text(yaml.safe_dump(spec, sort_keys=False))
    return d


def _fake_methods_tree(tmp_path: Path, modules: dict[str, str]) -> Path:
    """Build a methods/ package tree. Keys are dotted module paths, values are file source."""
    root = tmp_path / "am"
    (root / "methods").mkdir(parents=True, exist_ok=True)
    (root / "methods" / "__init__.py").write_text("")
    for dotted, src in modules.items():
        parts = dotted.split(".")
        pkg = root / "methods"
        for part in parts[:-1]:
            pkg = pkg / part
            pkg.mkdir(exist_ok=True)
            (pkg / "__init__.py").touch()
        (pkg / f"{parts[-1]}.py").write_text(src)
    return root


def _entrypoint_errors(spec: dict) -> list[str]:
    report = VC.ValidationReport(card_path="<test>")
    VC._method_entrypoint_check(spec, report)
    return [e for e in report.errors if e.startswith("METHOD_")]


# ---------------------------------------------------------------- resolution (per-card)


@pytest.mark.skipif(not _ANALYSIS_METHODS_PRESENT, reason="sibling analysis-methods repo not on disk")
def test_live_corpus_every_declared_entrypoint_resolves():
    """THE RATCHET (resolution direction). Every `module`+`entrypoint` in the live card corpus must name
    a symbol the module actually exports. This is what caught the three submodule-only declarations."""
    problems = []
    for path in sorted(CARDS.rglob("*.card.yaml")):
        spec = yaml.safe_load(path.read_text()) or {}
        problems += [f"{spec.get('card_id')}: {e}" for e in _entrypoint_errors(spec)]
    assert not problems, "unresolvable method wiring:\n  " + "\n  ".join(problems)


@pytest.mark.skipif(not _ANALYSIS_METHODS_PRESENT, reason="sibling analysis-methods repo not on disk")
def test_the_resolution_check_is_not_vacuous():
    """A loop over zero entrypoint-bearing declarations passes by measuring nothing. Assert the live
    population is substantial AND that resolution actually reads real symbol sets (not empty ones)."""
    declared = []
    for path in sorted(CARDS.rglob("*.card.yaml")):
        spec = yaml.safe_load(path.read_text()) or {}
        for m in spec.get("methods") or []:
            if isinstance(m, dict) and m.get("entrypoint"):
                declared.append((VC._method_module_path(m), m["entrypoint"]))
    assert len(declared) >= 60, f"only {len(declared)} entrypoint declarations — population collapsed?"
    resolved = [
        ep for mp, ep in declared if (b := VC._method_module_bindings(mp)) not in (None, VC._OPAQUE_MODULE) and ep in b
    ]
    assert len(resolved) == len(declared), "some declarations resolve only because the module is opaque"


def test_a_symbol_only_in_a_submodule_is_an_error(tmp_path, monkeypatch):
    """The exact live defect shape: the function is defined in `pkg/read.py`, the package `__init__`
    re-exports something else, so `getattr(pkg, fn)` raises AttributeError."""
    root = _fake_methods_tree(
        tmp_path,
        {"pkg.read": "def read_the_thing(target, indication):\n    return {}\n"},
    )
    (root / "methods" / "pkg" / "__init__.py").write_text("from methods.pkg.read import something_else\n")
    monkeypatch.setattr(VC, "_ANALYSIS_METHODS_REPO", root)
    VC._method_module_bindings.cache_clear()
    VC._analysis_methods_available.cache_clear()

    pkg_level = _entrypoint_errors(_card("c", methods=[{"call": "c", "module": "pkg", "entrypoint": "read_the_thing"}]))
    assert len(pkg_level) == 1 and pkg_level[0].startswith("METHOD_ENTRYPOINT_MISSING"), pkg_level
    # ...and the fix (point at the submodule) clears it — the check must accept the remedy it names.
    submodule = _entrypoint_errors(
        _card("c", methods=[{"call": "c", "module": "pkg.read", "entrypoint": "read_the_thing"}])
    )
    assert submodule == [], submodule


def test_a_missing_module_is_an_error(tmp_path, monkeypatch):
    root = _fake_methods_tree(tmp_path, {"pkg": "def f():\n    pass\n"})
    monkeypatch.setattr(VC, "_ANALYSIS_METHODS_REPO", root)
    VC._method_module_bindings.cache_clear()
    VC._analysis_methods_available.cache_clear()
    errs = _entrypoint_errors(_card("c", methods=[{"call": "c", "module": "no_such_pkg", "entrypoint": "f"}]))
    assert len(errs) == 1 and errs[0].startswith("METHOD_MODULE_MISSING"), errs


def test_the_module_defaults_to_the_call_slug_like_the_runtime_does(tmp_path, monkeypatch):
    """`_generic_dispatch` falls back to `call` with hyphens→underscores when `module` is omitted. The
    validator must mirror that or it would skip exactly the declarations the runtime still resolves."""
    root = _fake_methods_tree(tmp_path, {"my_reader": "def read_it():\n    pass\n"})
    monkeypatch.setattr(VC, "_ANALYSIS_METHODS_REPO", root)
    VC._method_module_bindings.cache_clear()
    VC._analysis_methods_available.cache_clear()
    assert _entrypoint_errors(_card("c", methods=[{"call": "my-reader", "entrypoint": "read_it"}])) == []
    bad = _entrypoint_errors(_card("c", methods=[{"call": "my-reader", "entrypoint": "read_gone"}]))
    assert len(bad) == 1 and bad[0].startswith("METHOD_ENTRYPOINT_MISSING"), bad


def test_a_call_only_method_is_out_of_the_population(tmp_path, monkeypatch):
    """75 of the 153 method entries declare only `call` (bespoke-routed). They promise no entrypoint, so
    the resolution check must not invent one — their coverage is the routability check's job."""
    root = _fake_methods_tree(tmp_path, {"pkg": ""})
    monkeypatch.setattr(VC, "_ANALYSIS_METHODS_REPO", root)
    VC._method_module_bindings.cache_clear()
    VC._analysis_methods_available.cache_clear()
    assert _entrypoint_errors(_card("c", methods=[{"call": "anything-at-all", "args": {}}])) == []


def test_a_star_import_module_is_skipped_not_failed(tmp_path, monkeypatch):
    """AST cannot see through `from .read import *`. No method package uses one today, but a false ERROR
    on wiring that genuinely resolves is worse than the gap, so an opaque module must ABSTAIN."""
    root = _fake_methods_tree(tmp_path, {"pkg.read": "def read_the_thing():\n    pass\n"})
    (root / "methods" / "pkg" / "__init__.py").write_text("from methods.pkg.read import *\n")
    monkeypatch.setattr(VC, "_ANALYSIS_METHODS_REPO", root)
    VC._method_module_bindings.cache_clear()
    VC._analysis_methods_available.cache_clear()
    assert VC._method_module_bindings("pkg") is VC._OPAQUE_MODULE
    assert _entrypoint_errors(_card("c", methods=[{"call": "c", "module": "pkg", "entrypoint": "anything"}])) == []


def test_conditionally_bound_names_count_as_exported():
    """`try: from x import y / except ImportError: def y(...)` binds y at module level. Treating only
    bare top-level defs as exports would false-fail that shape."""
    src = (
        "try:\n"
        "    from methods.other import read_it\n"
        "except ImportError:\n"
        "    def read_it():\n"
        "        pass\n"
        "if True:\n"
        "    LATE = 1\n"
    )
    names, opaque = VC._top_level_bindings(ast.parse(src).body)
    assert not opaque
    assert {"read_it", "LATE"} <= names
    # a name bound only INSIDE a function body is NOT an export.
    inner, _ = VC._top_level_bindings(ast.parse("def outer():\n    def inner():\n        pass\n").body)
    assert inner == {"outer"}


def test_resolution_skips_when_analysis_methods_is_absent(tmp_path, monkeypatch):
    """Isolated CI has no sibling repo. The check must abstain rather than error on every card."""
    monkeypatch.setattr(VC, "_ANALYSIS_METHODS_REPO", tmp_path / "nope")
    VC._method_module_bindings.cache_clear()
    VC._analysis_methods_available.cache_clear()
    assert _entrypoint_errors(_card("c", methods=[{"call": "c", "module": "pkg", "entrypoint": "gone"}])) == []


# ---------------------------------------------------------------- routability (cross-card)


def test_live_corpus_routability_is_clean():
    """THE RATCHET (routability direction): every card is readable, or waived-with-a-declared-status.

    Skips (rather than passing on an empty error list) when the dispatcher registries are unreadable —
    the check abstains in that state, so an assertion of "no errors" would be green for the wrong
    reason. The abstention itself is asserted separately."""
    if VC._dispatcher_routed_card_ids() is None:
        pytest.skip("sibling skills repo not on disk — the check abstains, so this ratchet cannot run")
    problems = VC.validate_card_method_routability(CARDS)
    errors = [p for p in problems if p.startswith("[ERROR]")]
    assert not errors, "unroutable cards:\n  " + "\n  ".join(errors)


def test_the_routability_check_is_not_vacuous():
    """An empty dispatcher set would make 60+ bespoke-routed cards look unroutable; an over-broad one
    would make everything look fine. Assert the parsed registries are real, and that the unroutable set
    the check derives is EXACTLY the nine pinned names."""
    routed = VC._dispatcher_routed_card_ids()
    if routed is None:
        pytest.skip("sibling skills repo not on disk — dispatcher registries unreadable")
    assert len(routed) >= 60, f"only {len(routed)} dispatcher-routed card_ids parsed — registry shape changed?"

    unroutable = set()
    for path in sorted(CARDS.rglob("*.card.yaml")):
        spec = yaml.safe_load(path.read_text()) or {}
        cid = spec.get("card_id")
        if (
            cid
            and cid not in routed
            and not any(isinstance(m, dict) and m.get("entrypoint") for m in (spec.get("methods") or []))
        ):
            unroutable.add(cid)
    assert unroutable == _EXPECTED_UNROUTED, (
        f"unroutable set moved: +{sorted(unroutable - _EXPECTED_UNROUTED)} -{sorted(_EXPECTED_UNROUTED - unroutable)}"
    )


def test_every_waived_card_declares_a_non_live_status():
    """The exemption is BY DECLARATION. A waived card claiming `wired` (or omitting status, which the
    schema defaults to `wired`) is a false liveness claim the waiver must not launder."""
    statuses = {}
    for path in sorted(CARDS.rglob("*.card.yaml")):
        spec = yaml.safe_load(path.read_text()) or {}
        if spec.get("card_id"):
            statuses[spec["card_id"]] = spec.get("status") or "wired"
    for cid in sorted(_EXPECTED_UNROUTED):
        assert statuses.get(cid) in VC._NON_LIVE_STATUSES, f"{cid}: status={statuses.get(cid)!r}"


def test_a_new_unwired_card_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(VC, "_dispatcher_routed_card_ids", lambda: frozenset({"routed-card"}))
    d = _write_cards(
        tmp_path,
        [
            _card("routed-card", methods=[{"call": "x"}]),
            _card("brand-new-card", methods=[{"call": "y"}], status="wired"),
        ],
    )
    problems = VC.validate_card_method_routability(d)
    # the waived nine have no contract in this fixture dir, so their own arm fires too — scope to the
    # arm under test rather than to the total, which would couple this test to the waiver's size.
    unroutable = [p for p in problems if "is UNROUTABLE" in p]
    assert len(unroutable) == 1 and "brand-new-card" in unroutable[0], problems
    assert not any("routed-card" in p for p in problems), "a dispatcher-routed card must not be flagged"


def test_a_stale_waiver_is_an_error(tmp_path, monkeypatch):
    """Mirror direction: a waiver that outlives its gap. `antigen-prevalence` gets a real entrypoint →
    the waiver must be removed, and the check says so instead of staying quietly green."""
    monkeypatch.setattr(VC, "_dispatcher_routed_card_ids", lambda: frozenset())
    specs = [_card(cid, methods=[{"call": cid}], status="placeholder_not_wired") for cid in sorted(_EXPECTED_UNROUTED)]
    specs[0]["methods"] = [{"call": specs[0]["card_id"], "module": "m", "entrypoint": "f"}]
    d = _write_cards(tmp_path, specs)
    problems = VC.validate_card_method_routability(d)
    assert len(problems) == 1, problems
    assert specs[0]["card_id"] in problems[0] and "now ROUTABLE" in problems[0], problems


def test_a_waiver_for_a_deleted_card_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(VC, "_dispatcher_routed_card_ids", lambda: frozenset())
    kept = sorted(_EXPECTED_UNROUTED)[1:]
    d = _write_cards(tmp_path, [_card(c, methods=[{"call": c}], status="dormant_pending_data") for c in kept])
    problems = VC.validate_card_method_routability(d)
    assert len(problems) == 1 and "no card contract" in problems[0], problems


def test_a_waived_card_claiming_wired_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(VC, "_dispatcher_routed_card_ids", lambda: frozenset())
    specs = [_card(cid, methods=[{"call": cid}], status="placeholder_not_wired") for cid in sorted(_EXPECTED_UNROUTED)]
    specs[0]["status"] = "wired"
    del specs[1]["status"]  # omitted → schema-defaulted to `wired`, same false claim
    d = _write_cards(tmp_path, specs)
    problems = VC.validate_card_method_routability(d)
    assert len(problems) == 2, problems
    assert {specs[0]["card_id"], specs[1]["card_id"]} == {p.split("'")[1] for p in problems}, problems
    assert all("claiming liveness" in p for p in problems), problems


def test_an_unreadable_dispatcher_registry_warns_instead_of_passing_silently(tmp_path, monkeypatch):
    """skip != pass. With no dispatcher registries the check CANNOT distinguish a bespoke-routed card
    from an orphan, so it must say so out loud — a silent [] is green for the wrong reason."""
    monkeypatch.setattr(VC, "_dispatcher_routed_card_ids", lambda: None)
    d = _write_cards(tmp_path, [_card("whatever", methods=[{"call": "x"}])])
    problems = VC.validate_card_method_routability(d)
    assert len(problems) == 1 and problems[0].startswith("[WARNING]") and "SKIPPED" in problems[0], problems


def test_an_empty_registry_parse_abstains_rather_than_flagging_everything(tmp_path, monkeypatch):
    """If the `*DISPATCHERS` naming convention changes, the parse finds nothing. Reporting 60+ phantom
    orphans would be worse than abstaining, so an empty parse is treated as 'cannot determine'."""
    fake = tmp_path / "live_readers.py"
    fake.write_text("SOMETHING_ELSE = {'a': 1}\nCARD_HANDLERS = {'card-a': _h}\n")
    monkeypatch.setattr(VC, "_LIVE_READERS_PATH", fake)
    VC._dispatcher_routed_card_ids.cache_clear()
    try:
        assert VC._dispatcher_routed_card_ids() is None
    finally:
        VC._dispatcher_routed_card_ids.cache_clear()


def test_the_registry_parse_is_suffix_driven_not_a_hardcoded_list(tmp_path, monkeypatch):
    """A FOURTH dispatcher registry must be picked up automatically — a hardcoded list of three would
    turn its cards into phantom orphans the day it lands."""
    fake = tmp_path / "live_readers.py"
    fake.write_text(
        "CARD_DISPATCHERS = {'a': _d}\n"
        "PANORAMA_DISPATCHERS = {'b': _d}\n"
        "SOME_BRAND_NEW_DISPATCHERS = {'c': (_d, 'manifest')}\n"
        "NOT_A_REGISTRY = {'d': 1}\n"
    )
    monkeypatch.setattr(VC, "_LIVE_READERS_PATH", fake)
    VC._dispatcher_routed_card_ids.cache_clear()
    try:
        assert VC._dispatcher_routed_card_ids() == frozenset({"a", "b", "c"})
    finally:
        VC._dispatcher_routed_card_ids.cache_clear()
