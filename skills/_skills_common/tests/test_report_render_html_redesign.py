"""report_render — the HTML redesign: light theme, target characterization in the header, signal
provenance, coherence suppression, the per-modality FIT readout, and self-contained figure inlining."""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render import build_ir, render_report, resolve_spec, vocab
from _skills_common.report_render._fixtures import make_nomination
from _skills_common.report_render.backends.html import HtmlBackend


def _ov(ir, kind):
    return next((b for b in ir.overview if b.kind == kind), None)


# -- theme + width ------------------------------------------------------------------------------
def test_light_theme_and_wide_content():
    h = render_report(make_nomination(), preset="full", backend="html")
    assert "color-scheme:light" in h and "--surface:#fcfcfb" in h  # light-first validated surface
    assert "max-width:1120px" in h  # widened content column


# -- header target characterization -------------------------------------------------------------
def test_header_carries_archetype_characterization():
    nom = make_nomination()
    nom["target_report"]["archetype"] = {
        "phenotype_mixture": {
            "control_housekeeping": 0.5,
            "amp_driver": 0.34,
            "dependency_essential": 0.12,
            "snv_driver": 0.02,
        }
    }
    ir = build_ir(nom, resolve_spec("full"))
    char = ir.header.payload.get("characterization")
    assert char and [m["label"] for m in char["mixture"]][0] == "housekeeping / broadly-essential control"
    assert len(char["mixture"]) == 3  # top-3, weight >= 8% (0.02 dropped)
    h = render_report(nom, preset="full", backend="html", target="MYC", indication="BRCA")
    assert "Target characterization" in h and "char-chip" in h and "50%" in h
    # the one-word recommendation is subordinate (a 'rec' line), not a shouty 'badge' pill.
    assert "Provisional call" in h and "class='rec" in h


# -- signal provenance --------------------------------------------------------------------------
def test_signals_carry_rollup_provenance():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    sov = _ov(ir, vocab.SIGNALS_OVERVIEW)
    assert all("n_cards" in r for r in sov.payload["rows"])
    h = render_report(make_nomination(), preset="full", backend="html")
    assert "rolled up from its" in h and "cards" in h  # the explanatory lede + per-row count


# -- coherence suppression ----------------------------------------------------------------------
def test_trivial_coherence_is_suppressed():
    nom = make_nomination()
    nom["target_report"]["thesis"]["coherence"] = {
        "class": "coherent",
        "caveats": [],
        "confirms": [],
        "artifact_flags": [],
    }
    assert _ov(build_ir(nom, resolve_spec("full")), vocab.COHERENCE) is None  # bare "coherent" → dropped
    # the shipped fixture HAS a caveat → the block emits.
    assert _ov(build_ir(make_nomination(), resolve_spec("full")), vocab.COHERENCE) is not None


# -- per-modality FIT readout -------------------------------------------------------------------
def test_modality_fit_channel_readout_and_grid_drilldown():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    mm = _ov(ir, vocab.MODALITY_MATRIX)
    assert mm and mm.payload.get("channels"), "per-channel readout must be built from modality_fit_by_channel"
    ch = {c["channel"]: c for c in mm.payload["channels"]}
    # fixture MYC-like: small_molecule + degrader unfavorable (safety); biologics/adc/... not applicable.
    assert ch["small_molecule"]["status"] in ("unfavorable", "conditional", "viable")
    assert any(c["status"] == "not_applicable" for c in mm.payload["channels"])
    h = render_report(make_nomination(), preset="full", backend="html")
    assert "Modality fit" in h and "mod-fit" in h and "pill" in h
    assert "Per-axis × modality detail" in h  # raw grid demoted to a drill-down
    assert "Modality-fit matrix" not in h  # the old abstract-grid heading is gone


# -- self-contained figure inlining -------------------------------------------------------------
def test_svg_inlined_as_data_uri_when_asset_root_given(tmp_path):
    svg = tmp_path / "figures" / "cards" / "c" / "f.svg"
    svg.parent.mkdir(parents=True)
    svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>")
    be = HtmlBackend(asset_root=tmp_path)
    src = be._inline_src("figures/cards/c/f.svg")
    assert src and src.startswith("data:image/svg+xml;base64,")
    assert HtmlBackend(asset_root=None)._inline_src("figures/cards/c/f.svg") is None  # no root → relative
    assert be._inline_src("figures/cards/c/missing.svg") is None  # missing → relative
    assert be._inline_src("../escape.svg") is None  # path-escape guarded


def test_oversized_svg_not_inlined(tmp_path):
    svg = tmp_path / "big.svg"
    svg.write_text("<svg>" + "x" * 200_000 + "</svg>")
    assert HtmlBackend(asset_root=tmp_path)._inline_src("big.svg") is None  # > cap → falls back to relative


# -- primary-per-card grouping ------------------------------------------------------------------
def test_secondary_figures_collapse_into_details():
    # dependency section has 1 primary + many secondary card figures → secondaries behind a <details>.
    from _skills_common.report_render.backends import BACKENDS

    ir = build_ir(make_nomination(), resolve_spec("full"))
    h = BACKENDS["html"]().render(ir)
    # the fixture's dependency card has a primary + a secondary SVG → a "more figure(s)" disclosure.
    assert "more figure(s)" in h


def test_characterization_surfaces_nearest_analogs():
    """Ph3b: the archetype 'what is this LIKE' anchor — nearest_analogs (self-anchor [0] skipped)
    render in the header characterization."""
    from _skills_common.report_render.ir import _target_characterization

    nom = make_nomination()
    nom["target_report"]["archetype"] = {
        "phenotype_mixture": {"snv_driver": 1.0},
        "nearest_analogs": [
            {"target": "KRAS", "indication": "COADREAD", "archetype_label": "snv_driver"},  # self-anchor
            {"target": "BRAF", "indication": "COADREAD", "archetype_label": "snv_driver"},
            {"target": "CDK4", "indication": "LUAD", "archetype_label": "amp_driver"},
        ],
    }
    c = _target_characterization(nom["target_report"])
    assert [(a["target"], a["indication"]) for a in c["analogs"]] == [("BRAF", "COADREAD"), ("CDK4", "LUAD")]
    h = render_report(nom, preset="full", backend="html")
    assert "nearest analogs" in h and "BRAF" in h and "CDK4" in h


def test_consolidation_design_tokens_present():
    """Dashboard consolidation Phase 2: the single design system carries the CVD-safe diverging pair
    (--pos/--neg), the hold tint (--t-hold), and the omics-vs-literature FACT axis (--det/--lit) —
    additive to the reserved status palette, which must remain."""
    h = render_report(make_nomination(), preset="full", backend="html")
    for tok in ("--pos:", "--neg:", "--t-hold:", "--det:", "--lit:", "--t-lit:"):
        assert tok in h, f"missing consolidation token {tok}"
    # existing reserved status tokens are NOT renamed/removed
    for tok in ("--supportive:", "--opposing:", "--killer:", "--good:", "--hold:"):
        assert tok in h, f"status token regressed: {tok}"
    # the literature dot reads pre-attentively via a --lit ring (two-tone omics/lit)
    assert "border:2px solid var(--lit)" in h
