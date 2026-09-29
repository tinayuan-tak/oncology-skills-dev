"""actionability_mode_lookup vocabulary tests — curated overrides for the derived actionability_mode facet."""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
LK = yaml.safe_load((REPO / "vocabularies" / "actionability_mode_lookup.yaml").read_text())
_MODES = {"cis_feature", "abundance", "mixed", "dependency_relational"}


def test_wellformed():
    assert LK["enum_id"] == "actionability_mode_lookup"
    assert set(LK["mode_enum"]) == _MODES
    assert isinstance(LK["overrides"], list) and LK["overrides"]


def test_each_override_wellformed():
    seen = set()
    for o in LK["overrides"]:
        assert o["hgnc_symbol"] and o["hgnc_symbol"] not in seen  # unique symbols
        seen.add(o["hgnc_symbol"])
        assert o["mode"] in _MODES
        assert o.get("rationale") and o.get("anchor")  # curation discipline


def test_documented_duals_are_mixed():
    """The seed's whole point: the biology_axis multi-axis duals are pinned mixed so a thin run can't collapse them."""
    by_sym = {o["hgnc_symbol"]: o for o in LK["overrides"]}
    for sym in ("ERBB2", "EGFR", "MET"):
        assert by_sym[sym]["mode"] == "mixed", f"{sym} must be pinned mixed"
    # HER2 alias resolves to ERBB2
    assert "HER2" in (by_sym["ERBB2"].get("aliases") or [])
