"""Gap #4b: synthesis prompt reads the matrix-SLICE, not only the flat verdict list.

Pins that _build_user_prompt embeds the modality-scoped ordinal matrix with the honesty framing
(reprojection-not-new-evidence, order-preserving-not-calibrated, don't-sum, cell-can-differ-from-
verdict), and that the system prompt instructs the LLM accordingly — so the reshape can't silently
turn the ordinals into scores. Bedrock-free (renders the prompt string only).
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run")


def _fired(*sm):
    return [{"rule_id": f"r{i}", "card_id": "c", "field": "f", "value": "v", "signals": s}
            for i, s in enumerate(sm)]


def _sub_results():
    return {
        "dependency": {"skill_dir": "functional-requirement",
                       "cards": [{"card_id": "crispr", "summary": {"x": 1}}],
                       "verdict": ("lineage_selective", "lineage-selective-supportive"),
                       "fired": _fired({"small_molecule": "opposing", "degrader": "supportive"})},
        "surface_modality": {"skill_dir": "surface-modality-fit",
                             "cards": [{"card_id": "s", "summary": {}}],
                             "verdict": ("neither_viable", "x"),
                             "fired": _fired({"adc": "killer", "bite_tce": "killer"})},
    }


def test_prompt_includes_matrix_slice_when_provided():
    sr = _sub_results()
    mx = tp._ordinal_matrix(sr)
    prompt = tp._build_user_prompt("KRAS", "COADREAD", sr, ordinal_matrix=mx)
    assert "### Modality-scoped evidence matrix" in prompt
    assert "| gate | small_molecule | degrader | adc | bite_tce | antibody |" in prompt
    # the degrader-preferred split is visible in the row (SM opposing -1, degrader supportive +2)
    assert "| dependency | -1 | +2 |" in prompt


def test_prompt_matrix_carries_honesty_framing():
    sr = _sub_results()
    prompt = tp._build_user_prompt("KRAS", "COADREAD", sr, ordinal_matrix=tp._ordinal_matrix(sr))
    seg = prompt[prompt.find("### Modality-scoped"):prompt.find("### Card summaries")]
    assert "NOT new evidence" in seg
    assert "NOT calibrated" in seg
    assert "Do NOT sum or average" in seg
    assert "verdict is the decision" in seg
    assert "off-scale (coverage, not a low score)" in seg


def test_prompt_backward_compatible_without_matrix():
    """Omitting ordinal_matrix (the pre-#4b call shape) must still produce a valid prompt with
    NO matrix section — purely additive."""
    sr = _sub_results()
    prompt = tp._build_user_prompt("KRAS", "COADREAD", sr)  # no ordinal_matrix
    assert "### Modality-scoped evidence matrix" not in prompt
    assert "### Sub-verdicts" in prompt and "### Card summaries" in prompt


def test_system_prompt_instructs_matrix_use_with_guardrails():
    assert "modality-scoped evidence matrix" in tp._SYSTEM_PROMPT
    assert "never sum or average" in tp._SYSTEM_PROMPT
    assert "VERDICT is the decision" in tp._SYSTEM_PROMPT
    assert "NOT new" in tp._SYSTEM_PROMPT and "NOT a score" in tp._SYSTEM_PROMPT
