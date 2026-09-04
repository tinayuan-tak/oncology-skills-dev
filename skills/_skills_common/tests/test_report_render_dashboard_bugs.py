"""Regression guards for the dashboard rendering bugs the multi-agent eval surfaced on the real
KRAS×COADREAD run: leaked python dicts, grey recommendation chip, empty deciding-axis, strip order."""
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render._fixtures import make_nomination
from _skills_common.report_render import build_ir, render_report, resolve_spec, vocab


def test_no_raw_python_dict_leaks_in_any_backend():
    # coherence dict + confidence.coverage dict must be formatted, never str(dict)'d into the page.
    nom = make_nomination()
    for backend in ("text", "markdown", "html"):
        out = render_report(nom, preset="full", backend=backend)
        for leak in ("{'class'", "{'n_measured'", "{'primary'", "'confirms':", "'artifact_flags'"):
            assert leak not in out, f"{backend}: raw dict leaked ({leak!r})"


def test_confidence_coverage_dict_is_formatted():
    txt = render_report(make_nomination(), preset="full", backend="text")
    assert "4/5 axes" in txt and "2 critical" in txt   # from {n_measured:4,n_axes:5,n_critical_measured:2}


def test_coherence_renders_class_not_dict():
    html = render_report(make_nomination(), preset="full", backend="html")
    assert "coherent" in html


def test_recommendation_badge_gets_semantic_color():
    # "nominate" (and the real rec vocab) must map to a colored badge class, not the grey fallback.
    nom = make_nomination()
    nom["target_report"]["target_call"]["recommendation"] = "nominate"
    html = render_report(nom, preset="full", backend="html")
    assert "badge go" in html, "recommendation 'nominate' fell through to the grey (empty-class) chip"


def test_deciding_axis_resolves_from_deciding_axes_list_not_dash():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    assert ir.deciding_short == "safety"                       # extracted from deciding_axes[0].short
    da = next(b for b in ir.overview if b.kind == vocab.DECIDING_AXIS)
    assert da.payload["title"] == "On-target safety" and da.payload["axes"]
    txt = render_report(make_nomination(), preset="full", backend="text")
    # the deciding-axis line must name the axis, not render an empty em-dash
    dline = next(ln for ln in txt.splitlines() if "deciding axis" in ln.lower())
    assert "On-target safety" in dline


def test_signals_strip_orders_killers_first():
    # the diverging strip must lead with the killer/opposing rows, matching the killers-first sections.
    # Slice from the BODY div (class='signal-strip'), NOT h.index('signal-strip') which matches the CSS
    # rule + the header's deciding mention first.
    import re
    html = render_report(make_nomination(), preset="full", backend="html")
    strip = html[html.index("class='signal-strip'"):html.index("</svg>")]
    titles = re.findall(r"font-size='12.5'[^>]*>([^<]+)<", strip)  # row title labels, in SVG order
    assert titles and titles.index("On-target safety") < titles.index("Functional dependency")
