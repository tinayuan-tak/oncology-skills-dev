"""report_render — Tier-4 messaging polish: rule-id citations lifted out of synthesis prose, modality
matrix cleanup (drop all-off rows + inline glyph legend + cell shading + collapsed caveat), internal
confidence-vocab gloss, and snake_case call humanized in skill headers."""

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
    # #2393: target-profile's real schema is top_arguments_for/top_arguments_against; _synthesis_block
    # reads those first (falling back to the legacy top_arguments/arguments shape only when both are
    # absent), so the citations lifted from the fixture's for/against arguments are these two, not the
    # legacy top_arguments claim's "lineage-selective-supportive".
    assert "strongly-selective-supportive" in cites and "gnomad-lof-constrained-veto" in cites
    assert len(cites) == len(set(cites))  # deduped


def test_synthesis_block_reads_top_arguments_for_against_not_legacy_keys():
    # #2393: top_arguments_for/top_arguments_against is the real target-profile Tier-3 schema key; the
    # legacy top_arguments/arguments shape is a fixture-only convenience the real pipeline never emits.
    ir = build_ir(make_nomination(), resolve_spec("full"))
    syn = next(b for b in ir.overview if b.kind == vocab.SYNTHESIS)
    claims = [a["claim"] for a in syn.payload["arguments"]]
    assert "Selective MSI-high dependency" in claims
    assert "Full-KO safety risk from LoF constraint" in claims
    stances = {a["stance"] for a in syn.payload["arguments"]}
    assert stances == {"for", "against"}


def test_synthesis_block_renders_argument_with_unresolved_anchor():
    # #2393: an argument whose inline anchor doesn't resolve to any skill's fired rule/card used to be
    # DROPPED by _route_synthesis_to_lenses (routed to Decision, then `continue`d) with nothing else
    # rendering it. The consolidated SYNTHESIS block now reads top_arguments_for/_against directly, so an
    # uncited/unresolved-anchor argument still appears there.
    nom = make_nomination()
    nom["llm_synthesis"]["top_arguments_for"] = ["No measured dependency signal in this lineage"]
    nom["llm_synthesis"]["top_arguments_against"] = []
    h = render_report(nom, preset="full", backend="html")
    assert "No measured dependency signal in this lineage" in h


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
    # v6 gate×modality .matrix: ordinal cells shaded by signal (g=supportive · b=killer/crit · h=mild).
    assert "td class='g'" in h  # supportive cell shaded
    assert "td class='b'" in h or "td class='h'" in h
    assert "Gate × modality matrix" in h  # the comp-bio power object
    assert "order-preserving ordinal" in h  # the inline ordinal legend retained


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
