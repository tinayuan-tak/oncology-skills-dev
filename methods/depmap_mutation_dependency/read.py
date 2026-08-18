"""depmap_mutation_dependency.read — library entry for Card 3 live-mode reads.

Delegates to cli.load_depmap_files (via depmap_chronos_distribution reuse) +
cli.load_mutation_data + cli.compute_mutation_stratification. Matches the
canonical Card 1+2 pattern (read.py is a thin delegate over cli helpers; no
duplicate compute logic).

When the underlying data is unreachable, returns a dict with `_live_read_error`
AND `mutation_stratification_class: "data_unavailable"` (Tier-2 vocabulary
contract — descriptive label always present so the Tier-2 rule for
data_unavailable can fire).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from . import cli as _cli


from methods.target_id_sidecar import ensure_aws_profile


def read_mutation_stratified_dependency(
    target: str,
    indication: Optional[str] = None,
) -> dict:
    """Compute mutation-stratified dependency for target across the DepMap panel.

    `indication` drives the INDICATION-CONDITIONED ladder: when it maps to a
    DepMap lineage and the within-lineage mutant-vs-WT split clears the floor, the stratified test
    runs WITHIN that lineage (evidence_scope=within_indication) — so a lineage-context-dependent
    oncogene (BRAF: addicted in melanoma/thyroid, NOT in CRC) no longer reads a pan-cancer strong
    biomarker under a CRC label. Otherwise it falls back to pan-DepMap with a strong→moderate
    downgrade (evidence_scope=pan_lineage_evidence_only). See depmap_common.lineage_ladder.

    Returns dict matching Card 3's outputs.summary_fields (+ evidence_scope / lineage_* provenance),
    or a dict with _live_read_error key when data is unreachable.
    """
    ensure_aws_profile()

    # Reuse Card 1's loader for Chronos
    METHODS_REPO = Path(__file__).resolve().parent.parent.parent
    if str(METHODS_REPO) not in sys.path:
        sys.path.insert(0, str(METHODS_REPO))
    from methods.depmap_chronos_distribution import cli as c1cli

    chronos_by_model, model_metadata, chronos_errs = c1cli.load_depmap_files(
        release_pin="26q1", target_symbol=target
    )
    if chronos_errs:
        return {
            "_live_read_error": chronos_errs[0].get("_live_read_error", "s3_or_local_read_failed"),
            "errors": chronos_errs,
            "_remediation": "Method cannot reach DepMap 26Q1 Chronos; verify local cache or AWS credentials.",
            "mutation_stratification_class": "data_unavailable",
        }
    if not chronos_by_model:
        return {
            "_live_read_error": "no_chronos_for_target",
            "target": target,
            "mutation_stratification_class": "data_unavailable",
        }

    hotspot_by_model, damaging_by_model, mut_errs = _cli.load_mutation_data(
        release_pin="26q1", target_symbol=target
    )
    if mut_errs:
        return {
            "_live_read_error": mut_errs[0].get("_live_read_error", "mutation_read_failed"),
            "errors": mut_errs,
            "mutation_stratification_class": "data_unavailable",
        }

    # INDICATION-CONDITIONED ladder: compute within-lineage when powered, else pan-DepMap
    # (strong→moderate downgraded). The compute kernel is unchanged (pure, byte-stable); the ladder
    # only restricts the model dicts + attaches evidence_scope. `restrict=None` → pan-DepMap.
    from methods.depmap_common.lineage_ladder import apply_lineage_ladder

    def _compute(mut_models, wt_models):
        # Keep model m in whichever arm its mutation status places it: a MUTANT (hotspot or damaging)
        # must be in mut_models; a WT must be in wt_models (None = all lines for that arm). This lets
        # rung 2 pass mut_models=lineage, wt_models=None → lineage mutants vs pan WT.
        def _keep(m):
            is_mut = bool(hotspot_by_model.get(m) or damaging_by_model.get(m))
            arm = mut_models if is_mut else wt_models
            return arm is None or m in arm
        c = {m: v for m, v in chronos_by_model.items() if _keep(m)}
        h = {m: v for m, v in hotspot_by_model.items() if m in c}
        d = {m: v for m, v in damaging_by_model.items() if m in c}
        return _cli.compute_mutation_stratification(c, h, d)

    return apply_lineage_ladder(
        _compute, "mutation_stratification_class", model_metadata, indication)
