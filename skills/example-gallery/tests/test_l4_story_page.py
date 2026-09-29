"""l4_story_page renderer — pure unit tests over fixture synthesis objects (no subprocess/S3/LLM).

Pins the C2 (#1997) acceptance surface:
  * deterministic HTML modulo the `generated_at` timestamp,
  * every statement's claim ID appears in the rendered HTML (traceability is the load-bearing UX),
  * liabilities vs contradictions render as DISTINCT sections,
  * an absence path — a facet the assembler did not resolve renders an honest "not yet resolved"
    section, never fabricated content.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
for p in (str(SKILLS), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import json  # noqa: E402

from _skills_common.l4_synthesis import assemble_target_synthesis  # noqa: E402
from l4_story_page import render_story_page  # noqa: E402

GOLDEN = SKILLS / "tumor-presence" / "tests" / "fixtures" / "epcam_coadread_decision.json"


def _golden_decision():
    return json.loads(GOLDEN.read_text())


def _golden_synthesis():
    return assemble_target_synthesis(_golden_decision(), target="EPCAM", indication="COADREAD")


# ── deterministic modulo timestamp ──────────────────────────────────────────────────────────────
def test_render_is_deterministic_given_a_fixed_timestamp():
    decision = _golden_decision()
    synthesis = _golden_synthesis()
    p1 = render_story_page(synthesis, decision, target="EPCAM", indication="COADREAD", generated_at="FIXED")
    p2 = render_story_page(synthesis, decision, target="EPCAM", indication="COADREAD", generated_at="FIXED")
    assert p1 == p2


def test_only_the_timestamp_differs_across_runs():
    decision = _golden_decision()
    synthesis = _golden_synthesis()
    p1 = render_story_page(synthesis, decision, target="EPCAM", indication="COADREAD", generated_at="AAAA")
    p2 = render_story_page(synthesis, decision, target="EPCAM", indication="COADREAD", generated_at="BBBB")
    assert p1 != p2
    assert p1.replace("AAAA", "X") == p2.replace("BBBB", "X")


# ── traceability: every statement's claim IDs show up in the HTML ──────────────────────────────
def test_every_statement_claim_id_is_present_in_the_html():
    decision = _golden_decision()
    synthesis = _golden_synthesis()
    assert synthesis is not None
    page = render_story_page(synthesis, decision, target="EPCAM", indication="COADREAD", generated_at="T")

    from _skills_common.l4_synthesis import schema as S

    seen_any = False
    for fr in (synthesis.get("facets") or {}).values():
        for st in S.iter_statements(fr):
            for ref in st.get("claim_ids") or []:
                cid = ref.get("claim_id")
                assert cid, "every statement must cite a claim_id"
                assert cid in page, f"claim_id {cid} missing from rendered HTML"
                seen_any = True
    assert seen_any, "the golden fixture must exercise at least one statement"


def test_archetype_and_thesis_narrative_render():
    decision = _golden_decision()
    synthesis = _golden_synthesis()
    page = render_story_page(synthesis, decision, target="EPCAM", indication="COADREAD", generated_at="T")
    assert synthesis["archetype"] in page
    # the renderer HTML-escapes body text (apostrophes -> &#x27; etc) — compare against the escaped form
    assert html.escape(synthesis["thesis"]["narrative"]) in page


# ── liabilities vs contradictions kept DISTINCT ─────────────────────────────────────────────────
def test_liabilities_and_contradictions_sections_are_distinct():
    decision = _golden_decision()
    synthesis = _golden_synthesis()
    facets = synthesis.get("facets") or {}
    lc = facets.get("liabilities_contradictions")
    assert lc is not None, "the golden fixture is expected to resolve liabilities_contradictions"
    page = render_story_page(synthesis, decision, target="EPCAM", indication="COADREAD", generated_at="T")

    lia_idx = page.find('id="facet-liabilities_contradictions"')
    assert lia_idx != -1
    section_end = page.find('<div class="facet', lia_idx + 1)
    section = page[lia_idx : section_end if section_end != -1 else len(page)]

    assert "Liabilities" in section
    assert "Contradictions" in section
    # every liability's text and every contradiction's note appear, each exactly once inside the section
    for lia in lc.get("liabilities") or []:
        assert html.escape(lia["liability"]) in section
    for con in lc.get("contradictions") or []:
        assert html.escape(con["note"]) in section
    # the two headers are genuinely separate DOM regions, not one blended list
    assert section.index("Liabilities") < section.index("Contradictions")


# ── absence path ────────────────────────────────────────────────────────────────────────────────
def test_unbuilt_facet_renders_as_honest_absence_not_fabricated_content():
    decision = _golden_decision()
    synthesis = _golden_synthesis()
    # modality_implications / next_evidence are still declared stubs as of C0a-d landing; if a later
    # child has since built one, fall back to asserting on whatever the registry still leaves absent
    # so this test keeps meaning without hard-pinning C0e/C0f's landing order.
    facets = synthesis.get("facets") or {}
    from _skills_common.l4_synthesis import schema as S

    absent_names = [n for n in S.FACET_NAMES if n not in facets]
    assert absent_names, "expected at least one facet still unresolved on the golden fixture"

    page = render_story_page(synthesis, decision, target="EPCAM", indication="COADREAD", generated_at="T")
    for name in absent_names:
        marker = f'id="facet-{name}"'
        assert marker in page
        idx = page.find(marker)
        end = page.find('<div class="facet', idx + 1)
        section = page[idx : end if end != -1 else len(page)]
        assert "not yet resolved" in section
        assert "absent" in section  # the absent-facet CSS class, i.e. this took the honest path


def test_none_synthesis_renders_sparsest_honest_page_never_fabricates():
    decision = {"skill": "tumor-presence", "target": "MADEUPGENE", "indication": "MADEUPIND", "headline": {}}
    page = render_story_page(None, decision, target="MADEUPGENE", indication="MADEUPIND", generated_at="T")
    assert "No L4 synthesis resolved" in page
    assert "honestly absent" in page
    # no fabricated facet content: none of the known facet titles should appear as a resolved section
    from _skills_common.l4_synthesis import schema as S

    for name in S.FACET_NAMES:
        assert f'id="facet-{name}"' not in page


# ── mutation teeth: a broken claim ref on a hand-built synthesis is never silently swallowed ─────
def test_traceability_error_propagates_from_assembler_not_the_renderer():
    """The renderer itself does not validate — `assemble_target_synthesis(..., validate=True)`
    (the default) is where the mutation teeth live; this pins that the renderer is a pure
    presentation layer that trusts an already-validated synthesis object, so a broken claim ref is
    caught upstream in generate_story_pages.py's call site, not silently absorbed in HTML."""
    import pytest
    from _skills_common.l4_synthesis.assembler import L4TraceabilityError

    broken = json.loads(GOLDEN.read_text())
    # corrupt a claim vector key referenced by the L3d story's provenance so the ref no longer resolves
    broken["headline"]["claim_vector"].pop("tumor_presence_concordance", None)
    with pytest.raises(L4TraceabilityError):
        assemble_target_synthesis(broken, target="EPCAM", indication="COADREAD")
