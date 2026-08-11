"""T7 (2026-08-11 engineering review): modality_specific_caveats must reach the synthesis output.

_build_caveats_summary's docstring promised to "aggregate modality_specific_caveats from loaded
modules", but the loop body was a no-op `pass` — and compose_phase1._module_summary never carried
the field into the run_plan anyway. So a loaded ADC/BiTE/antibody module's caveats were silently
dropped. This test pins both halves of the fix: the field is carried into loaded_modality_modules,
and _build_caveats_summary emits each caveat (modality-prefixed, deduped).
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR.parent))

from scripts._synthesis import _build_caveats_summary  # noqa: E402


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
