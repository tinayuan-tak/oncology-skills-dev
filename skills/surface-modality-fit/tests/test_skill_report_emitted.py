"""Guard: `_headline` emits the UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the Wave-3
skill_report adoption for surface-modality-fit (8th / LAST gating adopter; the 2nd killer-override skill).
The `neither_viable` VETO (neither ADC nor TCE viable) must surface as canonical `killer` (not the
3-band→canonical `opposing` floor); a viable/preferred call maps to `supportive`; best-effort degrade.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))


def _load():
    spec = importlib.util.spec_from_file_location("surf_run_sr", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


surf = _load()


def _cards(fit_class):
    # fit_class is read from the adc-tce-modality-fit card summary (not verdict_pair).
    cs = [{"card_id": cid, "summary": {}} for cid in surf.CARDS]
    for c in cs:
        if c["card_id"] == "adc-tce-modality-fit":
            c["summary"] = {"fit_class": fit_class}
    return cs


def _sr(fit_class, rule="r"):
    hl = surf._headline(_cards(fit_class), [], (fit_class, rule))
    return hl, hl.get("skill_report")


def test_neither_viable_veto_is_canonical_killer():
    hl, sr = _sr("neither_viable", "surface-neither-viable-veto")
    assert isinstance(sr, dict)
    assert sr["role"] == "gating"
    assert sr["call"] == "neither_viable"
    assert sr["polarity"] == "killer"                    # NOT "opposing"
    assert "skill_report" in surf._SYNTHESIS_FACET_KEYS


def test_both_viable_maps_to_supportive_no_override():
    _hl, sr = _sr("both_viable", "surface-both-viable")
    assert sr["call"] == "both_viable"
    assert sr["polarity"] == "supportive"                # positive → supportive (no killer override)


def test_skill_report_fault_degrades_not_aborts(monkeypatch):
    def _boom(*_a, **_k):
        raise ValueError("simulated skill_report fault")

    monkeypatch.setattr(surf, "build_skill_report", _boom)
    hl = surf._headline(_cards("neither_viable"), [], ("neither_viable", None))
    assert hl["fit_class"] == "neither_viable"           # spine survives the projection fault
    assert hl["skill_report"] is None
    assert hl["_enrichment_errors"]["skill_report"].startswith("ValueError")
