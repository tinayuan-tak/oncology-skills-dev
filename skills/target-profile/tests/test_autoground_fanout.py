"""target-profile AUTO-GROUNDING (fanout-integration) — offline unit guards for tp_grounding.

The live path (`--ground`) runs literature-risk-assessment/ground_axis, which needs PubMed + Bedrock;
that is exercised by a live smoke run, not here. These offline tests pin the deterministic orchestration:
  - resolve_axes: the --ground value → validated, ordered axis list (engine / all / comma-list / typo).
  - auto_ground: writes grounded_<axis>.json + returns {axis: record} via an INJECTED ground_fn (no
    network); best-effort per axis (a raising or non-dict axis is skipped, the rest still produced).
  - the produced record shape is what BOTH consumers accept (HTML grounded_by_axis + the --substrate
    parse_grounded_substrate): a {axis, deterministic, grounded} dict.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import tp_grounding as tg  # noqa: E402


# =============================== resolve_axes ===============================
def test_resolve_axes_default_and_engine_are_the_five_engine_axes():
    assert tg.resolve_axes(None) == list(tg.ENGINE_AXES)
    assert tg.resolve_axes("engine") == list(tg.ENGINE_AXES)
    assert tg.resolve_axes("") == list(tg.ENGINE_AXES)
    assert len(tg.ENGINE_AXES) == 5


def test_resolve_axes_all_adds_pseudo_cards():
    axes = tg.resolve_axes("all")
    assert axes == list(tg.ENGINE_AXES) + list(tg.PSEUDO_AXES)
    assert "clinical" in axes and "commercial" in axes


def test_resolve_axes_comma_list_validated_and_ordered():
    # order normalizes to engine-then-pseudo regardless of input order; dedups
    axes = tg.resolve_axes("dependency,safety,safety")
    assert axes == ["safety", "dependency"]
    # a pseudo-card explicitly requested is allowed
    assert tg.resolve_axes("commercial,safety") == ["safety", "commercial"]


def test_resolve_axes_unknown_axis_raises_loudly():
    with pytest.raises(ValueError) as ei:
        tg.resolve_axes("safety,not_an_axis")
    assert "not_an_axis" in str(ei.value)


# =============================== auto_ground (injected ground_fn) ===============================
def _fake_rec(axis: str) -> dict:
    """A ground_axis-shaped record."""
    return {"axis": axis, "deterministic": {"verdict": f"{axis}_verdict", "cards": {}},
            "grounded": {"findings": [{"finding": f"{axis} finding", "kind": "k",
                                       "cited_pmids": ["12345678"]}],
                         "corroborations": [], "contradicts_deterministic": False,
                         "anchor_verdict": f"{axis}_verdict", "escalate_only": True,
                         "confabulated_dropped": [], "n_retrieved": 3,
                         "corpus_pin": {"mindate": "2015", "maxdate": "2026"}}}


def test_auto_ground_writes_records_and_returns_map(tmp_path):
    calls = []

    def gf(target, indication, pkg_path, *, axis, mindate, maxdate):
        calls.append((target, indication, axis, Path(pkg_path).name))
        return _fake_rec(axis)

    pkg = tmp_path / "evidence_package.json"
    pkg.write_text("{}")
    produced = tg.auto_ground("KRAS", "COADREAD", pkg, tmp_path,
                              ["safety", "dependency"], ground_fn=gf)
    assert set(produced) == {"safety", "dependency"}
    # each axis wrote a grounded_<axis>.json with the {axis, deterministic, grounded} shape
    for ax in ("safety", "dependency"):
        p = tmp_path / f"grounded_{ax}.json"
        assert p.exists()
        rec = json.loads(p.read_text())
        assert rec["axis"] == ax and "grounded" in rec and "deterministic" in rec
    # ground_fn saw the package path + each axis
    assert {c[2] for c in calls} == {"safety", "dependency"}
    assert all(c[3] == "evidence_package.json" for c in calls)


def test_auto_ground_is_best_effort_one_bad_axis_skipped(tmp_path):
    def gf(target, indication, pkg_path, *, axis, mindate, maxdate):
        if axis == "dependency":
            raise RuntimeError("Bedrock unavailable")
        if axis == "selectivity":
            return "not a dict"          # malformed → skipped, not crashed
        return _fake_rec(axis)

    pkg = tmp_path / "evidence_package.json"
    pkg.write_text("{}")
    produced = tg.auto_ground("KRAS", "COADREAD", pkg, tmp_path,
                              ["safety", "dependency", "selectivity"], ground_fn=gf)
    # only the healthy axis survives; the run did not raise
    assert set(produced) == {"safety"}
    assert (tmp_path / "grounded_safety.json").exists()
    assert not (tmp_path / "grounded_dependency.json").exists()
    assert not (tmp_path / "grounded_selectivity.json").exists()


def test_produced_record_is_consumable_by_substrate_parser(tmp_path):
    """The produced record must be accepted by the hypothesis's parse_grounded_substrate (the
    --substrate contract) — proving the fanout output feeds [3B] natively without reshaping."""
    lra = SKILLS / "cross-evidence-hypothesis" / "scripts"
    if str(lra) not in sys.path:
        sys.path.insert(0, str(lra))
    import hypothesis_core as hc  # noqa: E402

    pkg = tmp_path / "evidence_package.json"
    pkg.write_text("{}")
    produced = tg.auto_ground("KRAS", "COADREAD", pkg, tmp_path, ["safety"],
                              ground_fn=lambda *a, axis, **k: _fake_rec(axis))
    parsed = hc.parse_grounded_substrate(produced)
    assert parsed["present"] is True
    assert parsed["n_findings"] == 1
    assert "12345678" in parsed["pmids"]
