"""Per-sub-skill synthesis bullets — resolve exec_bullet cites.citation_ids against the evidence
graph's citation registry and render the PMID(s) inline as a cite-pill/anchor. Display-only /
verdict-inert; unresolved citation_ids + card_ids stay in the bracket anchor."""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render import ir as IR  # noqa: E402
from _skills_common.report_render.backends.html import HtmlBackend  # noqa: E402


def _narrative():
    return {
        "exec_bullets": [
            {
                "text": "KRAS is a lineage-selective dependency in CRC.",
                "polarity": "supportive",
                "cites": {"card_ids": ["c1"], "citation_ids": ["lit-1", "lit-x"]},
            }
        ]
    }


def _citations():
    # a citation registry (evidence_graph.citations); only lit-1 resolves + carries a PMID
    return [{"id": "lit-1", "pmid": "16404434", "label": "Went 2006", "verified": True}]


def test_skill_synthesis_block_resolves_citation_ids_to_pmids():
    blk = IR._skill_synthesis_block(_narrative(), _citations())
    b = blk.payload["exec_bullets"][0]
    rc = b["resolved_citations"]
    assert len(rc) == 1
    assert rc[0]["id"] == "lit-1" and rc[0]["pmid"] == "16404434" and rc[0]["verified"] is True


def test_skill_synthesis_block_without_registry_adds_no_resolved_citations():
    blk = IR._skill_synthesis_block(_narrative(), [])
    assert "resolved_citations" not in blk.payload["exec_bullets"][0]


def test_synthesis_bullets_renders_pmid_pill_and_keeps_unresolved_in_anchor():
    blk = IR._skill_synthesis_block(_narrative(), _citations())
    out = "".join(HtmlBackend()._synthesis_bullets(blk.payload))
    # the resolved citation renders as a PubMed-linked cite-pill
    assert "pubmed.ncbi.nlm.nih.gov/16404434" in out
    assert "PMID 16404434" in out
    assert "cite-pill" in out
    # the card_id + the UNRESOLVED citation_id remain in the bracket anchor (not dropped)
    assert "[c1, lit-x]" in out
