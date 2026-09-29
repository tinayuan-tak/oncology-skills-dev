"""ladder_extract: the rule→verdict precedence ladder, from a skill's run.py source.

Two kinds of test:
  * live source extraction (needs the skills sibling) — re-derives from run.py and compares to a
    committed golden, so a source drift (a rung added/removed/reordered) breaks the golden.
  * committed-artifact consistency (always runs, CI-safe) — the ladder baked into
    framework_atlas.json["product_page"] must agree with the golden's structure.
"""

from _util import load_committed, load_golden, skills_root, tc_root


def _ladder_project(d: dict) -> dict:
    """The stable structural slice a golden pins (drop volatile validation `errors`)."""
    return {"verdict_source": d.get("verdict_source"), "gate": d.get("gate"), "ladders": d.get("ladders")}


def test_tumor_presence_ladder_matches_golden():
    import ladder_extract as LE

    sk = skills_root()
    got = LE.extract_ladder(sk / "skills" / "tumor-presence" / "scripts" / "run.py")
    assert _ladder_project(got) == load_golden("tumor_presence_ladder.json")


def test_tumor_presence_is_python_ladder_three_layers():
    import ladder_extract as LE

    sk = skills_root()
    got = LE.extract_ladder(sk / "skills" / "tumor-presence" / "scripts" / "run.py")
    assert got["verdict_source"] == "python_ladder"
    assert got["gate"] is None
    layers = {lad["layer"] for lad in got["ladders"]}
    assert layers == {"bulk_rna", "bulk_protein_ms", "sc_rna"}
    # every rung is (rule_id, verdict) with a 0-based positional tier
    for lad in got["ladders"]:
        assert [r["tier"] for r in lad["rungs"]] == list(range(len(lad["rungs"])))
        assert all(r["rule_id"] and r["verdict"] for r in lad["rungs"])


def test_resolver_backed_skill_short_circuits():
    """A resolver-backed skill (tumor-selectivity) has NO python ladder; it names its gate."""
    import ladder_extract as LE

    sk = skills_root()
    run_py = sk / "skills" / "tumor-selectivity" / "scripts" / "run.py"
    if not run_py.exists():
        import pytest

        pytest.skip("tumor-selectivity run.py absent")
    got = LE.extract_ladder(run_py)
    assert got["verdict_source"] == "resolver_yaml"
    assert got["gate"], "resolver-backed skill must recover its gate name"
    assert got["ladders"] == [] and got["rungs"] == []


def test_ladder_verdicts_subset_of_pinned_enum_and_atlas_rules():
    """Validation teeth: with the pinned enum + atlas rule_ids supplied, a clean skill drifts to
    zero errors — every ladder verdict is a pinned token and every rung rule_id is a real card rule."""
    import json

    import ladder_extract as LE

    sk = skills_root()
    pins = json.loads((tc_root() / "schemas" / "_skill_output" / "pins" / "tumor-presence.pins.json").read_text())
    enum = next(v["enum"] for v in pins["$defs"].values() if isinstance(v, dict) and isinstance(v.get("enum"), list))
    graph = load_committed()
    rule_ids = {r["rule_id"] for c in graph["cards"].values() for r in (c.get("rules") or []) if r.get("rule_id")}
    got = LE.extract_ladder(sk / "skills" / "tumor-presence" / "scripts" / "run.py", enum=enum, graph_rule_ids=rule_ids)
    assert set(got["verdict_tokens"]) <= set(enum), got["errors"]
    assert got["errors"] == [], got["errors"]


def test_committed_product_page_ladder_agrees_with_golden():
    """CI-safe: the ladder embedded in the committed artifact matches the golden structure."""
    pp = load_committed().get("product_page") or {}
    block = (pp.get("skills") or {}).get("tumor-presence") or {}
    assert _ladder_project(block.get("ladder") or {}) == load_golden("tumor_presence_ladder.json")
