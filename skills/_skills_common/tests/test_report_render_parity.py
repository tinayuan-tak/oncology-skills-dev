"""report_render — content-parity blocks with the legacy target_profile.html/.md: synthesis, coherence,
modality-fit matrix, literature risk, deciding axis (all report-level, spine/facet-sourced)."""

import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render import build_ir, render_report, resolve_spec, vocab
from _skills_common.report_render._fixtures import make_nomination


def _kinds(ir):
    return [b.kind for b in ir.overview]


def test_full_report_has_all_parity_blocks():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    for k in (vocab.SYNTHESIS, vocab.COHERENCE, vocab.MODALITY_MATRIX, vocab.LITERATURE_RISK, vocab.DECIDING_AXIS):
        assert k in _kinds(ir), f"missing parity block {k}"


def test_modality_matrix_block_shape():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    mm = next(b for b in ir.overview if b.kind == vocab.MODALITY_MATRIX)
    assert mm.payload["columns"][:2] == ["small_molecule", "degrader"]
    assert {r["short"] for r in mm.payload["rows"]} == {"safety", "dependency"}


def test_synthesis_and_literature_and_deciding():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    syn = next(b for b in ir.overview if b.kind == vocab.SYNTHESIS)
    assert syn.payload["executive_summary"] and len(syn.payload["arguments"]) == 2
    lit = next(b for b in ir.overview if b.kind == vocab.LITERATURE_RISK)
    assert any(d["dim"] == "safety" and d["pmids"] for d in lit.payload["dims"])
    da = next(b for b in ir.overview if b.kind == vocab.DECIDING_AXIS)
    assert da.payload["title"] == "On-target safety"


def test_level_gating_of_parity_blocks():
    l1 = _kinds(build_ir(make_nomination(), resolve_spec(level="L1")))
    assert vocab.SYNTHESIS in l1 and vocab.DECIDING_AXIS in l1
    assert vocab.MODALITY_MATRIX not in l1 and vocab.LITERATURE_RISK not in l1  # L2
    l2 = _kinds(build_ir(make_nomination(), resolve_spec(level="L2")))
    assert vocab.MODALITY_MATRIX in l2 and vocab.LITERATURE_RISK in l2


def test_html_renders_parity_content():
    h = render_report(make_nomination(), preset="full", backend="html")
    assert "Modality fit" in h and "<table" in h
    assert "AI-generated" in h and "Synthesis" in h
    assert "Literature × omics coherence" in h and "Deciding axis" in h


def test_text_and_json_render_parity():
    t = render_report(make_nomination(), preset="full", backend="text")
    assert "Modality-fit matrix" in t and "Synthesis" in t and "Literature × omics coherence" in t
    obj = json.loads(render_report(make_nomination(), preset="full", backend="json"))
    kinds = [b["kind"] for b in obj["overview"]]
    for k in (vocab.SYNTHESIS, vocab.MODALITY_MATRIX, vocab.LITERATURE_RISK):
        assert k in kinds


def test_parity_blocks_failsoft_when_sources_absent():
    # a minimal spine-only nomination (no llm_synthesis / risk_assessment / evidence_matrix / thesis)
    nom = {
        "target_report": {
            "skill_reports": {
                "safety": {
                    "role": "gating",
                    "polarity": "killer",
                    "call": "x",
                    "honest_phrase": "y",
                    "claim_chips": [],
                    "provenance": {},
                }
            }
        }
    }
    ir = build_ir(nom, resolve_spec("full"))
    present = _kinds(ir)
    for k in (vocab.SYNTHESIS, vocab.MODALITY_MATRIX, vocab.LITERATURE_RISK, vocab.COHERENCE):
        assert k not in present  # absent, not crashing
    assert render_report(nom, preset="full", backend="html")  # still renders
