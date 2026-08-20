"""Stage 2a: the cross-evidence panel consumes `synthesis.claim_vectors` (+ citable evidence atoms)
from the target-profile evidence_package. assemble() surfaces them; _panel_block() renders the atom
VALUES so the reasoner sees more than the verdict label, each value citable by its card_id. Pure /
offline (no Bedrock)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent.parent))   # skills/ (for _skills_common)

import hypothesis_core as hc  # noqa: E402
import run as R  # noqa: E402

_ATOM = {
    "read": "strongly_selective",
    "values": {"bimodality_coefficient": 0.70, "fraction_strongly_dependent": 0.176},
    "cite": {"card_id": "pan-cancer-crispr-dependency-distribution",
             "fields": ["bimodality_coefficient", "fraction_strongly_dependent"]},
    "entity": {"measurement_type": "crispr_lof_dependency", "sample_context": "cell_line",
               "stratum": "pan_cancer"},
}


def _pkg(with_cv=True):
    syn = {
        "sub_verdicts": {"dependency": {"verdict": "selective_dependency",
                                        "fired_rule_ids": ["dep-01"]}},
        "recommendation_gate": {},
    }
    if with_cv:
        syn["claim_vectors"] = {"dependency": {
            "claim_vector": {"DEP": {"signal": "strong", "corroboration": "high",
                                     "evidence": "CRISPR strongly_selective", "conflict": None,
                                     "informs": "dep", "evidence_atom": _ATOM}},
            "key_signals": {"headline": "Strong genetic dependency."}}}
    return {"synthesis": syn,
            "cards": [{"card_id": "pan-cancer-crispr-dependency-distribution",
                       "interpretation_call": "informative"}],
            "context": {"target": "KRAS", "indication": "COADREAD"}}


def _assemble(tmp_path, with_cv=True):
    p = tmp_path / "ep.json"
    p.write_text(json.dumps(_pkg(with_cv)))
    return hc.assemble(str(p), None, None, "small_molecule")


def test_assemble_surfaces_claim_vectors(tmp_path):
    panel = _assemble(tmp_path)
    assert "dependency" in panel["claim_vectors"]
    atom = panel["claim_vectors"]["dependency"]["claim_vector"]["DEP"]["evidence_atom"]
    assert atom["values"]["bimodality_coefficient"] == 0.70
    # the atom's card_id is ALREADY a valid citation token (the card is in the package) — a clause
    # citing it stays traceable without widening the citation surface.
    assert "pan-cancer-crispr-dependency-distribution" in panel["citation_surface"]["card_ids"]


def test_panel_block_renders_atom_values(tmp_path):
    panel = _assemble(tmp_path)
    text, tgt, ind, _sub = R._panel_block(panel, "small-molecule drug target")
    assert "claim-vector signal decomposition" in text
    assert "bimodality_coefficient" in text                       # the numeric value reaches the prompt
    assert "pan-cancer-crispr-dependency-distribution" in text    # citable card_id present
    assert tgt == "KRAS" and ind == "COADREAD"


def test_panel_block_omits_section_when_no_claim_vectors(tmp_path):
    panel = _assemble(tmp_path, with_cv=False)
    text, *_ = R._panel_block(panel, "obj")
    # no empty section when absent → byte-stable prompt for un-migrated packages (e.g. the golden fixtures)
    assert "claim-vector signal decomposition" not in text
