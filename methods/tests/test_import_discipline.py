"""Structural lint: nothing under ``methods/`` may import an analysis method by a BARE name.

WHAT THIS FORBIDS AND WHY (skills#2237)
---------------------------------------
Two import shapes only ever resolve because something mutated ``sys.path`` first:

1. **A bare top-level method name** — ``from depmap_chronos import read``,
   ``import tcga_fusion_consensus``, ``from cptac_protein_deg.read import ...``.
   ``depmap_chronos`` is not a distribution; it is a *subpackage directory* of
   ``onc_methods``. A bare import of it resolves only if ``methods/onc_methods/`` itself is
   on ``sys.path`` — i.e. only under a ``sys.path.insert`` (or a lucky ``cwd``, or pytest's
   rootdir-insertion under the non-importlib import modes). Ten test modules relied on
   exactly this and were invisible to a plain ``pytest methods/``; the fix is the
   fully-qualified ``from onc_methods.depmap_chronos import read``, which resolves through
   the editable install from any cwd.

2. **The old package name** — ``import methods`` / ``from methods.<x> import ...``. The
   import package was renamed ``methods`` -> ``onc_methods`` in skills#2237 so that its
   name differs from the distribution DIRECTORY ``methods/``: a package dir named
   ``methods`` inside ``methods/`` gets shadowed by the monorepo-root ``methods/`` dir
   whenever that lands on ``sys.path``, because ``PathFinder`` precedes the
   editable-install finder on ``sys.meta_path`` (skills#2196). A resurrected ``import
   methods`` is therefore not merely stale — it re-opens the shadow hazard, and it can
   even *appear* to work (resolving to an empty namespace package over the distribution
   dir, then failing on attribute access somewhere far away).

THE BASIS IS DERIVED, NOT LISTED
--------------------------------
The forbidden root names are read off the filesystem — every subpackage directory of
``methods/onc_methods/`` — rather than hardcoded as a ``tcga_*|depmap_*|cptac_*`` prefix
glob. A literal prefix list silently stops covering a method added under a new prefix
(``hpa_*``, ``signor_*``, ...), and a guard whose subject list can go empty is a guard
that passes vacuously: ``test_violation_basis_is_populated`` pins the basis as non-empty
and asserts it covers the three prefixes the issue named.

There is deliberately NO allowlist. Every import of a method from inside this
distribution can be fully qualified; if you think you have found an exception, the
exception is the bug.
"""

from __future__ import annotations

import ast
from pathlib import Path

# methods/ — the DISTRIBUTION root (this file is methods/tests/test_import_discipline.py)
_DIST = Path(__file__).resolve().parents[1]
# methods/onc_methods/ — the import package
_PKG = _DIST / "onc_methods"

# The pre-rename package name. A bare `import methods` must stay dead (see docstring #2).
_OLD_PACKAGE_NAME = "methods"

# Non-package directories that sit INSIDE the distribution root. They are not installed
# (pyproject's packages.find.include is `onc_methods*`), so a bare `from scripts.x import y`
# or `import tests.y` resolves only as a namespace package over the distribution root — i.e.
# only under a sys.path.insert. `methods/tests/scripts/test_*.py` reached the ops drivers
# exactly that way; they now load them with spec_from_file_location.
_DIST_NON_PACKAGE_DIRS = ("scripts", "tests")


def _forbidden_roots(pkg_dir: Path) -> set[str]:
    """Top-level module names that must never appear as an import ROOT.

    = every subpackage dir of onc_methods/ (a bare import of one can only resolve via a
    sys.path insert) + the pre-rename package name + the distribution's non-package dirs.
    """
    subpackages = {p.name for p in pkg_dir.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))}
    return subpackages | {_OLD_PACKAGE_NAME} | set(_DIST_NON_PACKAGE_DIRS)


def _import_roots(node: ast.AST) -> list[str]:
    """Root module name(s) of an import statement, or [] if it is not an absolute import."""
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        # level > 0 is an explicit relative import (`from .read import x`) — always fine.
        if node.level == 0 and node.module:
            return [node.module.split(".")[0]]
    return []


def _scan(root: Path, forbidden: set[str]) -> dict[str, list[tuple[int, str]]]:
    """Return {relpath: [(lineno, root_name), ...]} for every bare method import under `root`.

    Walks the FULL ast (not just module-level statements) so a lazily-imported bare name
    inside a function body is caught too — those are the ones a smoke test never reaches.
    """
    found: dict[str, list[tuple[int, str]]] = {}
    for py in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text())
        except SyntaxError:
            # A file that cannot be parsed cannot be audited: surface it rather than pass.
            found.setdefault(str(py.relative_to(root)), []).append((0, "<syntax-error>"))
            continue
        for node in ast.walk(tree):
            for name in _import_roots(node):
                if name in forbidden:
                    found.setdefault(str(py.relative_to(root)), []).append((node.lineno, name))
    return found


def test_no_bare_method_imports_under_methods():
    """No file in the distribution may import a method by a bare (sys.path-dependent) name."""
    violations = _scan(_DIST, _forbidden_roots(_PKG))
    assert not violations, (
        "Bare, sys.path-dependent method import(s) under methods/ — qualify them through the "
        "installed package instead (`from onc_methods.<method> import read`). A bare "
        "`from depmap_chronos import ...` or `import methods` only resolves under a "
        "sys.path.insert, which skills#2237 removed (and `methods` is the shadowed old "
        "package name — see skills#2196).\n  "
        + "\n  ".join(f"{rel}:{ln} -> {name}" for rel, hits in sorted(violations.items()) for ln, name in hits)
    )


def test_violation_basis_is_populated():
    """The forbidden-root basis must be real, or the guard above passes vacuously.

    An empty (or prefix-narrowed) basis means NOTHING can violate the lint while it still
    reports green — the classic guard-that-deleted-its-own-subject. Pin both the magnitude
    and the three prefixes skills#2237 named explicitly.
    """
    forbidden = _forbidden_roots(_PKG)
    assert len(forbidden) > 100, (
        f"only {len(forbidden)} forbidden roots derived from {_PKG} — the basis collapsed "
        "(wrong path? package renamed again?), so test_no_bare_method_imports_under_methods "
        "can no longer fail"
    )
    assert _OLD_PACKAGE_NAME in forbidden
    for prefix in ("tcga_", "depmap_", "cptac_"):
        assert any(n.startswith(prefix) for n in forbidden), (
            f"no {prefix}* method in the basis — skills#2237 names these three prefixes "
            "explicitly; their absence means the basis is not being read off onc_methods/"
        )


# --- mutation tests: prove the lint can actually FAIL -------------------------------------


def test_the_check_can_actually_fail(tmp_path):
    """Feed the scanner a synthetic tree of KNOWN violations and require it to flag each.

    Without this, `test_no_bare_method_imports_under_methods` being green is equally
    consistent with "the tree is clean" and "the detector matches nothing".
    """
    forbidden = _forbidden_roots(_PKG)
    cases = {
        # (filename, source, expected root reported)
        "v_import.py": ("import depmap_chronos\n", "depmap_chronos"),
        "v_from.py": ("from depmap_chronos import read\n", "depmap_chronos"),
        "v_from_sub.py": ("from cptac_protein_deg.read import load\n", "cptac_protein_deg"),
        "v_dotted.py": ("import tcga_fusion_consensus.read as r\n", "tcga_fusion_consensus"),
        "v_old_pkg.py": ("import methods\n", "methods"),
        "v_old_pkg_from.py": ("from methods.depmap_chronos import read\n", "methods"),
        "v_lazy.py": ("def f():\n    from depmap_chronos import read\n    return read\n", "depmap_chronos"),
        "v_aliased.py": ("import depmap_chronos as dc\n", "depmap_chronos"),
        # non-package dirs inside the distribution root (only reachable via a sys.path insert)
        "v_ops_scripts.py": ("from scripts.prefetch_source_maf import SOURCE_CONFIGS\n", "scripts"),
        "v_ops_scripts_mod.py": ("from scripts import prefetch_source_maf\n", "scripts"),
        "v_tests_dir.py": ("import tests.methods.conftest\n", "tests"),
    }
    for fname, (src, _root) in cases.items():
        (tmp_path / fname).write_text(src)
    # ...and sources that must NOT be flagged (a detector that flags everything is useless).
    clean = {
        "c_qualified.py": "from onc_methods.depmap_chronos import read\n",
        "c_qualified_import.py": "import onc_methods.tcga_fusion_consensus\n",
        "c_relative.py": "from .read import load\n",
        "c_relative_deep.py": "from ..depmap_chronos import read\n",
        "c_stdlib.py": "import json\nfrom pathlib import Path\n",
        # a name that merely CONTAINS a forbidden name is not a forbidden root
        "c_lookalike.py": "import depmap_chronos_helper\nfrom my_methods import x\n",
    }
    for fname, src in clean.items():
        (tmp_path / fname).write_text(src)

    found = _scan(tmp_path, forbidden)

    missed = sorted(set(cases) - set(found))
    assert not missed, f"the lint FAILED TO DETECT known-bad imports (it cannot fail): {missed}"
    for fname, (_src, root) in cases.items():
        reported = {name for _ln, name in found[fname]}
        assert root in reported, f"{fname}: expected root {root!r}, got {sorted(reported)}"
    false_positives = sorted(set(clean) & set(found))
    assert not false_positives, f"the lint flagged LEGITIMATE imports: {[(f, found[f]) for f in false_positives]}"


def test_unparseable_file_is_reported_not_skipped(tmp_path):
    """A SyntaxError must surface as a finding, not silently exempt the file from the audit."""
    (tmp_path / "broken.py").write_text("def f(:\n")
    found = _scan(tmp_path, _forbidden_roots(_PKG))
    assert "broken.py" in found and found["broken.py"] == [(0, "<syntax-error>")]
