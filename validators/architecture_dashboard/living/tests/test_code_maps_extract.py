"""code_maps_extract: the subskill→gate / subskill→risk maps + the registry↔code risk drift.

Live source extraction (needs the skills sibling) re-derives the maps from tp_fanout.py /
risk_projection.py / ir.py and compares to committed goldens; the drift is compared against the
registry read from vocabularies/target_profiling_axes.yaml. A committed-artifact test (CI-safe)
checks the drift baked into framework_atlas.json.
"""

import yaml
from _util import load_committed, load_golden, skills_root, tc_root


def _maps_project(d: dict) -> dict:
    """Drop volatile `errors` for golden comparison."""
    return {k: v for k, v in d.items() if k != "errors"}


def _axes():
    return yaml.safe_load((tc_root() / "vocabularies" / "target_profiling_axes.yaml").read_text())


def test_code_maps_match_golden():
    import code_maps_extract as CM

    got = CM.extract_code_maps(skills_root())
    assert got["errors"] == [], got["errors"]
    assert _maps_project(got) == load_golden("code_maps.json")


def test_sub_skills_and_gate_map_shapes():
    import code_maps_extract as CM

    got = CM.extract_code_maps(skills_root())
    assert all({"skill", "short"} <= set(s) for s in got["sub_skills"])
    # the 8 gating shorts map to a gate; tumor-presence's expression is NOT among them (gateless)
    assert len(got["short_to_gate"]) == 8
    assert "expression" not in got["short_to_gate"]
    # exclusions carry a resolved state string, never the {state,reason} dict
    assert all(v is None or isinstance(v, str) for v in got["axis_dim_exclusions"].values())


def test_risk_drift_matches_golden():
    import code_maps_extract as CM

    got = CM.risk_drift(CM.extract_code_maps(skills_root()), _axes())
    assert got == load_golden("risk_drift.json")


def test_risk_drift_kinds_valid():
    import code_maps_extract as CM

    got = CM.risk_drift(CM.extract_code_maps(skills_root()), _axes())
    assert got, "expected a non-empty known drift (the finding surfaced to issue #856)"
    assert all(r["kind"] in ("category_mismatch", "unmapped_in_code") for r in got)
    assert got == sorted(got, key=lambda r: r["short"]), "drift rows must be short-sorted"


def test_committed_product_page_risk_drift_agrees_with_golden():
    """CI-safe: the drift block baked into the committed artifact matches the golden."""
    pp = load_committed().get("product_page") or {}
    assert (pp.get("risk_drift") or []) == load_golden("risk_drift.json")
