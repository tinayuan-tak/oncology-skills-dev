"""report_render — the COMPOSED_FINGERPRINT block: the composed at-a-glance grid, the FIRST renderer of
the target_report.evidence_graph index (composed_evidence_graph.v1, #1068). It projects that index into a
lens-grouped skill grid + verdict + dissent, leading the Decision lens. Display-only / verdict-inert:
the block appears ONLY when the index is present, so pre-index nominations and the standalone single-skill
path stay byte-stable."""
import copy
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render._fixtures import make_decision_json, make_nomination
from _skills_common.report_render import (build_ir, build_ir_for_skill, render_report,
                                          resolve_spec, vocab)
from _skills_common.report_render.backends import render as render_ir


def _make_index() -> dict:
    """A representative composed_evidence_graph.v1 index (the shape tp_facets.build_composed_evidence_graph
    emits): a verdict node, skill nodes spanning all four non-decision lenses (with a deciding axis + a
    literature-consistency signal), and a typed dissent edge."""
    return {
        "schema": "composed_evidence_graph.v1",
        "verdict": {"recommendation": "nominate",
                    "confidence": {"level": "moderate"},
                    "deciding_shorts": ["dependency", "safety"]},
        "skills": [
            {"short": "dependency", "lens": vocab.LENS_SIGNALS, "role": "gating",
             "call": "genetic_dependency", "polarity": "supportive", "confidence": "high",
             "deciding": True, "has_evidence_graph": True, "literature_consistency": "consistent"},
            {"short": "selectivity", "lens": vocab.LENS_SIGNALS, "role": "gating",
             "call": "selective", "polarity": "neutral", "confidence": "moderate",
             "deciding": False, "has_evidence_graph": True, "literature_consistency": None},
            {"short": "surface_modality", "lens": vocab.LENS_MODALITY, "role": "gating",
             "call": "neither_viable", "polarity": "killer", "confidence": "low",
             "deciding": False, "has_evidence_graph": True, "literature_consistency": "contradicts"},
            {"short": "safety", "lens": vocab.LENS_RISK, "role": "gating",
             "call": "lof_constrained", "polarity": "opposing", "confidence": "moderate",
             "deciding": True, "has_evidence_graph": True, "literature_consistency": "mixed"},
            {"short": "genomic_alteration", "lens": vocab.LENS_BIOLOGY, "role": "descriptive",
             "call": "recurrent_driver", "polarity": "supportive", "confidence": "high",
             "deciding": False, "has_evidence_graph": True, "literature_consistency": None},
        ],
        "edges": [
            {"type": "deciding_axis", "from": "verdict", "to": "dependency",
             "ref": "target_report.target_call.deciding_axis"},
            {"type": "dissent", "from": "surface_modality", "to": "verdict",
             "note": "surface non-viability overruled by the intracellular dependency",
             "resolved_to": "nominate", "ref": "target_report.target_call.dissent"},
        ],
    }


def _nom_with_index() -> dict:
    nom = copy.deepcopy(make_nomination())
    nom["target_report"]["evidence_graph"] = _make_index()
    return nom


def _fingerprint(ir):
    blks = [b for b in ir.overview if b.kind == vocab.COMPOSED_FINGERPRINT]
    return blks[0] if blks else None


# -- presence + placement -----------------------------------------------------------------------
def test_block_present_and_leads_decision_lens():
    ir = build_ir(_nom_with_index(), resolve_spec("full"))
    assert _fingerprint(ir) is not None
    by = {lid: items for lid, _t, items in ir.lenses()}
    dec = [it.kind for k, it in by[vocab.LENS_DECISION] if k == "block"]
    assert vocab.COMPOSED_FINGERPRINT in dec
    assert dec[0] == vocab.COMPOSED_FINGERPRINT          # leads the Decision lens


def test_absent_without_index_byte_stable():
    """No target_report.evidence_graph → the block is never added (pre-index nominations unchanged)."""
    ir = build_ir(make_nomination(), resolve_spec("full"))
    assert _fingerprint(ir) is None


def test_absent_on_standalone_skill_report():
    """The standalone single-skill path is un-lensed and carries no composed index → no fingerprint."""
    ir = build_ir_for_skill(make_decision_json()["headline"]["skill_report"], resolve_spec("full"),
                            skill_name="on-target-safety-liability")
    assert not any(b.kind == vocab.COMPOSED_FINGERPRINT for b in ir.overview)


def test_tier_gated_off_at_L0():
    ir = build_ir(_nom_with_index(), resolve_spec(None, level="L0"))
    assert _fingerprint(ir) is None                       # TIER 1 — summary depth, not the one-page brief


# -- payload projection --------------------------------------------------------------------------
def test_lanes_grouped_in_lens_order_deciding_first():
    blk = _fingerprint(build_ir(_nom_with_index(), resolve_spec("full")))
    lanes = blk.payload["lanes"]
    order = [ln["lens"] for ln in lanes]
    # only lenses with skills appear, in canonical LENS_ORDER (Decision has no skills of its own).
    assert order == [vocab.LENS_SIGNALS, vocab.LENS_MODALITY, vocab.LENS_RISK, vocab.LENS_BIOLOGY]
    signals = next(ln for ln in lanes if ln["lens"] == vocab.LENS_SIGNALS)["skills"]
    assert [s["short"] for s in signals] == ["dependency", "selectivity"]   # deciding first, then alpha
    assert signals[0]["deciding"] is True


def test_verdict_and_dissent_carried():
    blk = _fingerprint(build_ir(_nom_with_index(), resolve_spec("full")))
    v = blk.payload["verdict"]
    assert v["recommendation"] == "nominate"
    assert v["confidence"] == "moderate"
    assert set(v["deciding_shorts"]) == {"dependency", "safety"}
    dis = blk.payload["dissent"]
    assert len(dis) == 1 and dis[0]["source"] == "surface_modality"
    assert dis[0]["resolved_to"] == "nominate"


def test_unknown_lens_skill_trails_in_stable_bucket():
    nom = _nom_with_index()
    nom["target_report"]["evidence_graph"]["skills"].append(
        {"short": "mystery", "lens": None, "role": "descriptive", "call": "x",
         "polarity": "neutral", "confidence": None, "deciding": False,
         "has_evidence_graph": False, "literature_consistency": None})
    blk = _fingerprint(build_ir(nom, resolve_spec("full")))
    assert blk.payload["lanes"][-1]["skills"][0]["short"] == "mystery"   # None-lens bucket trails


# -- rendering ------------------------------------------------------------------------------------
def test_html_renders_grid_deciding_and_dissent():
    html = render_report(_nom_with_index(), preset="full", backend="html")
    assert "At a glance" in html
    assert "cfp-chip deciding" in html                    # the deciding axis is outlined
    assert "cfp-dissent" in html and "Dissent" in html
    assert "Functional dependency" in html                # skill title, not the raw short


def test_text_renders_table_and_dissent():
    txt = render_report(_nom_with_index(), preset="full", backend="text")
    assert "At a glance" in txt
    assert "deciding" in txt                              # the role column marks the deciding axis
    assert "DISSENT" in txt.upper()


def test_json_carries_block_with_lens():
    doc = json.loads(render_report(_nom_with_index(), preset="full", backend="json"))
    fp = [b for b in (doc.get("overview") or []) if b.get("kind") == vocab.COMPOSED_FINGERPRINT]
    assert len(fp) == 1
    assert fp[0].get("lens") == vocab.LENS_DECISION       # carried so the json consumer can group it
    assert fp[0].get("lanes") and fp[0].get("verdict")
    # the Decision lens references the block in its items list (in canonical LENS_ORDER position 0)
    dec = next(l for l in doc["lenses"] if l["id"] == vocab.LENS_DECISION)
    assert dec["items"][0] == {"block": vocab.COMPOSED_FINGERPRINT}


def test_verdict_inert_spine_unchanged():
    """Attaching the index + rendering the fingerprint must not perturb the decision spine the header
    reads (recommendation / deciding axis) — it is a pure projection of an already-computed index."""
    base = build_ir(make_nomination(), resolve_spec("full")).header.payload
    withx = build_ir(_nom_with_index(), resolve_spec("full")).header.payload
    assert base["recommendation"] == withx["recommendation"]
    assert base["deciding_short"] == withx["deciding_short"]
