"""Roster sweep: the product page generalized from the tumor-presence exemplar (#852) to the FULL
skill roster (#853). Every skill in the committed framework_atlas.json must produce a structurally
valid five-panel product block across the three shape buckets — python-ladder, resolver-backed, and
no-verdict-source (descriptive/support/gateless) — with no crash and no fabricated verdict.

All assertions read the COMMITTED artifact (CI-safe, no siblings). A single live-rebuild sweep at
the end re-derives every block from the skills sibling and skips cleanly when it is absent.
"""

import pytest
from _util import load_committed, skills_root, tc_root

_PANELS = {"spine", "card_drilldown", "optionality", "rollup", "cards_questions"}


def _pp():
    pp = load_committed().get("product_page")
    if not pp:
        pytest.skip("committed framework_atlas.json has no product_page — regenerate with build_living_doc")
    return pp


def _skills():
    return _pp().get("skills") or {}


def test_roster_covers_every_graph_skill():
    """The product page is built for EVERY skill the wiring graph knows (not a hardcoded subset)."""
    graph = load_committed()
    graph_skills = set(graph.get("skills") or {})
    built = set(_skills())
    assert built == graph_skills, (
        f"roster mismatch: only-in-graph={graph_skills - built}, only-built={built - graph_skills}"
    )
    assert len(built) >= 20, f"expected the full ~22-skill roster, got {len(built)}"


def test_every_skill_has_five_panels():
    for name, block in _skills().items():
        assert set((block.get("panels") or {})) >= _PANELS, (
            f"{name} missing panels: {_PANELS - set(block.get('panels') or {})}"
        )


def test_three_shape_buckets_all_present():
    """The sweep must exercise all three verdict-source shapes: exactly one python-ladder skill
    (tumor-presence), the 9 resolver-backed gates, and the descriptive/support remainder."""
    buckets = {"python_ladder": [], "resolver_yaml": [], None: []}
    for name, block in _skills().items():
        vs = (block.get("ladder") or {}).get("verdict_source")
        buckets.setdefault(vs, []).append(name)
    assert buckets["python_ladder"], "no python-ladder skill in the roster"
    assert "tumor-presence" in buckets["python_ladder"]
    assert len(buckets["resolver_yaml"]) == 9, f"expected 9 resolver-backed skills, got {buckets['resolver_yaml']}"
    assert buckets[None], "no no-verdict-source (descriptive/support) skill exercised"


def test_verdict_bearing_skills_resolve_verdicts_within_enum():
    """A skill WITH a verdict source: every spine card resolves >=1 verdict token, all pinned."""
    for name, block in _skills().items():
        vs = (block.get("ladder") or {}).get("verdict_source")
        if not vs:
            continue
        spine = block["panels"]["spine"]
        enum = set(spine.get("verdict_enum") or [])
        cards = spine.get("cards") or []
        assert cards, f"{name} is verdict-bearing ({vs}) but resolved no spine cards"
        for row in cards:
            toks = {v for r in (row.get("rules") or []) for v in (r.get("verdicts") or [])}
            assert toks, f"{name} spine card {row.get('card_id')} resolves no verdict token"
            if enum:
                assert toks <= enum, (
                    f"{name} spine card {row.get('card_id')} has non-pinned verdicts {sorted(toks - enum)}"
                )


def test_no_verdict_source_skills_have_empty_spine_no_fabricated_green():
    """A gateless/descriptive/support skill must degrade to an EMPTY spine — never fabricate a
    verdict-bearing card. This is the 'no green propped up by an absence' invariant on the roster."""
    n_checked = 0
    for name, block in _skills().items():
        vs = (block.get("ladder") or {}).get("verdict_source")
        if vs:
            continue
        n_checked += 1
        spine = block["panels"]["spine"]
        assert not (spine.get("cards") or []), f"{name} has no verdict source but lists spine cards (fabricated)"
        assert not (spine.get("verdict_bearing_cards") or []), f"{name} fabricated verdict_bearing_cards"
    assert n_checked, "expected at least one no-verdict-source skill in the roster"


def test_optionality_lanes_verdict_inert_for_every_skill():
    for name, block in _skills().items():
        lanes = block["panels"]["optionality"].get("lanes") or []
        assert lanes, f"{name} has no optionality lanes"
        assert all(l.get("verdict_inert") is True for l in lanes), f"{name} has a non-inert optionality lane"
        assert all(str(l.get("flag", "")).startswith("--") for l in lanes), f"{name} lane flag is not a --flag"


def test_structural_self_check_passes_over_whole_roster():
    """The builder's product_page_errors self-check is clean across the full roster (not just tp)."""
    from _util import builder

    errs = builder().product_page_errors(load_committed())
    assert not errs, "product_page_errors:\n  " + "\n  ".join(errs)


def test_standalone_render_produces_valid_html_for_every_skill():
    """render_product_page_standalone emits a self-contained doc per skill (CI-safe: reads the
    committed graph). Structural: a full HTML document that names the skill and its five panels."""
    import render_living as R

    graph = load_committed()
    for name in _skills():
        html = R.render_product_page_standalone(graph, name)
        assert html.lstrip().lower().startswith("<!doctype html>"), f"{name}: not a full HTML doc"
        assert "</html>" in html
        # the five panel headers are always present (empty-but-honest for gateless skills)
        for panel_title in ("Spine", "Card drill-down", "Optionality", "Roll-up", "Cards"):
            assert panel_title in html, f"{name}: standalone page missing the {panel_title!r} panel"
        # the risk-drift finding (#856) is surfaced, never silently dropped
        assert "risk drift" in html.lower()


def test_live_rebuild_roster_spine_is_stable():
    """Re-derive every block from the skills sibling and confirm the verdict-bearing set + the
    shape bucket match the committed artifact for the whole roster (skips when siblings absent)."""
    sk = skills_root()  # skips if absent
    import build_living_doc as B
    import product_page as PP

    graph = load_committed()
    health = {"cards": [{"card_id": cid} for cid in graph["cards"]]}
    ledgers = PP.load_ledgers(tc_root())
    axes = B._load_axes(tc_root())
    for name, committed_block in _skills().items():
        block = PP.build(graph, health, ledgers, axes, name, sk_root=sk, tc_root=tc_root())
        live_vs = (block.get("ladder") or {}).get("verdict_source")
        committed_vs = (committed_block.get("ladder") or {}).get("verdict_source")
        assert live_vs == committed_vs, f"{name}: verdict_source drift live={live_vs} committed={committed_vs}"
        live = set(block["panels"]["spine"]["verdict_bearing_cards"])
        committed = set(committed_block["panels"]["spine"]["verdict_bearing_cards"])
        assert live == committed, f"{name}: spine drift {live ^ committed}"
