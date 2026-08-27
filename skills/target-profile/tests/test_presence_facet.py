"""Test the presence cross-modal reconciliation facet plumbing in the composed target-profile:
  1. _load_sub_skill_facet_fn returns tumor-presence's _synthesis_facet, and None for a sub-skill
     that does not expose the hook (the loader is generic + opt-in);
  2. _presence_facet reads sub_results['expression']['synthesis_facet'] (and is None-safe);
  3. _build_user_prompt renders the deterministic reconciliation block when a presence_facet is
     supplied, and omits it otherwise — and the block is explicitly labelled a FACET, not a gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from tp_fanout import _load_sub_skill_facet_fn, _load_sub_skill_verdict_fn  # noqa: E402
from tp_facets import _presence_facet  # noqa: E402
from tp_synthesis_prompt import _build_user_prompt  # noqa: E402


def test_facet_loader_is_opt_in():
    # sub-skills that supply the hook: tumor-presence (cross-modal reconciliation) and, since P2
    # phase 3-claim, functional-requirement (the dependency claim-vector SIGNAL decomposition).
    assert callable(_load_sub_skill_facet_fn("tumor-presence"))
    assert callable(_load_sub_skill_facet_fn("functional-requirement"))
    # a sub-skill WITHOUT the hook returns None (loader never fabricates one). synthetic-lethal-partners
    # is the negative control — a composed sub-skill that exposes no _synthesis_facet (its relational
    # signal is claim-decomposed under the consolidated combination-and-vulnerability skill, not here).
    # (Was mechanism-and-pharmacology until it gained a _synthesis_facet in the claim-vector rollout.)
    _load_sub_skill_verdict_fn("synthetic-lethal-partners")  # warm the module cache
    assert _load_sub_skill_facet_fn("synthetic-lethal-partners") is None


def test_presence_facet_reads_synthesis_facet_from_sub_results():
    sub_results = {"expression": {"skill_dir": "tumor-presence",
                                  "synthesis_facet": {"presence_verdict": "tumor_broadly_expressed"}}}
    assert _presence_facet(sub_results) == {"presence_verdict": "tumor_broadly_expressed"}
    # None-safe when absent / no expression sub-skill
    assert _presence_facet({"expression": {}}) is None
    assert _presence_facet({}) is None


def _min_sub_results():
    # _build_user_prompt renders a "Card summaries" section that iterates r["cards"], so every
    # sub-result needs cards + fired (the real fan-out always provides them).
    return {"expression": {"skill_dir": "tumor-presence", "verdict": ("tumor_broadly_expressed", "r"),
                           "cards": [], "fired": []}}


def _facet():
    return {
        "presence_verdict": "tumor_broadly_expressed", "headline_lens": "bulk_rna/tumor",
        "cell_line_vs_tumor_discordant": True,
        "presence_interpretation_note": "understates tumor presence",
        "bulk_rna_proxy_quality": "rna_positive_proxy_partial", "bulk_rna_proxy_quality_source": "tumor",
        "rna_as_biomarker": "adequate_proxy", "rna_protein_r": 0.86,
        "rna_as_biomarker_tumor": "partial_proxy", "rna_protein_r_tumor": 0.41,
        "normal_tissue_ihc_breadth_class": "broad_normal_expression",
        "normal_tissue_ihc_essential_flag": True,
        "sc_normal_expression_class": "HIGH_LIABILITY",
        "sc_normal_max_det_cell_type": "BEST4+ colonocyte", "sc_normal_max_det_fraction": 1.0,
        "presence_verdict_by_modality": {
            "bulk_rna/tumor": {"verdict": "tumor_broadly_expressed", "evidence_state": "measured"},
            "sc_rna/normal": {"verdict": "HIGH_LIABILITY", "evidence_state": "comparator"},
        },
    }


def test_prompt_renders_the_reconciliation_block_when_facet_present():
    prompt = _build_user_prompt("CEACAM5", "COADREAD", _min_sub_results(), presence_facet=_facet())
    assert "Presence cross-modal reconciliation facet" in prompt
    assert "FACET, not a gate" in prompt
    # the per-modality matrix is rendered
    assert "bulk_rna/tumor" in prompt and "sc_rna/normal" in prompt
    # proxy quality (both arms) + normal-tissue window framing surfaced
    assert "proxy quality" in prompt and "partial_proxy" in prompt
    assert "WINDOW framing" in prompt and "HIGH_LIABILITY" in prompt
    # the discordance caveat is surfaced
    assert "DISCORDANT" in prompt


def test_prompt_omits_the_block_when_no_facet():
    prompt = _build_user_prompt("CEACAM5", "COADREAD", _min_sub_results(), presence_facet=None)
    assert "Presence cross-modal reconciliation facet" not in prompt


def test_prompt_renders_hierarchy_signal_decomposition_when_carried():
    # Stage 3: the composed prompt surfaces the hierarchy-derived sub-group + per-question signals that
    # the facet already carries (narrator-input contract) — read structurally off presence_facet, not
    # hand-picked. It is rendered in a SECTION register (no single-lens 'LEAD your narration' framing).
    facet = _facet()
    facet["subgroup_signals"] = {
        "abundance": {"signal": "strong", "confidence": "high", "n_sources": 2, "n_agree": 2,
                      "power": "high", "conflict": False,
                      "sources": [{"card": "tumor-rna-distribution", "tier": "strong", "n": 600,
                                   "label": "tumor RNA", "conflict": False, "value": "broadly_high"}]},
        "tumor_elevation": {"signal": "weak", "confidence": "low", "n_sources": 1, "n_agree": 0,
                            "power": "moderate", "conflict": True, "sources": []},
    }
    facet["question_table"] = [{"id": "Q3", "question": "Elevated vs normals?",
                                "signal": {"tier": "weak"}, "confidence": {"tier": "low"}}]
    prompt = _build_user_prompt("CEACAM5", "COADREAD", _min_sub_results(), presence_facet=facet)
    assert "Presence signal decomposition" in prompt
    assert "SUB-GROUP SIGNALS" in prompt
    assert "abundance: signal=strong confidence=high" in prompt
    assert "tumor_elevation: signal=weak confidence=low" in prompt
    assert "PER-QUESTION DECOMPOSITION" in prompt and "Q3 Elevated vs normals?" in prompt
    # section register — NOT the single-lens narrator's 'LEAD your narration' framing
    assert "LEAD your narration" not in prompt


def test_prompt_omits_signal_decomposition_when_facet_lacks_signals():
    # backward-compatible: a facet without subgroup_signals/question_table (older presence run) renders
    # the reconciliation block but no decomposition sub-block.
    prompt = _build_user_prompt("CEACAM5", "COADREAD", _min_sub_results(), presence_facet=_facet())
    assert "Presence cross-modal reconciliation facet" in prompt
    assert "Presence signal decomposition" not in prompt
