"""report_render — the deciding-axis headline must prefer an axis the framework can EVIDENCE, not
blindly the first entry of deciding_axes (which can lead with a framework-blind gateless lens like
cis_coherence). Surfaced by the ERBB2×BRCA example (headline read "Cis-feature coherence")."""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render import build_ir, render_report, resolve_spec, vocab
from _skills_common.report_render._fixtures import make_nomination
from _skills_common.report_render.ir import _deciding_short

# the real ERBB2×BRCA shape: a framework-blind lens leads the list, the gated+evidenced driver follows.
_ERBB2_DA = {
    "basis": "positive_signal",
    "deciding_axes": [
        {"short": "cis_coherence", "gate": None, "gate_name": None, "framework_can_evidence": "blind"},
        {"short": "genomic_alteration", "gate": "E", "gate_name": "Altered", "framework_can_evidence": "captured"},
        {
            "short": "tractability_sm",
            "gate": None,
            "gate_name": "Small-molecule druggability",
            "framework_can_evidence": "partial",
        },
    ],
}


def test_deciding_short_skips_the_framework_blind_leading_axis():
    assert (
        _deciding_short(_ERBB2_DA, {"cis_coherence", "genomic_alteration", "tractability_sm"}) == "genomic_alteration"
    )


def test_deciding_short_single_axis_is_unchanged():
    da = {"deciding_axes": [{"short": "safety", "gate_name": "On-target safety", "band": "necessity"}]}
    assert _deciding_short(da, {"safety"}) == "safety"


def test_deciding_short_all_blind_falls_back_to_first():
    da = {
        "deciding_axes": [
            {"short": "a", "framework_can_evidence": "blind"},
            {"short": "b", "framework_can_evidence": "blind"},
        ]
    }
    assert _deciding_short(da, {"a", "b"}) == "a"


def test_deciding_short_legacy_scalar_shape_still_works():
    assert _deciding_short({"short": "safety"}, {"safety"}) == "safety"


def test_header_and_signals_mark_the_evidenced_deciding_axis():
    # render-level: build a nomination whose deciding_axis leads with a blind axis; the header +
    # the signals-overview deciding marker must land on the evidenced gating axis.
    nom = make_nomination()
    nom["target_report"]["target_call"]["deciding_axis"] = _ERBB2_DA
    ir = build_ir(nom, resolve_spec("full"))
    assert ir.deciding_short == "genomic_alteration"
    assert ir.header.payload["deciding_title"] == vocab.skill_title("genomic_alteration")


def test_tension_source_is_humanized_not_raw():
    nom = make_nomination()
    # inject a tension with an internal dotted source id on the safety skill.
    nom["target_report"]["skill_reports"]["safety"]["top_tension"] = {
        "text": "constraint vs selectivity",
        "severity": "high",
        "source": "key_signals.caveat",
    }
    t = render_report(nom, preset="full", backend="text")
    assert "key_signals.caveat" not in t
    assert "key signals caveat" in t


# a no-NAMED-axis deciding_axis (gate-forced hold / "cannot decide") — routing only, no named axes.
# Surfaced by the MYC/MSLN/ALK panel: header read "Deciding axis: — — cannot decide…".
_NO_NAME_DA = {
    "basis": "no_signal",
    "deciding_axes": [],
    "routing": "cannot decide; no gate produced a signal and no coverage map available.",
}


def test_deciding_axis_no_named_axis_has_no_double_dash_placeholder_text():
    nom = make_nomination()
    nom["target_report"]["target_call"]["deciding_axis"] = _NO_NAME_DA
    t = render_report(nom, preset="full", backend="text")
    line = next(ln for ln in t.splitlines() if ln.upper().startswith("DECIDING AXIS:"))
    assert "— —" not in line and "—  —" not in line
    assert "cannot decide" in line  # routing leads


def test_deciding_axis_no_named_axis_html_has_no_empty_bold():
    nom = make_nomination()
    nom["target_report"]["target_call"]["deciding_axis"] = _NO_NAME_DA
    h = render_report(nom, preset="full", backend="html")
    assert "<b></b>" not in h and "<b>—</b> —" not in h
    assert "cannot decide" in h
