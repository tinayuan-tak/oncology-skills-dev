"""target-profile — shared foundation: skills-root bootstrap, skill identity constants,
the contracts-repo anchor, the framework-model pin, and tiny cross-cutting formatters."""
from __future__ import annotations

import os
import sys
from pathlib import Path


SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
for _p in (str(Path(__file__).resolve().parent), str(SKILLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)



SKILL_NAME = "target-profile"
SKILL_VERSION = "1.2.0"   # 1.2.0: grounded-substrate chain (ground→risk→hypothesis) DEFAULT-ON (--no-substrate opts out)


def _framework_model_version() -> str | None:
    """The DECLARED framework model pin (governance item B). Read from the single
    source-of-truth constant in the bedrock client. Graceful None on import failure —
    provenance simply omits it rather than crashing the run (conservative fallback)."""
    try:
        from _skills_common.bedrock_client import FRAMEWORK_MODEL_VERSION
        return FRAMEWORK_MODEL_VERSION
    except Exception:  # noqa: BLE001
        return None

_CONTRACTS_REPO = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)


# --- Rendering --------------------------------------------------------------

# --- Per-phase evidence rows -----------------------------------------------
# For each sub-skill's "short" key, name the 2-4 key metric fields to inline
# in the per-phase evidence table. Field names must match those actually
# exposed by each sub-skill's underlying card summaries (audited empirically).
PHASE_METRIC_FIELDS: dict[str, list[tuple[str, str]]] = {
    "expression": [
        # INV-3: name the sample_context of every number. `median_log2tpm` is the TUMOR-tissue median
        # (tumor-rna-distribution); `median_log2tpm_panel` is the DepMap CELL-LINE panel median
        # (cellline-rna-distribution) — the previous "(pan-cancer)" label conflated the two and surfaced
        # the cell-line value as if it were tumor prevalence. Lead with the tumor lens.
        ("median_log2tpm",          "median log2TPM (tumor)"),
        ("median_log2tpm_panel",    "median log2TPM (cell-line panel)"),
        ("fraction_expressed",       "fraction expressed (cell-line panel)"),
        ("log2_fc",                  "log2FC tumor vs adj"),
        ("q_value",                  "q-value (tumor vs adj)"),
    ],
    "selectivity": [
        ("cells_supporting",         "cells supporting"),
        ("cells_ran",                "cells ran"),
        ("comparator_concordance",   "comparator agreement"),   # TCGA-adjacent vs GTEx concur? (slice 4)
        ("dominant_direction",       "dominant direction"),
        ("max_abs_log2fc",           "max |log2FC|"),
        ("discordant",               "discordant"),
    ],
    "dependency": [
        ("median_chronos_indication", "median CRISPR score"),
        ("pct_dependent_indication",  "pct cell lines dependent"),
        ("lineage_selectivity_class", "lineage selectivity"),
        ("concordance_class",         "CRISPR-RNAi concordance"),
    ],
    # Keys MUST match SUB_SKILLS shorts (run.py:65) or the per-phase evidence table
    # silently doesn't render (PHASE_METRIC_FIELDS.get(short, []) misses). Fixed
    # 2026-07-17: `mutation`→`genomic_alteration`, `tractability`→`tractability_sm`
    # (renamed in the 2026-07-14 restructure but this dict was missed — same
    # rename-drift class as the _risk_by_category fix); `population` DROPPED (skill
    # deleted, prevalence folded into genomic_alteration).
    "genomic_alteration": [
        ("mutation_landscape_class",      "landscape class"),
        ("mutation_stratification_class", "stratification class"),
        ("copy_number_class",             "copy-number class"),
        ("overall_mutation_frequency",    "cohort mutation frequency (indication)"),
    ],
    "tractability_sm": [
        ("prism_activity_class",            "PRISM activity class"),
        ("crispr_prism_concordance_class",  "PRISM-CRISPR concordance"),
        ("predictability_class",            "predictability"),
    ],
}


def _first_card_summary_field(sub_result: dict, field: str):
    """Search each card in the sub-result for a summary field; return the
    first non-None value found. Cards each expose different summary shapes,
    so a targeted search is more robust than positional assumption."""
    for c in sub_result.get("cards") or []:
        s = (c.get("summary") or {})
        if field in s and s[field] is not None:
            return s[field]
    return None


def _fmt_metric(value):
    """Human-render a metric value for the markdown table."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if abs(value) < 1e-3 or abs(value) >= 1e6:
            return f"{value:.3g}"
        return f"{value:.3f}"
    if isinstance(value, int):
        return str(value)
    s = str(value)
    return s if len(s) <= 60 else s[:57] + "..."


__all__ = [
    'PHASE_METRIC_FIELDS',
    'SKILLS_DIR',
    'SKILL_NAME',
    'SKILL_VERSION',
    '_CONTRACTS_REPO',
    '_first_card_summary_field',
    '_fmt_metric',
    '_framework_model_version',
]
