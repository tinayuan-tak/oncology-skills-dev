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

from _skills_common.paths import TARGET_CONTRACTS_ROOT_DEFAULT  # noqa: E402

SKILL_NAME = "target-profile"
# 1.3.0: subtype_fit tier DEFAULT-ON — strata auto-resolved from the contracts subtype_crosswalk
#        (--no-subtypes opts out). 1.2.0: grounded-substrate chain DEFAULT-ON (--no-substrate opts out)
SKILL_VERSION = "1.3.0"


def _framework_model_version() -> str | None:
    """The DECLARED framework model pin (governance item B). Read from the single
    source-of-truth constant in the bedrock client. Graceful None on import failure —
    provenance simply omits it rather than crashing the run (conservative fallback)."""
    try:
        from _skills_common.bedrock_client import FRAMEWORK_MODEL_VERSION

        return FRAMEWORK_MODEL_VERSION
    except Exception:  # noqa: BLE001
        return None


_CONTRACTS_REPO = Path(os.environ.get("TARGET_CONTRACTS_ROOT", TARGET_CONTRACTS_ROOT_DEFAULT))


def default_subtypes(indication: str) -> "tuple[list[str], str]":
    """The molecular strata the subtype tier evaluates when --subtypes is not given.

    Returns (strata_ids, source) where source is a short machine token recorded in the
    artifact so a reader can always tell WHY the tier ran or did not:
      auto:subtype_crosswalk                — resolved from the contracts registry (normal path)
      auto:subtype_crosswalk:alias_of:<CODE> — the requested code is a curated ALIAS; <CODE>'s
                                strata answered, MINUS any `partition: co_defining` axis (below)
      unavailable:no_registry — the vocabulary could not be read
      unavailable:<CODE>      — the indication is not registered; run stays whole-cohort

    ALIASES (indication_crosswalk v1.4.0, via _skills_common.indication_scope): the registry is
    keyed by canonical_code, so `--indication LUAD` used to return ([], "unavailable:LUAD") and
    run whole-cohort even though the crosswalk has curated `NSCLC: aliases: [LUAD, LUSC]` all
    along. The alias now resolves, and the token names WHICH indication answered.

    ★ On an alias, axes declared `partition: co_defining` are DROPPED. Those strata co-define the
    canonical cohort (NSCLC `histology_Adeno`/`histology_SCC`), so under a LUAD request the axis
    degenerates to ONE stratum that IS the requested cohort — no cross-stratum contrast, yet
    tp_fanout._subtype_verdict reads a single stratum's own class and would happily let the
    VERDICT-BEARING subtype_restricted_dependency rung fire off what is really a whole-cohort read.
    Declaration-derived, so it is self-inerting for synonym aliases: only NSCLC and ESCA declare a
    co_defining axis and ESCA has no aliases. Expected: LUAD/LUSC → 16 strata, NSCLC → 18,
    COAD/READ → COADREAD's 21 (no co_defining axis, so nothing is dropped).

    WHY the CONTRACTS crosswalk and not the data-catalog subgroup catalog: the catalog is
    the source of truth for stratum IDS, but its list is raw — for COADREAD it carries
    `stage_I` / `stage_II` / `stage_resectable` (staging, not molecular biology) and the
    source-duplicated `CMS1_depmap`..`CMS4_depmap` alongside `CMS1`..`CMS4`. The tier's
    semantics are molecular ("a MEASURED, floor-cleared SUBTYPE that is not a dependency
    holds the nomination"), so it defaults to the curated, axis-organized registry, whose
    validator already asserts every id it lists exists in a catalog. Pass --subtypes
    explicitly to scope to anything else, including staging strata.

    Never raises: an unreadable or unlisted indication yields ([], reason) and the run
    proceeds whole-cohort exactly as it did before this became the default.
    """
    path = _CONTRACTS_REPO / "vocabularies" / "subtype_crosswalk.yaml"
    try:
        import yaml

        doc = yaml.safe_load(path.read_text()) or {}
    except Exception:  # noqa: BLE001 — a missing vocab degrades to whole-cohort, never a crash
        return [], "unavailable:no_registry"
    code = (indication or "").strip().upper()
    # Resolve aliases against the CURATED indication_crosswalk lane. `how == "unknown"` (including
    # an unreadable crosswalk) leaves `lookup` as the requested code, so the exact-match behaviour
    # below is byte-identical to the pre-alias implementation.
    try:
        from _skills_common.indication_scope import canonical_subtype_code

        canonical, how = canonical_subtype_code(code)
    except Exception:  # noqa: BLE001 — resolution is additive; never break the tier on it
        canonical, how = None, "unknown"
    lookup = (canonical or code).upper()
    for entry in doc.get("indications") or []:
        if str(entry.get("canonical_code", "")).upper() != lookup:
            continue
        axes = entry.get("axes") or []
        if how == "alias":
            # See the docstring: a co_defining axis degenerates to one whole-cohort stratum here.
            axes = [ax for ax in axes if str(ax.get("partition") or "") != "co_defining"]
        # dict.fromkeys: dedupe while holding the registry's axis order (stable run ids)
        strata = list(dict.fromkeys(s for axis in axes for s in (axis.get("strata") or [])))
        if not strata:
            return [], f"unavailable:{code}"
        return strata, (
            f"auto:subtype_crosswalk:alias_of:{entry.get('canonical_code')}"
            if how == "alias"
            else "auto:subtype_crosswalk"
        )
    return [], f"unavailable:{code or 'no_indication'}"


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
        ("median_log2tpm", "median log2TPM (tumor)"),
        ("median_log2tpm_panel", "median log2TPM (cell-line panel)"),
        ("fraction_expressed", "fraction expressed (cell-line panel)"),
        ("log2_fc", "log2FC tumor vs adj"),
        ("q_value", "q-value (tumor vs adj)"),
    ],
    "selectivity": [
        ("cells_supporting", "cells supporting"),
        ("cells_ran", "cells ran"),
        ("comparator_concordance", "comparator agreement"),  # TCGA-adjacent vs GTEx concur? (slice 4)
        ("dominant_direction", "dominant direction"),
        ("max_abs_log2fc", "max |log2FC|"),
        ("discordant", "discordant"),
    ],
    "dependency": [
        ("median_chronos_indication", "median CRISPR score"),
        ("pct_dependent_indication", "pct cell lines dependent"),
        ("lineage_selectivity_class", "lineage selectivity"),
        ("concordance_class", "CRISPR-RNAi concordance"),
    ],
    # Keys MUST match SUB_SKILLS shorts (run.py:65) or the per-phase evidence table
    # silently doesn't render (PHASE_METRIC_FIELDS.get(short, []) misses). Fixed
    # 2026-07-17: `mutation`→`genomic_alteration`, `tractability`→`tractability_sm`
    # (renamed in the 2026-07-14 restructure but this dict was missed — same
    # rename-drift class as the _risk_by_category fix); `population` DROPPED (skill
    # deleted, prevalence folded into genomic_alteration).
    "genomic_alteration": [
        ("mutation_landscape_class", "landscape class"),
        ("mutation_stratification_class", "stratification class"),
        ("copy_number_class", "copy-number class"),
        ("overall_mutation_frequency", "cohort mutation frequency (indication)"),
    ],
    "tractability_sm": [
        ("prism_activity_class", "PRISM activity class"),
        ("crispr_prism_concordance_class", "PRISM-CRISPR concordance"),
        ("predictability_class", "predictability"),
    ],
}


def _first_card_summary_field(sub_result: dict, field: str):
    """Search each card in the sub-result for a summary field; return the
    first non-None value found. Cards each expose different summary shapes,
    so a targeted search is more robust than positional assumption."""
    for c in sub_result.get("cards") or []:
        s = c.get("summary") or {}
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
    "PHASE_METRIC_FIELDS",
    "SKILLS_DIR",
    "SKILL_NAME",
    "SKILL_VERSION",
    "_CONTRACTS_REPO",
    "_first_card_summary_field",
    "_fmt_metric",
    "_framework_model_version",
    "default_subtypes",
]
