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
def test_resolve_axes_default_and_engine_cover_all_configured_engine_axes():
    """FIX (2026-08-21, finding #5): engine axes are DERIVED from the live ground_axis.AXIS_CONFIG
    (every verdict-anchored entry), so the default `--ground` covers ALL engine axes — not just the
    original 5. Previously this hard-coded 5 and silently excluded the 4 rolled-out axes."""
    engine, _pseudo = tg._split_configured_axes()
    assert tg.resolve_axes(None) == engine
    assert tg.resolve_axes("engine") == engine
    assert tg.resolve_axes("") == engine
    # the 5 originals + the 4 rolled-out engine axes are all reachable by the default now
    assert {
        "safety",
        "dependency",
        "selectivity",
        "surface_modality",
        "tractability_sm",
        "mechanism",
        "genomic_alteration",
        "differentiation",
        "expression",
    } <= set(engine)
    # consolidation orphans must NOT be engine axes (removed with the 2026-08-21 cleanup)
    assert "synthetic_lethal_partners" not in engine and "combinatorial_dependency" not in engine


def test_resolve_axes_all_adds_pseudo_cards():
    engine, pseudo = tg._split_configured_axes()
    axes = tg.resolve_axes("all")
    assert axes == list(engine) + list(pseudo)
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
    return {
        "axis": axis,
        "deterministic": {"verdict": f"{axis}_verdict", "cards": {}},
        "grounded": {
            "findings": [{"finding": f"{axis} finding", "kind": "k", "cited_pmids": ["12345678"]}],
            "corroborations": [],
            "contradicts_deterministic": False,
            "anchor_verdict": f"{axis}_verdict",
            "escalate_only": True,
            "confabulated_dropped": [],
            "n_retrieved": 3,
            "corpus_pin": {"mindate": "2015", "maxdate": "2026"},
        },
    }


def test_auto_ground_writes_records_and_returns_map(tmp_path):
    calls = []

    def gf(target, indication, pkg_path, *, axis, mindate, maxdate):
        calls.append((target, indication, axis, Path(pkg_path).name))
        return _fake_rec(axis)

    pkg = tmp_path / "evidence_package.json"
    pkg.write_text("{}")
    produced = tg.auto_ground("KRAS", "COADREAD", pkg, tmp_path, ["safety", "dependency"], ground_fn=gf)
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
            return "not a dict"  # malformed → skipped, not crashed
        return _fake_rec(axis)

    pkg = tmp_path / "evidence_package.json"
    pkg.write_text("{}")
    produced = tg.auto_ground("KRAS", "COADREAD", pkg, tmp_path, ["safety", "dependency", "selectivity"], ground_fn=gf)
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
    produced = tg.auto_ground(
        "KRAS", "COADREAD", pkg, tmp_path, ["safety"], ground_fn=lambda *a, axis, **k: _fake_rec(axis)
    )
    parsed = hc.parse_grounded_substrate(produced)
    assert parsed["present"] is True
    assert parsed["n_findings"] == 1
    assert "12345678" in parsed["pmids"]


# =============================== plan_substrate (DEFAULT-ON gating) ===============================
def test_plan_substrate_default_full_run_turns_the_whole_chain_on():
    """A plain nomination run (no opt-outs, no fast/machine mode) runs ground + both projections, with
    grounding defaulting to the engine axes."""
    p = tg.plan_substrate(
        no_substrate=False,
        no_synthesis=False,
        emit=None,
        ground=None,
        no_ground=False,
        no_risk=False,
        no_hypothesis=False,
    )
    assert p == {
        "chain_on": True,
        "run_ground": True,
        "ground_spec": "engine",
        "run_risk": True,
        "run_hypothesis": True,
    }


def test_plan_substrate_no_substrate_restores_offline_byte_identical_run():
    p = tg.plan_substrate(
        no_substrate=True,
        no_synthesis=False,
        emit=None,
        ground=None,
        no_ground=False,
        no_risk=False,
        no_hypothesis=False,
    )
    assert p["chain_on"] is False
    assert (p["run_ground"], p["run_risk"], p["run_hypothesis"]) == (False, False, False)


def test_plan_substrate_fast_and_machine_modes_skip_the_chain():
    # --no-synthesis / --verdict-only (which sets no_synthesis) and --emit all keep the run byte-identical
    for kw in ({"no_synthesis": True}, {"emit": "evidence-package"}):
        base = dict(
            no_substrate=False,
            no_synthesis=False,
            emit=None,
            ground=None,
            no_ground=False,
            no_risk=False,
            no_hypothesis=False,
        )
        base.update(kw)
        p = tg.plan_substrate(**base)
        assert p["chain_on"] is False
        assert (p["run_risk"], p["run_hypothesis"]) == (False, False)


def test_plan_substrate_granular_opt_outs_are_independent():
    p = tg.plan_substrate(
        no_substrate=False,
        no_synthesis=False,
        emit=None,
        ground=None,
        no_ground=True,
        no_risk=False,
        no_hypothesis=True,
    )
    assert p["chain_on"] is True
    assert p["run_ground"] is False and p["run_hypothesis"] is False
    assert p["run_risk"] is True


def test_plan_substrate_explicit_ground_survives_no_ground_and_sets_spec():
    # an explicit --ground value forces grounding on even in a mode where the chain would be off, and
    # threads the requested axis spec through.
    p = tg.plan_substrate(
        no_substrate=True,
        no_synthesis=False,
        emit=None,
        ground="safety,dependency",
        no_ground=True,
        no_risk=False,
        no_hypothesis=False,
    )
    assert p["run_ground"] is True and p["ground_spec"] == "safety,dependency"


# =============================== [3A]/[3B] orchestrators (best-effort) ===============================
def _minimal_sub_results():
    # The in-memory fanout shape build_risk_6dim reads: {short: {"verdict": (v, rule), "cards": [...]}}.
    return {
        "safety": {"verdict": ("tolerant_reduced_safety_risk", "r"), "cards": []},
        "dependency": {"verdict": ("concordant_dependent", "r"), "cards": []},
        "mechanism": {"verdict": ("well_characterized", "r"), "cards": []},
        "tractability_sm": {"verdict": ("well_covered", "r"), "cards": []},
    }


def test_build_risk_6dim_projects_deterministic_bins_and_writes_file(tmp_path):
    # risk_6dim is now computed IN-MEMORY from sub_results (no disk round-trip). Grounding empty ({})
    # → the pure deterministic projection (no sibling/network).
    dims = tg.build_risk_6dim(_minimal_sub_results(), "small_molecule", {}, tmp_path)
    assert isinstance(dims, dict)
    # the deterministic 6-dim spine is present
    assert {"safety", "biological", "druggability", "clinical", "commercial", "translational"} <= set(dims)
    assert (tmp_path / "risk_rollup.json").exists()


def test_build_risk_6dim_is_best_effort_bad_input_returns_none(tmp_path):
    # a malformed sub_results must degrade to None (WARN), never raise
    assert tg.build_risk_6dim("not-a-dict", "small_molecule", {}, tmp_path) is None


def test_auto_risk_assessment_is_best_effort_on_failure(tmp_path, monkeypatch):
    # Inject a failing sibling loader so the fail-soft contract is tested WITHOUT touching the network
    # (the live LRA path hits PubMed before reading the package, so a bad-path test would be flaky).
    monkeypatch.setattr(tg, "_load_sibling", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no Bedrock/network")))
    assert tg.auto_risk_assessment("KRAS", "colorectal cancer", tmp_path / "nope.json", tmp_path) is None


def test_auto_hypothesis_is_best_effort_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "_load_sibling", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no Bedrock/network")))
    assert tg.auto_hypothesis(tmp_path / "nope.json", tmp_path, modality="small_molecule") is None
