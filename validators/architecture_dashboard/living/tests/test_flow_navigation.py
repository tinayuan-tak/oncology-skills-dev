"""Flow diagrams: multiple altitudes present, and the zoom navigation is internally valid."""
from _util import load_committed


def _flow():
    return load_committed().get("flow", {})


def test_multiple_levels_present():
    levels = _flow().get("levels", [])
    assert len(levels) >= 9, f"expected >= 9 flow levels, got {len(levels)}"
    for lv in levels:
        assert lv.get("stages") or lv.get("center"), f"level {lv.get('id')} has no content"
        assert lv.get("subtitle"), f"level {lv.get('id')} has no subtitle"


def test_drill_and_parent_indices_valid():
    """Every zoom-in / zoom-out target must point at a real level index (connected views)."""
    levels = _flow().get("levels", [])
    n = len(levels)
    for lv in levels:
        pi = lv.get("parent_idx")
        assert pi is None or (0 <= pi < n), f"{lv['id']}: bad parent_idx {pi}"
        for st in lv.get("stages", []):
            di = st.get("drill_idx")
            assert di is None or (0 <= di < n), f"{lv['id']}/{st['label']}: bad drill_idx {di}"
        for ch in lv.get("child_idx", []):
            assert 0 <= ch["idx"] < n, f"{lv['id']}: bad child idx {ch}"


def test_wire_schematics_present_and_filled():
    """>=5 monospace wire schematics, tokens injected (no leftover «» placeholders)."""
    levels = _flow().get("levels", [])
    scs = [lv for lv in levels if lv.get("schematic")]
    assert len(scs) >= 5, f"expected >= 5 wire schematics, got {len(scs)}"
    for lv in scs:
        assert "«" not in lv["schematic"] and "»" not in lv["schematic"], \
            f"{lv['id']}: unfilled token placeholder in schematic"


def test_overview_drills_into_detail_levels():
    """The 10,000ft overview must connect to zoomed-in levels (the composed-views requirement)."""
    levels = {lv["id"]: lv for lv in _flow().get("levels", [])}
    ov = levels.get("overview")
    assert ov, "no overview level"
    drilled = {st["drill_id"] for st in ov.get("stages", []) if st.get("drill_id")}
    assert {"card", "post_card", "composition"} <= drilled, f"overview under-connected: {drilled}"
