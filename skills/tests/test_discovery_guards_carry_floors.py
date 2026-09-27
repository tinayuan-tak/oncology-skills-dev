"""Meta-guard (the enforcement-layer teeth RATCHET): every discovery-based test guard must carry an
anti-vacuity floor.

This repo enforces a rich anti-vacuity practice by hand: a guard that discovers its subject set from
the filesystem/git (``glob`` / ``rglob`` / ``iterdir`` / ``os.walk`` / ``git ls-files``) and then
parametrizes over it or iterates it is only meaningful while that subject set is NON-EMPTY. The day the
subject empties — an empty glob, a relocated skill, a renamed source key, a refactored discovery helper
— a loop-based guard asserts over zero items (``collected N`` unchanged: fully invisible) and a
parametrize-based guard drops to zero cases (only the unread SKIP count moves under CI's ``-q``). Both
ship GREEN having proven nothing. The floored guards (``assert len(_X) >= N`` / ``assert _X``) close
that hole — but nothing FORCED them to, so every new discovery guard defaulted floorless and the
practice was one author-diligence lapse from a hole.

This meta-guard ratchets the class: it enumerates the test suite, classifies every module that does
MODULE-LEVEL discovery (a discovery call evaluated at import — assigned to a module-level variable, or
fed directly into a ``@pytest.mark.parametrize`` decorator, possibly via a module-level helper), and
asserts each such module carries an anti-vacuity floor over its discovered subject. Add a floorless
discovery guard and this goes RED, rather than the guard going silently vacuous. It consolidates
#1639 / #1640 / #1641 and the floorless residue found alongside (#1648).

Design notes (why this is a meta-guard, not a hand list):
  * The classifier is scope-aware. ``ast.walk`` is NOT scope-aware — a module-scope walk unions every
    function-local glob and would fabricate module-level discovery where there is none. So module-level
    discovery is decided over ``tree.body`` ONLY; discovery that lives inside a test/helper body (and is
    not lifted to a module var or a parametrize arg) is FUNCTION-level and out of this ratchet's class.
    (Function-level guards are floored directly at their own site — see e.g.
    test_card_field_conformance.py / test_question_hierarchy_drift.py.)
  * The floor must reference the DISCOVERY SUBJECT (the module-level discovery var, its discovery
    helper, or a local alias of either), so a floor drawn over a different, hand-maintained set does not
    count (the "floor on the wrong set" trap).
  * Teeth = mutation, not inspection. Positive/negative/scope controls below run the SAME classifier +
    floor functions the population run uses, on synthetic module sources, so a regression that blinds
    the classifier reds a control rather than silently exempting the corpus.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILLS.parent

# Discovery = filesystem/git enumeration whose result set can silently empty.
_DISCOVERY_ATTRS = {"glob", "rglob", "iterdir", "walk"}

# Genuinely-incidental module-level discovery (a glob NOT feeding any assertion) may be waived here WITH
# a reason. Empty today — fail-closed is the point: a new discovery guard must carry a floor or a waiver.
_NO_FLOOR_WAIVERS: dict[str, str] = {}  # {module_relpath: reason}


# ----------------------------------------------------------------------------------------------------
# AST primitives
# ----------------------------------------------------------------------------------------------------
def _subtree_has_discovery(node: ast.AST) -> bool:
    """True if the expression subtree contains a direct discovery call — a ``.glob/.rglob/.iterdir/
    .walk(...)`` attribute call, or a subprocess carrying a ``git ls-files`` argument."""
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _DISCOVERY_ATTRS:
            return True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and "ls-files" in n.value:
            return True
    return False


def _calls_named(node: ast.AST, names: set[str]) -> bool:
    """True if the subtree calls a function whose bare name is in ``names``."""
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in names:
            return True
    return False


def _refs_name(node: ast.AST, names: set[str]) -> bool:
    """True if the subtree references any Name id in ``names``."""
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id in names:
            return True
    return False


def _contains_len_call(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "len":
            return True
    return False


def _bound_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        out: set[str] = set()
        for el in target.elts:
            out |= _bound_names(el)
        return out
    return set()


def _assign_parts(node: ast.AST):
    """(targets, value) for an Assign / annotated Assign with a value, else (None, None)."""
    if isinstance(node, ast.Assign):
        return node.targets, node.value
    if isinstance(node, ast.AnnAssign) and node.value is not None:
        return [node.target], node.value
    return None, None


# ----------------------------------------------------------------------------------------------------
# Classification
# ----------------------------------------------------------------------------------------------------
def _discovery_helpers(tree: ast.Module) -> set[str]:
    """Top-level functions that do discovery — directly (their OWN body contains a discovery call;
    scope-correct, each function body is its own scope) OR transitively (they call another discovery
    helper). The transitive closure catches a two-hop chain like ``_all_specs()`` -> ``_rosters()``
    (glob), so a parametrize over ``_all_specs()`` is still recognized as discovery-fed."""
    func_nodes = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    helpers = {name for name, node in func_nodes.items() if any(_subtree_has_discovery(s) for s in node.body)}
    changed = True
    while changed:
        changed = False
        for name, node in func_nodes.items():
            if name not in helpers and _calls_named(node, helpers):
                helpers.add(name)
                changed = True
    return helpers


def _module_discovery_vars(tree: ast.Module, helpers: set[str]) -> set[str]:
    """Names assigned at MODULE LEVEL (``tree.body`` only — never inside a function) whose RHS does
    discovery directly, or calls a discovery helper. These are evaluated at import."""
    dvars: set[str] = set()
    for node in tree.body:
        targets, value = _assign_parts(node)
        if value is None:
            continue
        if _subtree_has_discovery(value) or _calls_named(value, helpers):
            for t in targets:
                dvars |= _bound_names(t)
    return dvars


def _is_parametrize(dec: ast.AST) -> bool:
    return isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "parametrize"


def _parametrize_argvalues(dec: ast.Call):
    """The argvalues expression of a ``@pytest.mark.parametrize(argnames, argvalues, ...)`` decorator."""
    if len(dec.args) >= 2:
        return dec.args[1]
    for kw in dec.keywords:
        if kw.arg == "argvalues":
            return kw.value
    return None


def _has_discovery_fed_parametrize(tree: ast.Module, helpers: set[str], dvars: set[str]) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if not _is_parametrize(dec):
                    continue
                argvals = _parametrize_argvalues(dec)
                if argvals is None:
                    continue
                if _subtree_has_discovery(argvals) or _calls_named(argvals, helpers) or _refs_name(argvals, dvars):
                    return True
    return False


def _subject_names(tree: ast.Module, helpers: set[str], dvars: set[str]) -> set[str]:
    """Every name that is a discovery subject or a (transitive) alias of one — so a floor written over a
    MODULE-LEVEL alias (``_SPECS = _all_specs(); assert len(_SPECS) >= 55``) still ties to the subject.

    Scope-aware, deliberately: alias propagation walks ``tree.body`` ONLY, never ``ast.walk`` into
    function bodies. A module-scope ``ast.walk`` would mint FUNCTION-LOCAL names as subjects — e.g. a
    per-item helper call ``d, q = _load(skill)`` (``_load`` globs one skill's fixtures, so it is a
    discovery helper) would make ``d``/``q`` and everything derived from them "subjects", and then a
    per-graph invariant like ``assert len(g["cards"]) == len(full["cards"])`` would false-match as an
    anti-vacuity floor. A floor must pin the module-level DISCOVERED SET, so only module-level names (and
    the helpers themselves, matched via ``_calls_named``) are subjects; the floor ASSERT may still live
    inside a test function (``_has_antivacuity_floor`` walks all asserts), it just has to reference one of
    these module-level subjects."""
    subjects = set(dvars) | set(helpers)
    changed = True
    while changed:
        changed = False
        for node in tree.body:
            targets, value = _assign_parts(node)
            if value is None:
                continue
            if _subtree_has_discovery(value) or _calls_named(value, helpers) or _refs_name(value, subjects):
                for t in targets:
                    for nm in _bound_names(t):
                        if nm not in subjects:
                            subjects.add(nm)
                            changed = True
    return subjects


def _has_antivacuity_floor(tree: ast.Module, subjects: set[str], helpers: set[str]) -> bool:
    """An ``assert`` that (a) references a discovery subject AND (b) is anti-vacuity shaped — a
    ``len(...)`` cardinality check, or a bare truthiness ``assert <subject>`` / ``assert <helper>()``."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        test = node.test
        if not (_refs_name(test, subjects) or _calls_named(test, helpers)):
            continue
        if _contains_len_call(test):
            return True
        # comparison of a subject-derived quantity against an int literal: `assert n >= 15` where
        # `n = len(subject)` (the len() lives in the binding, not the assert).
        if isinstance(test, ast.Compare) and any(
            isinstance(c, ast.Constant) and isinstance(c.value, int) and not isinstance(c.value, bool)
            for c in test.comparators
        ):
            return True
        # bare truthiness: `assert VAR`, `assert helper()`, or an operand of a boolean expression
        for operand in [test, *getattr(test, "values", [])]:
            if isinstance(operand, ast.Name) and operand.id in subjects:
                return True
            if isinstance(operand, ast.Call) and isinstance(operand.func, ast.Name) and operand.func.id in helpers:
                return True
    return False


def _classify(source: str):
    """(needs_floor: bool, has_floor: bool) for one module's source."""
    tree = ast.parse(source)
    helpers = _discovery_helpers(tree)
    dvars = _module_discovery_vars(tree, helpers)
    needs_floor = bool(dvars) or _has_discovery_fed_parametrize(tree, helpers, dvars)
    if not needs_floor:
        return False, False
    subjects = _subject_names(tree, helpers, dvars)
    return True, _has_antivacuity_floor(tree, subjects, helpers)


# ----------------------------------------------------------------------------------------------------
# Corpus enumeration
# ----------------------------------------------------------------------------------------------------
def _test_modules() -> list[Path]:
    """Every git-tracked ``test_*.py`` under ``skills/``."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "skills/**/test_*.py", "skills/test_*.py"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        rels = [f for f in out.split("\0") if f]
    except (subprocess.CalledProcessError, FileNotFoundError):
        rels = [str(p.relative_to(REPO_ROOT)) for p in SKILLS.rglob("test_*.py") if "__pycache__" not in p.parts]
    return sorted({(REPO_ROOT / r) for r in rels if Path(r).name.startswith("test_") and r.endswith(".py")})


def _discovery_modules():
    """(relpath, has_floor) for every module the classifier says does module-level discovery."""
    out = []
    for path in _test_modules():
        try:
            source = path.read_text()
        except OSError:
            continue
        try:
            needs, floored = _classify(source)
        except SyntaxError:
            continue
        if needs:
            out.append((str(path.relative_to(REPO_ROOT)), floored))
    return out


# ----------------------------------------------------------------------------------------------------
# Anti-vacuity floor for THIS ratchet (do not let the meta-guard's own discovery go vacuous)
# ----------------------------------------------------------------------------------------------------
def test_ratchet_corpus_is_not_vacuous():
    """If the enumeration glob or the classifier breaks, the ratchet below would police zero modules and
    pass proving nothing. Pin both the whole suite and the discovered-guard roster to a member count."""
    all_modules = _test_modules()
    assert len(all_modules) >= 200, (
        f"only {len(all_modules)} test modules enumerated under skills/ — the git ls-files enumeration "
        "broke; the ratchet would run over almost nothing."
    )
    discovery = _discovery_modules()
    assert len(discovery) >= 10, (
        f"only {len(discovery)} module-level-discovery guards classified — the AST classifier stopped "
        "recognizing discovery; the ratchet would pass vacuously. Expected the ~13-member roster "
        "(card_output_emission, live_reader_chain, evidence_graph_invariants, questions_yaml_schema, ...)."
    )


def test_every_discovery_guard_carries_a_floor():
    """THE ratchet. Every module-level discovery guard must carry an anti-vacuity floor over its
    discovered subject (or a documented waiver). A floorless one goes RED here rather than shipping
    green-by-vacuity the day its subject set empties."""
    floorless = [rel for rel, floored in _discovery_modules() if not floored and rel not in _NO_FLOOR_WAIVERS]
    assert not floorless, (
        "these test modules discover their subject set at module level (glob/rglob/iterdir/os.walk/"
        "git ls-files feeding a parametrize or a module-level list) but carry NO anti-vacuity floor "
        "over that subject, so they pass green-by-vacuity the day the subject empties:\n  "
        + "\n  ".join(sorted(floorless))
        + "\n\nAdd a floor that pins the discovered subject to a member count — a dedicated "
        "`assert len(<subject>) >= N` (or `assert <subject>`) test, mirroring e.g. "
        "test_live_reader_chain.py::test_skill_card_pairs_discovered. Do NOT floor a DIFFERENT set. "
        "If the discovery is genuinely incidental (feeds no assertion), waive it in _NO_FLOOR_WAIVERS "
        "with a reason."
    )


# ----------------------------------------------------------------------------------------------------
# Teeth — the classifier + floor detector, mutation-proven on synthetic module sources. These exercise
# the SAME functions the population run uses, so a regression that blinds the ratchet reds a control.
# ----------------------------------------------------------------------------------------------------
_FLOORLESS_MODULE = """
import pytest
from pathlib import Path
_SUBJECT = sorted(Path(".").glob("*/thing.yaml"))
@pytest.mark.parametrize("p", _SUBJECT)
def test_thing(p):
    assert p.exists()
"""

_FLOORED_MODULE = """
import pytest
from pathlib import Path
_SUBJECT = sorted(Path(".").glob("*/thing.yaml"))
def test_subject_not_empty():
    assert len(_SUBJECT) >= 3
@pytest.mark.parametrize("p", _SUBJECT)
def test_thing(p):
    assert p.exists()
"""

_FLOORED_VIA_HELPER = """
import pytest
from pathlib import Path
def _discover():
    return sorted(Path(".").glob("*/thing.yaml"))
_SUBJECT = _discover()
def test_not_empty():
    assert _SUBJECT
@pytest.mark.parametrize("p", _SUBJECT)
def test_thing(p):
    assert p.exists()
"""

_FLOOR_ON_WRONG_SET = """
import pytest
from pathlib import Path
_KNOWN = {"a", "b", "c"}
_SUBJECT = sorted(Path(".").glob("*/thing.yaml"))
def test_wrong_floor():
    assert len(_KNOWN) >= 3          # floors a hand-maintained set, NOT the discovery subject
@pytest.mark.parametrize("p", _SUBJECT)
def test_thing(p):
    assert p.exists()
"""

_FUNCTION_LEVEL_ONLY = """
from pathlib import Path
def _reads():
    return sorted(Path(".").glob("*/thing.yaml"))   # discovery lives INSIDE a function, not lifted
def test_thing():
    for p in _reads():
        assert p.exists()
"""

_PARAMETRIZE_HELPER_FLOORLESS = """
import pytest
from pathlib import Path
def _discover():
    return sorted(Path(".").glob("*/thing.yaml"))
@pytest.mark.parametrize("p", _discover())
def test_thing(p):
    assert p.exists()
"""


def test_positive_control_floorless_module_is_flagged():
    needs, floored = _classify(_FLOORLESS_MODULE)
    assert needs and not floored, "a module-level glob feeding a parametrize with no floor must be flagged"


def test_negative_control_floored_module_passes():
    needs, floored = _classify(_FLOORED_MODULE)
    assert needs and floored, "a module-level glob with an `assert len(subject) >= N` floor must pass"


def test_floor_via_helper_and_bare_truthiness_passes():
    needs, floored = _classify(_FLOORED_VIA_HELPER)
    assert needs and floored, "`_SUBJECT = _discover()` + `assert _SUBJECT` must read as floored"


def test_floor_on_the_wrong_set_is_still_flagged():
    needs, floored = _classify(_FLOOR_ON_WRONG_SET)
    assert needs and not floored, "a floor over a DIFFERENT (hand-maintained) set must NOT count as a floor"


def test_scope_control_function_level_discovery_is_not_flagged():
    """The AST scope trap: a glob confined to a function body (not lifted to a module var or a
    parametrize arg) is FUNCTION-level and must NOT be classified as module-level discovery — else a
    module-scope ``ast.walk`` would fabricate discovery everywhere."""
    needs, _ = _classify(_FUNCTION_LEVEL_ONLY)
    assert not needs, "function-local discovery must not be classified as module-level discovery"


def test_parametrize_over_discovery_helper_is_flagged():
    needs, floored = _classify(_PARAMETRIZE_HELPER_FLOORLESS)
    assert needs and not floored, "a parametrize over a direct discovery-helper call with no floor must be flagged"
