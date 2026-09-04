"""report_render — fail-soft: null-heavy and empty nominations render (every preset × string backend)
without crashing; missing expected gating slots surface as explicit `unmeasured` coverage."""
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render._fixtures import make_null_heavy_nomination
from _skills_common.report_render import (PRESETS, build_ir, render_report, resolve_spec,
                                           string_backend_names, vocab)

_BACKENDS = string_backend_names()  # binary (pptx) covered in test_report_render_pptx.py
_PRESETS = list(PRESETS) + [None]


@pytest.mark.parametrize("preset", _PRESETS)
@pytest.mark.parametrize("backend", _BACKENDS)
def test_null_heavy_renders(preset, backend):
    out = render_report(make_null_heavy_nomination(), preset=preset, backend=backend)
    assert isinstance(out, str) and out.strip(), f"empty output for {preset}/{backend}"


@pytest.mark.parametrize("preset", _PRESETS)
@pytest.mark.parametrize("backend", _BACKENDS)
def test_completely_empty_nomination_renders(preset, backend):
    for nom in ({}, {"target_report": {}}, {"target_report": {"skill_reports": {}}}):
        out = render_report(nom, preset=preset, backend=backend)
        assert isinstance(out, str) and out, f"crashed/blank on {nom} for {preset}/{backend}"


def test_gateless_call_none_falls_back_to_phrase_not_blank():
    ir = build_ir(make_null_heavy_nomination(), resolve_spec(level="L0"))
    hdrs = [b.payload for s in ir.sections for b in s.blocks if b.kind == vocab.SKILL_HEADER]
    assert hdrs and all(h["call"] is None for h in hdrs)
    txt = render_report(make_null_heavy_nomination(), level="L0", backend="text")
    assert "None" not in txt  # never leak a bare None into human output


def test_missing_gating_slot_surfaces_unmeasured():
    ir = build_ir(make_null_heavy_nomination(), resolve_spec(level="L2", scope="all"))
    sel = next(s for s in ir.sections if s.short == "selectivity")
    slots = [b.payload.get("slot") for b in sel.blocks if b.kind == vocab.UNMEASURED]
    # only the question_table coverage flag is kept; per_phase_metrics/figures no longer emit noise.
    assert "question_table" in slots
    assert "per_phase_metrics" not in slots and "figures" not in slots
