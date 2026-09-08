"""report_render — Tier-4 messaging polish: rule-id citations lifted out of synthesis prose, modality
matrix cleanup (drop all-off rows + inline glyph legend + cell shading + collapsed caveat), internal
confidence-vocab gloss, and snake_case call humanized in skill headers."""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render import build_ir, render_report, resolve_spec, vocab
from _skills_common.report_render._fixtures import make_nomination
from _skills_common.report_render.ir import _strip_rule_citations


# -- 1. synthesis rule-id citations -------------------------------------------------------------
def test_strip_rule_citations_lifts_only_rule_id_brackets():
    clean, cites = _strip_rule_citations(
        "A is a driver [alteration-role-gof-driver-supportive] and constrained [SAF-LOF-01]. See [Fig 2]."
    )
    assert "[alteration-role-gof-driver-supportive]" not in clean and "[SAF-LOF-01]" not in clean
    assert "[Fig 2]" in clean  # a non-citation bracket is preserved
    assert cites == ["alteration-role-gof-driver-supportive", "SAF-LOF-01"]
    assert "  " not in clean and " ." not in clean  # tidy whitespace/punctuation


def test_synthesis_block_prose_is_clean_and_citations_collected():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    syn = next(b for b in ir.overview if b.kind == vocab.SYNTHESIS)
    assert "[" not in syn.payload["executive_summary"]
    assert "[" not in (syn.payload["tension_analysis"] or "")
    cites = syn.payload["citations"]
    assert "dependency-mutant-strongly-dependent-supportive" in cites
    assert "SAF-LOF-01" in cites and "SAF-DOSAGE-02" in cites
    assert "lineage-selective-supportive" in cites  # lifted from an argument claim too
    assert len(cites) == len(set(cites))  # deduped


def test_html_synthesis_shows_collapsed_citation_provenance():
    h = render_report(make_nomination(), preset="full", backend="html")
    assert "<details class='cite-prov'>" in h and "Grounded in" in h
    assert "<code>SAF-LOF-01</code>" in h
    # the rule-id must NOT appear in the executive prose paragraph itself.
    assert "[SAF-LOF-01" not in h


def test_text_synthesis_footnotes_the_rules():
    t = render_report(make_nomination(), preset="full", backend="text")
    assert "Grounded in" in t and "SAF-LOF-01" in t
    assert "[SAF-LOF-01" not in t


# -- 2. modality matrix cleanup -----------------------------------------------------------------
def test_all_off_scale_row_is_dropped():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    mm = next(b for b in ir.overview if b.kind == vocab.MODALITY_MATRIX)
    shorts = {r["short"] for r in mm.payload["rows"]}
    assert "translational_readiness" not in shorts  # all-`·` row dropped
    assert shorts == {"safety", "dependency"}
    assert mm.payload.get("glyph_legend")  # inline legend present


def test_html_matrix_shades_cells_and_collapses_disclaimer():
    h = render_report(make_nomination(), preset="full", backend="html")
    assert "td class='mx-pos'" in h  # supportive cell shaded
    assert "td class='mx-killer'" in h or "td class='mx-neg'" in h
    assert "Per-axis × modality detail" in h  # raw grid + caveats collapsed into <details>
    assert "not calibrated measurement" in h  # full caveat retained inside the details


def test_text_matrix_has_glyph_legend_and_collapsed_caveat():
    t = render_report(make_nomination(), preset="full", backend="text")
    assert "order-preserving ordinal" in t
    assert "Full caveat in provenance." in t


# -- 3. confidence vocab gloss ------------------------------------------------------------------
def test_certainty_model_sidecar_is_glossed():
    nom = make_nomination()
    nom["target_report"]["target_call"]["confidence"] = {
        "level": "strong",
        "basis": "certainty_model_sidecar",
        "coverage": {"n_measured": 3, "n_axes": 4, "n_critical_measured": 1},
    }
    t = render_report(nom, preset="full", backend="text")
    assert "certainty_model_sidecar" not in t
    assert "cross-axis certainty model" in t


# -- 4. snake_case call humanized in headers ----------------------------------------------------
def test_skill_header_call_is_humanized():
    # fixture dependency call = "genetic_dependency" → header reads "genetic dependency".
    t = render_report(make_nomination(), preset="full", backend="text")
    assert "genetic dependency" in t
    assert "genetic_dependency" not in t
    h = render_report(make_nomination(), preset="full", backend="html")
    assert "genetic_dependency" not in h
