"""--full-package packaging: write_full_package emits per-sub-skill packages + a MANIFEST. Bedrock-free,
no S3.

(The coherence / data-package / hypothesis HTML body-block assertions that used to live here were removed
with the retirement of tp_render_html 2026-09-03 — the default html render path is report_render, covered
by its own suite. The renderer-agnostic packaging invariant below is retained.)"""

from __future__ import annotations

import json
from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run_fpb")
import tp_manifest as tm  # noqa: E402


def test_write_full_package_emits_subskills_and_manifest(tmp_path):
    sr = {
        "expression": {
            "skill_dir": "tumor-presence",
            "cards": [{"card_id": "rna", "card_version": "1", "summary": {"_data_source": "x"}}],
            "verdict": ("tumor_broadly_expressed", "r"),
            "fired": [],
            "synthesis_facet": {},
        }
    }
    (tmp_path / "figures").mkdir()
    mpath = tm.write_full_package(
        tmp_path,
        target="KRAS",
        indication="COADREAD",
        sub_results=sr,
        skill_name="target-profile",
        skill_version="1.0",
        generated_at="t",
        subtypes=None,
        modality=None,
        has_figures=True,
        has_evidence_package=True,
        has_narrative=True,
    )
    assert mpath.name == "MANIFEST.json" and mpath.exists()
    pkg = tmp_path / "subskills" / "expression" / "package.json"
    assert pkg.exists()
    d = json.loads(pkg.read_text())
    assert d["sub_skill"] == "expression" and d["verdict"] == "tumor_broadly_expressed"
    man = json.loads(mpath.read_text())
    assert man["bundle_type"] == "target-profile-full-package" and (tmp_path / "MANIFEST.md").exists()


def test_full_package_also_emits_each_subskill_dashboard(tmp_path):
    """Dashboard consolidation: a composed --full-package run emits each sub-skill's dashboard.html
    (report_render standalone view) beside its package.json — so the composed run produces the FULL
    set (composed target_profile.html + every subskill dashboard), synchronized, each openable alone.
    Rendered from the carried skill_report (with its evidence_graph). Display-only / best-effort."""
    import sys

    skills_root = Path(__file__).resolve().parents[2]  # .../skills
    if str(skills_root) not in sys.path:
        sys.path.insert(0, str(skills_root))

    sr = {
        "expression": {
            "skill_dir": "tumor-presence",
            "cards": [{"card_id": "rna", "card_version": "1", "summary": {"_data_source": "x"}}],
            "verdict": ("tumor_broadly_expressed", "r"),
            "fired": [],
            "synthesis_facet": {
                "skill_report": {
                    "call": "tumor_broadly_expressed",
                    "role": "gating",
                    "polarity": "supportive",
                    "honest_phrase": "Abundantly present",
                    "confidence": {"level": "moderate"},
                    "question_table": [{"id": "Q1", "question": "present?", "signal": {}, "confidence": {}}],
                    "provenance": {"driving_rule_id": "r", "fired_rule_ids": ["r"], "cards_used": ["rna"]},
                }
            },
        }
    }
    (tmp_path / "figures").mkdir()
    mpath = tm.write_full_package(
        tmp_path,
        target="KRAS",
        indication="COADREAD",
        sub_results=sr,
        skill_name="target-profile",
        skill_version="1.0",
        generated_at="t",
        subtypes=None,
        modality=None,
        has_figures=True,
        has_evidence_package=True,
        has_narrative=True,
    )
    dash = tmp_path / "subskills" / "expression" / "dashboard.html"
    assert dash.exists(), "composed --full-package must emit each subskill's dashboard.html"
    h = dash.read_text()
    assert "<!doctype html>" in h.lower() or "<!DOCTYPE" in h
    # MANIFEST references the dashboard beside the package
    man = json.loads(mpath.read_text())
    entry = next(s for s in man.get("sub_skills", []) if s.get("sub_skill") == "expression")
    assert entry.get("dashboard") == "subskills/expression/dashboard.html"


def test_write_subskill_package_materializes_one_package_standalone(tmp_path):
    """The single-sub-skill projection the [3B] hypothesis leg needs BEFORE the full bundle exists.
    Same path and same shape write_full_package would produce, from the same in-memory carrier."""
    r = {
        "skill_dir": "target-intrinsic",
        "cards": [{"card_id": "paralog", "card_version": "1", "summary": {"_data_source": "x"}}],
        "verdict": ("tractable_biology", "r7"),
        "fired": [{"rule_id": "r7", "card_id": "paralog", "tier": "strong", "signals": {}}],
        "synthesis_facet": {"claim_vector": {"a": 1}, "key_signals": ["s"]},
    }
    p = tm.write_subskill_package(tmp_path, "target_intrinsic", r)
    assert p == tmp_path / "subskills" / "target_intrinsic" / "package.json" and p.exists()
    d = json.loads(p.read_text())
    assert d["sub_skill"] == "target_intrinsic" and d["verdict"] == "tractable_biology"
    assert d["driving_rule_id"] == "r7" and d["n_cards"] == 1
    # figures/ absent is not an error — a dossier read is verdict-inert context
    assert d["cards"][0]["figures"] == []
    # best-effort: a carrier that makes the projection raise returns None instead of killing the run
    assert tm.write_subskill_package(tmp_path, "broken", {"cards": 7, "fired": 7}) is None
    assert not (tmp_path / "subskills" / "broken" / "package.json").exists()


def test_dossier_is_on_disk_before_the_hypothesis_leg_reads_it():
    """ORDERING REGRESSION GUARD (the F16 defect that a single target cannot show).

    run.py's [3B] leg passes `subskills/target_intrinsic/package.json` as the integrator's dossier only
    `if dossier_path.exists()`. subskills/ is written by write_full_package at the very END of the run,
    so before the early materialization below the check was ALWAYS False: every default-on chain run
    reported `degraded inputs: ['dossier']` and pinned certainty `low` — panel-wide constant, no
    discrimination between targets, and no single-target run looks wrong. So the invariant is an
    ORDER, not a value: the dossier write must precede the auto_hypothesis call."""
    import ast

    src = (Path(__file__).resolve().parents[1] / "scripts" / "run.py").read_text()
    tree = ast.parse(src)
    lines: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if name in {"write_subskill_package", "auto_hypothesis", "write_full_package"}:
                lines.setdefault(name, []).append(node.lineno)
    for name in ("write_subskill_package", "auto_hypothesis", "write_full_package"):
        assert lines.get(name), f"run.py no longer calls {name} — the dossier wiring changed"
    early = min(lines["write_subskill_package"])
    hyp = min(lines["auto_hypothesis"])
    full = min(lines["write_full_package"])
    assert early < hyp, (
        f"write_subskill_package (line {early}) must run BEFORE auto_hypothesis (line {hyp}), or "
        "dossier_path.exists() is False and every run reports degraded inputs ['dossier']"
    )
    assert full > hyp, (
        f"write_full_package moved to line {full}, before auto_hypothesis (line {hyp}) — if the full "
        "bundle now precedes [3B] the early write is redundant and this guard should be retired"
    )
