"""Deciding-axis router tests (L, 2026-07-20).

The router turns a bare `insufficient_evidence` into a routing statement — WHICH gate is
load-bearing for the run + whether the framework can evidence it. These tests pin the three
bases and, critically, the HONESTY guardrail: the router REPORTS (a fired gate is the deciding
axis; on abstention it lists unevidenced gates) and never PREDICTS a single axis prospectively.
They also pin that it is purely additive — it reads already-resolved state and returns a block,
touching no verdict — and that per-run coverage DOWNGRADES (never upgrades) the static baseline.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"
CONTRACTS = Path(os.environ.get("TARGET_CONTRACTS_ROOT",
                                "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))


def _load():
    spec = importlib.util.spec_from_file_location("tp_run", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()


def _sr(**verdicts):
    """Build a minimal sub_results dict. Each kwarg short=verdict_str (or None). Cards default
    to one present card so _sub_result_has_signal keys off the verdict; pass cards=... to override."""
    out = {}
    for short, v in verdicts.items():
        out[short] = {
            "skill_dir": short, "cards": [{"card_id": f"{short}-card"}],
            "fired": [{"rule_id": f"{short}-rule"}] if v else [],
            "verdict": (v, f"{short}-rule") if v else None,
        }
    return out


# ---------- basis 1: a gate FIRED → the deciding axis is that gate (known, not predicted) ----------

def test_fired_gate_is_the_deciding_axis_captured():
    sr = _sr(dependency="non_dependent", expression="broadly_high")
    gate_hits = [{"short": "dependency", "verdict": "non_dependent", "action": "veto",
                  "driving_rule_id": "non-dependent-killer"}]
    da = tp._deciding_axis(sr, gate_action="veto", gate_hits=gate_hits, positive_hits=[],
                           contracts_repo=CONTRACTS)
    assert da["basis"] == "gate_fired"
    assert da["deciding_axis"]["short"] == "dependency"
    assert da["deciding_axis"]["gate"] == "C"
    # a gate that FIRED was, by definition, evidenced → captured (not the static 'partial')
    assert da["deciding_axis"]["framework_can_evidence"] == "captured"


# ---------- basis 2: a positive tier → strongest positive dimension is load-bearing ----------

def test_positive_tier_names_supporting_axes():
    sr = _sr(dependency="concordant_dependent", selectivity="strong_tumor_selective")
    pos_hits = [{"short": "dependency"}, {"short": "selectivity"}]
    da = tp._deciding_axis(sr, gate_action=None, gate_hits=[], positive_hits=pos_hits,
                           contracts_repo=CONTRACTS)
    assert da["basis"] == "positive_signal"
    shorts = {r["short"] for r in da["deciding_axes"]}
    assert shorts == {"dependency", "selectivity"}


# ---------- basis 3: abstention → list the unevidenced NECESSITY gates first ----------

def test_abstention_lists_unevidenced_gates_necessity_first():
    # dependency evidenced; surface_modality (sufficiency, baseline blind) + safety (sufficiency)
    # + mechanism (necessity) unevidenced.
    sr = _sr(dependency="concordant_dependent", surface_modality=None, safety=None, mechanism=None)
    da = tp._deciding_axis(sr, gate_action=None, gate_hits=[], positive_hits=[],
                           contracts_repo=CONTRACTS)
    assert da["basis"] == "abstention_coverage_gaps"
    unev = da["unevidenced_gates"]
    shorts = [g["short"] for g in unev]
    assert "dependency" not in shorts, "an evidenced gate must not be listed as unevidenced"
    assert {"surface_modality", "safety", "mechanism"} <= set(shorts)
    # necessity gates rank BEFORE sufficiency gates (the routing instruction leads with the
    # framework's own lane).
    bands = [g["band"] for g in unev]
    first_suff = bands.index("sufficiency") if "sufficiency" in bands else len(bands)
    assert all(b == "necessity" for b in bands[:first_suff])


# ---------- per-run coverage DOWNGRADES (never upgrades) the static baseline ----------

def test_all_cards_missing_downgrades_to_blind():
    """dependency baseline is `partial`; if every dependency card came back _missing this run,
    the per-run coverage is `blind` (we could not look), not the baseline partial."""
    sr = {"dependency": {"skill_dir": "functional-requirement",
                         "cards": [{"card_id": "crispr", "_missing": True},
                                   {"card_id": "rnai", "_missing": True}],
                         "fired": [], "verdict": None}}
    baseline, _ = tp._load_gate_coverage(CONTRACTS)
    assert baseline["dependency"]["framework_can_evidence"] == "partial"  # static
    assert tp._run_coverage_for_short("dependency", sr["dependency"], baseline) == "blind"  # per-run


def test_run_coverage_never_upgrades_above_baseline():
    """surface_modality baseline is `blind`; even with a present card + a fired rule the router
    must not UPGRADE it to captured (the framework is structurally blind on the deciding axis)."""
    r = {"cards": [{"card_id": "surf"}], "fired": [{"rule_id": "x"}], "verdict": ("something", "x")}
    baseline, _ = tp._load_gate_coverage(CONTRACTS)
    assert baseline["surface_modality"]["framework_can_evidence"] == "blind"
    assert tp._run_coverage_for_short("surface_modality", r, baseline) == "blind"


# ---------- degrade safely when the vocab is absent ----------

def test_missing_vocab_degrades_to_bare_note_not_fabricated_coverage(tmp_path):
    """With no gate_coverage.yaml, the router must not invent a coverage claim — it returns a
    bare abstention note (empty baseline → source 'none')."""
    sr = _sr(dependency=None)
    da = tp._deciding_axis(sr, gate_action=None, gate_hits=[], positive_hits=[],
                           contracts_repo=tmp_path)  # tmp_path has no vocabularies/
    assert da["coverage_source"] == "none"
    assert da["basis"] == "abstention_coverage_gaps"
