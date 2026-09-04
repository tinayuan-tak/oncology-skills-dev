"""Messaging-polish guards from the multi-agent eval: thesis subtitle, plain-language strip sublabels,
'context (descriptive)' relabel, and Signals/Questions dedupe."""
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render._fixtures import make_nomination
from _skills_common.report_render import build_ir, render_report, resolve_spec, vocab


def test_header_shows_thesis_subtitle():
    for backend in ("html", "text"):
        out = render_report(make_nomination(), preset="full", backend=backend)
        assert "selective dependency with safety ceiling" in out  # thesis.primary, humanized


def test_descriptive_skill_labeled_context_not_not_scored():
    txt = render_report(make_nomination(), preset="full", backend="text")
    assert "context (descriptive)" in txt   # target_intrinsic (descriptive, call=None)


def test_signal_strip_uses_plain_language_not_snake_case():
    html = render_report(make_nomination(), preset="full", backend="html")
    strip = html[html.index("class='signal-strip'"):html.index("</svg>")]
    assert "Highly LoF-constrained" in strip        # honest_phrase, not the call token
    assert "lof_constrained" not in strip           # raw snake_case call is gone from the strip


def test_dedupe_questions_replace_chips_at_L2():
    ir = build_ir(make_nomination(), resolve_spec(level="L2"))
    safety = next(s for s in ir.sections if s.short == "safety")   # has both chips + question_table
    kinds = [b.kind for b in safety.blocks]
    assert vocab.QUESTION_TABLE in kinds and vocab.CLAIM_CHIPS not in kinds


def test_chips_still_render_at_L1_when_no_question_table_shown():
    ir = build_ir(make_nomination(), resolve_spec(level="L1"))
    safety = next(s for s in ir.sections if s.short == "safety")
    kinds = [b.kind for b in safety.blocks]
    assert vocab.CLAIM_CHIPS in kinds and vocab.QUESTION_TABLE not in kinds


def test_no_repeated_not_surfaced_noise_lines():
    txt = render_report(make_nomination(), preset="full", backend="text")
    # the old per-card "figures: not measured / per phase metrics: not measured" noise is gone
    assert "figures: not measured" not in txt.lower()
    assert txt.lower().count("not measured") <= 2   # at most the question_table coverage flag(s)
