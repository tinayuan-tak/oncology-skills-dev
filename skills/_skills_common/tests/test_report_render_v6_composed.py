"""report_render — the composed HTML renders the approved redesign-v6 convergence layout: a sticky
3-column hero (identity + verdict chip + 6-dim glance), a standout headline, the archetype + convergence
folds, and a 3-view switch (6-dimension assessment / modality / lit×omics). Verdict-inert — the layout is
a pure re-projection of the same IR blocks; the decision spine is untouched.
"""

from _skills_common.report_render import build_ir, build_ir_for_skill, render_report, resolve_spec
from _skills_common.report_render._fixtures import make_decision_json, make_nomination

# the v6 structural signature — every load-bearing class of the single-scroll convergence layout.
_V6_SIGNATURE = (
    "hero",
    "hgrid",
    "dimmini",
    "vchip",
    "headline",
    "class='fold'",
    "causal",
    "cflow",
    "ebul",
    "tension",
    "views",
    "data-v",
    'class="dim ',
    "dbar",
    "dmembers",
    "cohtab",
    "mbul",
    "matrix",
)


def test_composed_html_is_the_v6_convergence_layout():
    h = render_report(make_nomination(), preset="full", backend="html")
    for cls in _V6_SIGNATURE:
        assert cls in h, f"v6 signature class missing from composed HTML: {cls!r}"
    # the OLD 5-radio-tab lens shell + risk-tile spine are gone from the composed layout.
    assert "class='lens-tabs'" not in h and "class='lens-radio'" not in h
    assert "class='risk-tile" not in h  # (CSS token may remain, but no rendered risk-tile element)


def test_v6_hero_is_three_column_with_verdict_and_glance():
    h = render_report(make_nomination(), preset="full", backend="html")
    # sticky hero, verdict chip, and the 6-dim glance rows all present.
    assert "<header class='hero'>" in h and "class='hgrid'" in h
    assert "class='vchip" in h  # the go/hold/kill verdict chip
    assert "class='dimmini'" in h and "mtrack" in h  # the 6-dim glance with positioned bars


def test_v6_three_view_switch_and_sections():
    h = render_report(make_nomination(), preset="full", backend="html")
    assert "data-v='assess'" in h and "data-v='modality'" in h and "data-v='coherence'" in h
    assert "id='v-assess'" in h and "id='v-modality'" in h and "id='v-coherence'" in h


def test_v6_layout_is_composed_only_standalone_stays_flat():
    """The v6 hero is the COMPOSED path only — the standalone single-skill IR (build_ir_for_skill, no
    lenses) keeps the flat header + section fallback, never the 3-column hero / 3-view switch."""
    from _skills_common.report_render.backends.html import HtmlBackend

    ir = build_ir_for_skill(
        make_decision_json()["headline"]["skill_report"], resolve_spec("full"), skill_name="on-target-safety-liability"
    )
    assert ir.lenses() == []  # un-lensed → flat fallback
    flat = HtmlBackend().render(ir)
    assert "<header class='hero'>" not in flat and "class='views'" not in flat


def test_v6_verdict_inert_header_payload_unchanged_shape():
    """The v6 hero enrichment ADDS display context to the header payload (risk_dims / literature /
    clinical_precedent / groundedness) — it never removes the decision fields the spine carries."""
    ir = build_ir(make_nomination(), resolve_spec("full"))
    p = ir.header.payload
    for k in ("recommendation", "confidence", "deciding_axis", "gate"):
        assert k in p, f"decision field {k} dropped from header payload"
    assert "risk_dims" in p and isinstance(p["risk_dims"], list)


def test_synthesis_degradation_reader_none_when_trail_clean():
    """A run whose narration validated cleanly (no salvage/recovery/truncation) surfaces NO degradation
    telemetry — the report stays byte-stable and the note never renders."""
    from _skills_common.report_render.ir import _synthesis_degradation

    assert _synthesis_degradation(make_nomination()) is None
    assert build_ir(make_nomination(), resolve_spec("full")).header.payload["synthesis_degradation"] is None
    h = render_report(make_nomination(), preset="full", backend="html")
    assert "synthesis degraded" not in h


def test_synthesis_degradation_reader_surfaces_salvage_and_truncation():
    """A salvaged/truncated narration must reach the reader — the degradation note is rendered beside the
    trust badge (mirroring the JSON's fail-visible salvage trail). Verdict-inert display telemetry."""
    from _skills_common.report_render.ir import _synthesis_degradation

    nom = make_nomination()
    nom["llm_synthesis"]["_malformed_fields"] = ["top_arguments_for"]
    nom["llm_synthesis"]["_recovered_fields"] = ["top_arguments_against"]
    nom["llm_synthesis"]["_truncated"] = True
    deg = _synthesis_degradation(nom)
    assert deg == {
        "truncated": True,
        "malformed_fields": ["top_arguments_for"],
        "recovered_fields": ["top_arguments_against"],
    }
    h = render_report(nom, preset="full", backend="html")
    assert "synthesis degraded" in h
    assert "output truncated at token cap" in h
    assert "1 field salvaged" in h
