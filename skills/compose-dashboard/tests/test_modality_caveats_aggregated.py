"""T7 (2026-08-11 engineering review): modality_specific_caveats must reach the synthesis output.

_build_caveats_summary's docstring promised to "aggregate modality_specific_caveats from loaded
modules", but the loop body was a no-op `pass` — and compose_phase1._module_summary never carried
the field into the run_plan anyway. So a loaded ADC/BiTE/antibody module's caveats were silently
dropped. This test pins both halves of the fix: the field is carried into loaded_modality_modules,
and _build_caveats_summary emits each caveat (modality-prefixed, deduped).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR.parent))

from scripts._synthesis import _build_caveats_summary, _interpolate_tokens  # noqa: E402

CONTRACTS_ROOT = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT",
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))


def _run_plan_with_modules(modules):
    return {
        "input_context": {"target_symbol": "ERBB2", "indication": "BRCA"},
        "loaded_modality_modules": modules,
    }


def test_caveats_aggregated_and_prefixed():
    run_plan = _run_plan_with_modules([
        {"modality": "adc", "modality_specific_caveats": ["ADC density caveat", "shared caveat"]},
        {"modality": "bite_tce", "modality_specific_caveats": ["BiTE CRS caveat", "shared caveat"]},
    ])
    summary = _build_caveats_summary(run_plan, card_outputs=[], contracts_root=None)
    assert "[adc] ADC density caveat" in summary
    assert "[bite_tce] BiTE CRS caveat" in summary
    # dedup: the shared caveat appears once (from whichever module hit it first), not twice
    assert summary.count("shared caveat") == 1


def test_no_modules_no_modality_caveats():
    """Backward-compat: with no loaded modules, no modality caveat lines are added."""
    summary = _build_caveats_summary(_run_plan_with_modules([]), card_outputs=[], contracts_root=None)
    assert "[adc]" not in summary and "[bite_tce]" not in summary


def test_module_without_caveats_field_is_safe():
    """A module dict lacking modality_specific_caveats must not raise (defensive .get)."""
    summary = _build_caveats_summary(
        _run_plan_with_modules([{"modality": "small_molecule"}]),
        card_outputs=[], contracts_root=None,
    )
    assert isinstance(summary, str)


# ============================================================================
# C-fix (data-products emitter): caveats_summary must interpolate card warning-message tokens
# ============================================================================

def test_interpolate_tokens_fills_known_leaves_unknown():
    m = {"target.symbol": "MUC16", "shed_product": "soluble CA125", "serum_marker": "CA125"}
    out = _interpolate_tokens(
        "{target.symbol} sheds {shed_product} (marker {serum_marker}); {unknown_field} stays.", m)
    assert out == "MUC16 sheds soluble CA125 (marker CA125); {unknown_field} stays."
    # a None-valued token is left intact (a missing summary field must not blank the sentence)
    assert _interpolate_tokens("{shed_product}", {"shed_product": None}) == "{shed_product}"


def test_caveats_summary_interpolates_shed_warning_tokens():
    """A shed-ectodomain-liability warning message carries {target.symbol}/{shed_product}/
    {serum_marker}; _build_caveats_summary must render them from context + the card's summary,
    NOT leak the raw tokens (the data-products emitter bug)."""
    run_plan = {"input_context": {"target_symbol": "MUC16", "indication": "OV"},
                "loaded_modality_modules": []}
    card_outputs = [{
        "card_id": "shed-ectodomain-liability",
        "excluded_by_applies_when": False,
        "warning_ids": ["clinically_shed_antigen_sink"],
        "summary": {"shed_liability_class": "clinically_shed",
                    "shed_product": "soluble CA125 (shed MUC16 ectodomain)",
                    "serum_marker": "CA125"},
    }]
    summary = _build_caveats_summary(run_plan, card_outputs, contracts_root=CONTRACTS_ROOT)
    # rendered, not raw
    assert "MUC16 has a clinically-established shed ectodomain" in summary
    assert "soluble CA125 (shed MUC16 ectodomain)" in summary
    assert "serum marker CA125" in summary
    # no unrendered tokens leaked
    for tok in ("{target.symbol}", "{shed_product}", "{serum_marker}"):
        assert tok not in summary, f"unrendered token {tok} leaked into caveats_summary"
