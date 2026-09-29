"""product_page: the per-subskill five-panel block, assembled into framework_atlas.json.

Most assertions read the committed artifact (CI-safe). A re-derivation test rebuilds the block
from live siblings and checks the spine's verdict-bearing set is stable (skips when siblings absent).
"""

import pytest
from _util import load_committed, skills_root, tc_root

_PANELS = {"spine", "card_drilldown", "optionality", "rollup", "cards_questions"}


def _pp():
    pp = load_committed().get("product_page")
    if not pp:
        pytest.skip("committed framework_atlas.json has no product_page — regenerate with build_living_doc")
    return pp


def _tumor_presence():
    return (_pp().get("skills") or {}).get("tumor-presence") or {}


def test_product_page_present_with_default_skill():
    pp = _pp()
    skills = pp.get("skills") or {}
    assert skills, "product_page has no skills"
    assert pp.get("default_skill") in skills
    assert "tumor-presence" in skills


def test_all_five_panels_present():
    block = _tumor_presence()
    assert set((block.get("panels") or {})) >= _PANELS, block.get("panels", {}).keys()


def test_self_check_product_page_structural():
    """The builder's product_page structural self-check passes on the committed artifact."""
    from _util import builder

    graph = load_committed()
    errs = builder().product_page_errors(graph)
    assert not errs, "product_page_errors:\n  " + "\n  ".join(errs)


def test_spine_verdict_bearing_cards_resolve_verdicts():
    spine = _tumor_presence()["panels"]["spine"]
    cards = spine.get("cards") or []
    assert cards, "no verdict-bearing cards on the spine"
    assert spine.get("verdict_source") == "python_ladder"
    assert spine.get("verdict_enum") or [], "spine must carry the pinned verdict enum"
    for row in cards:
        rules = row.get("rules") or []
        assert rules, f"{row['card_id']} has no rules"
        # at least one rule maps to a verdict token, and every such token is in the pinned enum
        toks = {v for r in rules for v in (r.get("verdicts") or [])}
        assert toks, f"{row['card_id']} resolves no verdict"
        assert toks <= set(spine["verdict_enum"]), (
            f"{row['card_id']} verdicts {toks - set(spine['verdict_enum'])} not pinned"
        )


def test_optionality_lanes_present_and_flag_shaped():
    """Non-vacuity + shape: the panel carries lanes and each names a real `--flag`.

    SK#2091 dropped the third assert (`verdict_inert is True` for every lane): the tag is a
    hardcoded True in product_page._OPTIONALITY_LANES, so it asserted its own literal and could
    never fail. The two asserts kept here CAN fail (an empty panel, a malformed flag).
    """
    lanes = _tumor_presence()["panels"]["optionality"]["lanes"]
    assert lanes, "no optionality lanes"
    assert all(l.get("flag", "").startswith("--") for l in lanes)


def test_rollup_shape():
    ru = _tumor_presence()["panels"]["rollup"]
    assert ru.get("short") == "expression"
    # tumor-presence expression is a gateless necessity axis
    assert ru.get("gateless") is True and ru.get("gate") is None
    assert ru.get("risk_dim"), "rollup must resolve a risk-6dim bin"


def test_cards_questions_bottoms_out_at_cards():
    cq = _tumor_presence()["panels"]["cards_questions"]
    assert cq.get("axis")
    all_cards = set(load_committed()["cards"])  # sanity: card universe
    seen_mt, joined = 0, 0
    for sg in cq.get("sub_groups") or []:
        for q in sg.get("questions") or []:
            for mt in q.get("measurement_types") or []:
                seen_mt += 1
                for c in mt.get("cards") or []:
                    assert c in all_cards, f"{c} is not a real card"
                    joined += 1
    assert seen_mt, "no measurement_types in the question hierarchy"
    assert joined, "no measurement_type resolved to any card"


def test_card_drilldown_covers_all_composed_cards():
    block = _tumor_presence()
    dd = block["panels"]["card_drilldown"]
    assert len(dd) == block.get("n_cards"), "drill-down must list every composed card"
    assert any(r.get("is_verdict_bearing") for r in dd)


def test_live_rebuild_spine_is_stable():
    """Re-derive the block from siblings and confirm the verdict-bearing set matches the artifact."""
    sk = skills_root()  # skips if absent
    import build_living_doc as B
    import product_page as PP

    graph = load_committed()
    health = {"cards": [{"card_id": cid, **{}} for cid in graph["cards"]]}  # minimal overlay
    ledgers = PP.load_ledgers(tc_root())
    axes = B._load_axes(tc_root())
    block = PP.build(graph, health, ledgers, axes, "tumor-presence", sk_root=sk, tc_root=tc_root())
    live = set(block["panels"]["spine"]["verdict_bearing_cards"])
    committed = set(_tumor_presence()["panels"]["spine"]["verdict_bearing_cards"])
    assert live == committed, f"spine drift: live-committed={live ^ committed}"
