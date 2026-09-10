"""report_render — report-level overview blocks (signals_overview diverging strip + risk_6dim tiles),
absorbed from the tp_dashboard v2 design and re-sourced from the spine."""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render import build_ir, build_ir_for_skill, render_report, resolve_spec, vocab
from _skills_common.report_render._fixtures import make_decision_json, make_nomination


def _overview_kinds(ir):
    return [b.kind for b in ir.overview]


def _ov_block(ir, kind):
    return next((b for b in ir.overview if b.kind == kind), None)


def test_build_ir_emits_both_overview_blocks_at_full():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    assert vocab.SIGNALS_OVERVIEW in _overview_kinds(ir)
    assert vocab.RISK_6DIM in _overview_kinds(ir)


def test_signals_overview_rows_are_scored_skills_killer_first():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    sov = next(b for b in ir.overview if b.kind == vocab.SIGNALS_OVERVIEW)
    shorts = [r["short"] for r in sov.payload["rows"]]
    assert shorts[0] == "safety"  # killer (level -3) sorts to the top
    assert "dependency" in shorts  # supportive gating skill
    assert "Target-intrinsic dossier" in sov.payload["descriptive"]  # descriptive → footnote (title), not a bar
    assert sov.payload["counts"]["against"] >= 1 and sov.payload["counts"]["support"] >= 1


def test_risk_6dim_has_ordered_dims_with_bins():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    r6 = next(b for b in ir.overview if b.kind == vocab.RISK_6DIM)
    dims = {d["dim"]: d for d in r6.payload["dims"]}
    assert dims["safety"]["rank"] == 3 and dims["safety"]["bin"] == "HIGH"
    assert dims["commercial"]["rank"] is None  # ENGINE-BLIND → off-scale rank
    assert [d["dim"] for d in r6.payload["dims"]][:2] == ["biological", "druggability"]  # canonical order


def test_risk_6dim_spine_surfaces_feeding_members():
    """Each dimension enumerates its FULL member set — every AXIS_TO_DIM verdict-bearing subskill (present
    in the composed skill_reports) PLUS the gateless `context` companions — each carrying a rich
    plain-language reading + a `full ↗` external deep-link (subskills/<short>/dashboard.html) to the
    standalone page. Without skill_reports (a bare call) members fall back to the chain [source, read, level]."""
    from _skills_common.report_render.backends.html import HtmlBackend
    from _skills_common.report_render.ir import _risk_6dim_block

    r6 = {
        "safety": {
            "bin": "HIGH",
            "chain": [
                ["on-target-safety", "highly_constrained [LOEUF 0.23]", "HIGH"],
                ["sc-normal", "HIGH_LIABILITY", "MED"],
            ],
            "blind_spots": ["off-target / secondary pharmacology"],
        },
        "biological": {"bin": "LOW", "chain": [["dependency", "lineage_selective", "LOW"]]},
    }
    # (a) bare call — no skill_reports: members fall back to the chain [source, read, level].
    bare = {d["dim"]: d for d in _risk_6dim_block(r6).payload["dims"]}
    assert bare["safety"]["members"][0]["short"] == "on-target-safety"
    assert bare["safety"]["members"][0]["read"] == "highly_constrained [LOEUF 0.23]"
    assert bare["safety"]["blind_spots"] == ["off-target / secondary pharmacology"]

    # (b) composed call — with skill_reports: the FULL mapped member set + rich readings + deep-links.
    skill_reports = {
        "safety": {"call": "lof_constrained", "honest_phrase": "Highly LoF-constrained"},
        "selectivity": {"call": "not_selective", "honest_phrase": "Discordant across normal comparators"},
        "dependency": {"call": "lineage_selective", "honest_phrase": "Lineage-selective dependency"},
        "mechanism": {"call": "well_characterized", "honest_phrase": "Well-characterized network"},
        "cis_coherence": {"call": "coherent_cis_addiction"},  # no prose → class-label fallback
    }
    risk_assessment = {"dimensions": {"safety": {"interpretation": "gnomAD LoF-constrained", "cited_pmids": ["1"]}}}
    blk = _risk_6dim_block(r6, skill_reports, risk_assessment)
    dims = {d["dim"]: d for d in blk.payload["dims"]}
    safety_shorts = [m["short"] for m in dims["safety"]["members"]]
    assert safety_shorts == ["selectivity", "safety"]  # both AXIS_TO_DIM safety subskills, canonical order
    m_safety = {m["short"]: m for m in dims["safety"]["members"]}["safety"]
    assert m_safety["skill_dir"] == "on-target-safety-liability"  # short → skill-dir badge
    assert m_safety["read"] == "Highly LoF-constrained" and m_safety["fallback"] is False  # honest_phrase reading
    # EXTERNAL deep-link to the standalone subskills/<short>/dashboard.html page (composed HTML no longer
    # inlines per-subskill dashboards, so the old same-page #skill-<short> anchors were retired).
    assert m_safety["dashboard"] == "subskills/safety/dashboard.html"
    assert dims["safety"]["literature"]["interpretation"] == "gnomAD LoF-constrained"
    bio_members = {m["short"]: m for m in dims["biological"]["members"]}
    assert "dependency" in bio_members and "mechanism" in bio_members  # verdict-bearing
    assert bio_members["cis_coherence"]["context"] is True  # gateless companion, tagged context
    assert bio_members["cis_coherence"]["fallback"] is True  # no prose → class-label fallback (call)
    assert bio_members["cis_coherence"]["read"] == "coherent_cis_addiction"  # falls back to the class label

    # v6 assessment spine: one <details class="dim risk-…"> per dimension with a .dbar + a .dmembers table.
    h = "".join(HtmlBackend()._risk_6dim(blk.payload))
    assert 'class="dim risk-high' in h and 'class="dim risk-low' in h  # per-dim tiles, LOW=green
    assert "dbar" in h and "dmembers" in h and "class='mem'" in h  # positioned bar + member rows
    assert "class='full' href='subskills/safety/dashboard.html'" in h  # external standalone-page deep-link
    assert "class='ctxtag'" in h and "blind spots" in h  # context tag + blind-spot line
    assert "text-mined" in h  # verdict-inert literature line


def test_level_gates_overview():
    # signals_overview is L0 (the lead); risk_6dim is L1+
    l0 = _overview_kinds(build_ir(make_nomination(), resolve_spec(level="L0")))
    assert vocab.SIGNALS_OVERVIEW in l0 and vocab.RISK_6DIM not in l0
    l1 = _overview_kinds(build_ir(make_nomination(), resolve_spec(level="L1")))
    assert vocab.RISK_6DIM in l1


def test_single_skill_has_no_overview():
    ir = build_ir_for_skill(
        make_decision_json()["headline"]["skill_report"], resolve_spec("full"), skill_name="on-target-safety-liability"
    )
    assert ir.overview == []


def test_html_renders_svg_strip_and_risk_tiles():
    # the diverging strip + risk-tiles are the SIGNALS_OVERVIEW block. The composed v6 HTML no longer emits
    # the decision-detail fold that carried it, so assert the HTML block-render capability directly (the
    # block is still in the IR + rendered by the other backends).
    from _skills_common.report_render.backends.html import HtmlBackend

    ir = build_ir(make_nomination(), resolve_spec("full"))
    sov = _ov_block(ir, vocab.SIGNALS_OVERVIEW)
    html = "".join(HtmlBackend()._emit(sov))
    assert "<svg" in html and "signal-strip" in html  # the diverging strip
    assert "Signals across subskills" in html
    # the risk-tile design tokens remain in the composed stylesheet (the tile ELEMENT is drawn by the
    # 6-dim spine's own .dim tiles; the .risk-tile CSS is kept for the standalone/other surfaces).
    full = render_report(make_nomination(), preset="full", backend="html")
    assert "risk-tiles" in full and "risk-tile" in full


def test_text_and_json_render_overview():
    txt = render_report(make_nomination(), preset="full", backend="text")
    assert "Signals across skills" in txt and "risk by dimension" in txt.lower()
    import json

    obj = json.loads(render_report(make_nomination(), preset="full", backend="json"))
    kinds = [b["kind"] for b in obj["overview"]]
    assert vocab.SIGNALS_OVERVIEW in kinds and vocab.RISK_6DIM in kinds


def _nom_with(dep_polarity, thesis_primary):
    """A make_nomination() copy with the dependency skill_report polarity + coherence thesis overridden,
    for exercising the surface-antigen thesis reconciliation of the diverging strip."""
    import copy

    nom = copy.deepcopy(make_nomination())
    tr = nom["target_report"]
    tr["skill_reports"]["dependency"]["polarity"] = dep_polarity
    tr["skill_reports"]["dependency"]["call"] = "non_dependent_paralog_buffered"
    tr["skill_reports"]["dependency"]["honest_phrase"] = "Not dependent (paralog-buffered)"
    tr["thesis"]["thesis"]["primary"] = thesis_primary
    return nom


def _sov(ir):
    return next(b for b in ir.overview if b.kind == vocab.SIGNALS_OVERVIEW)


def test_dependency_negative_reconciled_under_surface_antigen_thesis():
    # ERBB2-shape: a measured-negative dependency under a surface-antigen thesis is EXPECTED (orthogonal
    # to the ADC/TCE MoA), so the strip must NOT count it "against" — it renders neutral + a reason note.
    ir = build_ir(_nom_with("opposing", "surface_antigen_no_dependency"), resolve_spec("full"))
    dep = next(r for r in _sov(ir).payload["rows"] if r["short"] == "dependency")
    assert dep["polarity"] == "neutral" and dep["level"] == 0
    assert dep["raw_polarity"] == "opposing"
    assert dep["expected_note"] and "surface-antigen" in dep["expected_note"]
    # tally reflects the reframe: dependency is not in `against`.
    counts = _sov(ir).payload["counts"]
    dep_calls = [r for r in _sov(ir).payload["rows"] if r["short"] == "dependency"]
    assert dep_calls and dep_calls[0]["level"] == 0
    assert counts["against"] == sum(1 for r in _sov(ir).payload["rows"] if (r["level"] or 0) < 0)


def test_dependency_negative_still_counts_against_intracellular_thesis():
    # SAME negative dependency, but an intracellular/driver thesis → NOT reconciled; still counts against.
    ir = build_ir(_nom_with("opposing", "oncogene_addiction_driver"), resolve_spec("full"))
    dep = next(r for r in _sov(ir).payload["rows"] if r["short"] == "dependency")
    assert dep["polarity"] == "opposing" and (dep["level"] or 0) < 0
    assert dep.get("expected_note") is None and dep.get("raw_polarity") is None


def test_reconciliation_note_reaches_backends():
    from _skills_common.report_render.backends.html import HtmlBackend

    nom = _nom_with("opposing", "amplification_overexpression_antigen")
    txt = render_report(nom, preset="full", backend="text")
    assert "orthogonal to the ADC/TCE mechanism" in txt
    # the composed v6 HTML no longer emits the signals-overview fold — assert the HTML block-render
    # capability directly (the reconciliation note still reaches the SIGNALS_OVERVIEW block payload).
    ir = build_ir(nom, resolve_spec("full"))
    html = "".join(HtmlBackend()._emit(_ov_block(ir, vocab.SIGNALS_OVERVIEW)))
    assert "orthogonal to the ADC/TCE mechanism" in html


def test_overview_failsoft_without_risk_or_signals():
    # a nomination with no risk_6dim and no gating skills → no overview blocks, no crash
    nom = {
        "target_report": {
            "skill_reports": {
                "target_intrinsic": {
                    "role": "descriptive",
                    "polarity": "not_scored",
                    "call": None,
                    "honest_phrase": "x",
                    "claim_chips": [],
                    "provenance": {},
                },
            }
        }
    }
    ir = build_ir(nom, resolve_spec("full"))
    assert ir.overview == []
    assert render_report(nom, preset="full", backend="html")  # renders fine
