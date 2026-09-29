"""The atlas build must describe the tree it is run FROM, not a hard-coded $HOME path.

`build_architecture_explorer.DEFAULTS["tc"]` used to be `~/rnd-...-target-contracts`. Every
consumer defaults to it — `build_living_doc --tc`, and therefore `make atlas` and `make
atlas-check`. Run from a /tmp worktree that reads the PRIMARY checkout's cards, rules and
resolvers while WRITING the feed into the worktree, so:

  * a branch could regenerate the committed atlas and publish TRUNK's wiring under its own name,
    with the branch's actual contract changes invisible in the feed it just committed;
  * `--check` compared trunk against a feed built from trunk and reported `fresh`, i.e. the
    drift guard was answering a question about a tree nobody was working in.

Both failure modes are silent — the build prints no warning, and the numbers look plausible.
This is the same defect class as the absolute `md_path` in `stable_projection`: a tool whose
answer depends on where it happens to be invoked.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_ARCH = REPO / "validators" / "architecture_dashboard"


def _load(name: str, path: Path):
    if str(_ARCH) not in sys.path:
        sys.path.insert(0, str(_ARCH))
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


A = _load("build_architecture_explorer", _ARCH / "build_architecture_explorer.py")


def test_contracts_root_is_the_tree_this_test_lives_in():
    """The whole point: in a worktree this must be the WORKTREE, and in CI's checkout it must be
    the checkout — neither is under $HOME by the old convention."""
    assert A.DEFAULTS["tc"] == REPO, (
        f"atlas would read contracts from {A.DEFAULTS['tc']} while this tree is {REPO} — "
        "a feed regenerated here would describe a different tree"
    )


def test_contracts_root_actually_contains_the_contracts():
    tc = A.DEFAULTS["tc"]
    for sub in ("cards", "interpretation-rules", "resolvers", "schemas"):
        assert (tc / sub).is_dir(), f"derived contracts root {tc} has no {sub}/"


def test_sibling_roots_are_resolved_next_to_the_contracts_root():
    """Siblings follow the same derivation, which is the layout framework_health.probe and
    framework-health-cross-repo.yml already assume. If they were left on $HOME, an atlas built in
    a worktree would mix worktree contracts with whatever skills/catalog $HOME happened to hold."""
    for key, name in (
        ("sk", "rnd-computational-biology-oncology-claude-oncology-skills"),
        ("dc", "rnd-computational-biology-oncology-data-catalog"),
    ):
        expected = (REPO.parent / name).resolve()
        assert A.DEFAULTS[key] == expected, f"DEFAULTS[{key!r}] = {A.DEFAULTS[key]}, expected {expected}"


def test_sibling_roots_are_resolved_through_the_worktree_symlinks():
    """new-worktree seeds the siblings as SYMLINKS to the canonical clones, and paths harvested
    from them are COMMITTED (skills[].md_path in framework_atlas.json). Leaving them unresolved
    would publish an ephemeral /tmp worktree path inside a shared artifact."""
    for key in ("sk", "dc"):
        p = A.DEFAULTS[key]
        assert not p.is_symlink(), f"DEFAULTS[{key!r}] is an unresolved symlink: {p}"
        assert p == p.resolve(), f"DEFAULTS[{key!r}] is not canonical: {p} != {p.resolve()}"


def test_living_doc_data_products_default_follows_the_same_root():
    """build_living_doc derives --dp from DEFAULTS['tc'].parent, so the fix must carry to it
    rather than leaving one of the four roots pointing somewhere else."""
    living = _load("build_living_doc", _ARCH / "living" / "build_living_doc.py")
    assert Path(A.DEFAULTS["tc"]).parent == REPO.parent
    assert living.DEFAULT_JSON == REPO / "health" / "framework_atlas.json", living.DEFAULT_JSON
    assert living.DEFAULT_HTML == REPO / "health" / "framework_atlas.html", living.DEFAULT_HTML
