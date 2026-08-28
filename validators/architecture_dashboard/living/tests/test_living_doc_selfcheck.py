"""The committed framework_atlas.json must be internally self-consistent (CI-safe, no siblings)."""
from _util import builder, load_committed


def test_committed_living_doc_self_consistent():
    graph = load_committed()
    errs = builder().self_check(graph)
    assert not errs, "framework_atlas.json self-check failed:\n  " + "\n  ".join(errs[:30])


def test_has_expected_top_level_sections():
    graph = load_committed()
    for key in ("concepts", "gaps", "narrative", "glossary", "summary", "framework_atlas_version"):
        assert key in graph, f"framework_atlas.json missing top-level '{key}'"
