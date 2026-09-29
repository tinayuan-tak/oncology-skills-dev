"""control_position — anchor a target's all-gene percentile against curated controls.

Given a (target, indication), fetch the Phase-1 all-gene percentile for the target AND
for each APPLICABLE control gene (positives + negatives), then report where the target
sits relative to the anchors — on the same percentile scale, in the same cohort.

Two entry points, one per RNA card / percentile source:
  control_position_tumor(target, indication)   → allgene-tumor-rank-v1 (per-study tumor median)
  control_position_cellline(target)            → allgene-depmap-rank-26q3-v1 (pan-cancer panel)

INDICATION-MATCHING (the load-bearing rule): a `lineage_marker` negative is only a
negative AWAY from its own lineage. We resolve the indication's gtex_normal_tissue via
indication_crosswalk.yaml and EXCLUDE (flag lineage_conflict) any negative whose
`negative_except_lineage` matches it. housekeeping/silent negatives + all positives are
`applies: universal`.

data_unavailable-safe: vocab/crosswalk load failure or absent percentiles → a
control_position_class of data_unavailable, never a raise into the render path.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from methods.roots import contracts_root

METHOD_VERSION = "0.1.0"
# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
DEFAULT_TARGET_CONTRACTS = Path(contracts_root())
CONTROLS_VOCAB_RELPATH = "vocabularies/tumor_presence_controls.yaml"
CROSSWALK_RELPATH = "vocabularies/indication_crosswalk.yaml"


@lru_cache(maxsize=4)
def _load_controls(contracts_dir: str) -> dict:
    path = Path(contracts_dir) / CONTROLS_VOCAB_RELPATH
    return yaml.safe_load(path.read_text())


@lru_cache(maxsize=4)
def _load_crosswalk(contracts_dir: str) -> dict:
    """indication canonical_code (upper) -> gtex_normal_tissue (or None)."""
    path = Path(contracts_dir) / CROSSWALK_RELPATH
    data = yaml.safe_load(path.read_text())
    out = {}
    for ind in data.get("indications", []):
        code = str(ind.get("canonical_code", "")).upper().strip()
        if code:
            out[code] = ind.get("gtex_normal_tissue")
    return out


# Reader indication codes -> crosswalk canonical_code. The tumor reader keys studies on
# histology codes (LUAD/LUSC/PDAC/COAD/READ) while indication_crosswalk.yaml keys tissue on
# the broader canonical code (NSCLC/PAAD/COADREAD). Bridge them here so a lung query resolves
# its normal tissue (Lung) regardless of which code the caller used — WITHOUT editing the
# shared crosswalk (collision-prone; the readers' full migration to the crosswalk is a separate
# workstream). Mirrors INDICATION_TO_TUMOR_ASSIGNMENT_MANIFEST's LUAD/LUSC->nsclc aliasing.
_INDICATION_CANONICAL_ALIAS = {
    "LUAD": "NSCLC",
    "LUSC": "NSCLC",
    "PDAC": "PAAD",
    "COAD": "COADREAD",
    "READ": "COADREAD",
}


def _indication_normal_tissue(indication: str, contracts_dir: str) -> Optional[str]:
    """The indication's GTEx normal tissue-of-origin (the lineage a lineage-marker
    negative would CONFLICT with). Tries the code directly, then its canonical alias.
    None when neither is in the crosswalk (then no lineage negative is excluded — honest)."""
    xw = _load_crosswalk(contracts_dir)
    code = (indication or "").upper().strip()
    if code in xw and xw[code] is not None:
        return xw[code]
    alias = _INDICATION_CANONICAL_ALIAS.get(code)
    return xw.get(alias) if alias else None


def _applicable_negatives(controls: dict, indication_tissue: Optional[str]) -> tuple:
    """Split the negative controls into (applicable, excluded-for-lineage-conflict).

    A lineage_marker negative whose `negative_except_lineage` matches the indication's
    gtex_normal_tissue is EXCLUDED (it is the lineage marker there, not a negative).
    housekeeping/silent negatives (applies: universal) are always applicable."""
    applicable, excluded = {}, {}
    for sym, spec in (controls.get("negative_controls") or {}).items():
        role = spec.get("role")
        if role == "lineage_marker":
            lineage = spec.get("negative_except_lineage")
            if (
                indication_tissue is not None
                and lineage is not None
                and str(lineage).strip().lower() == str(indication_tissue).strip().lower()
            ):
                excluded[sym] = spec  # lineage_conflict — this gene is a MARKER here
                continue
        applicable[sym] = spec
    return applicable, excluded


def _classify_control_position(target_pct, pos_pcts: dict, neg_pcts: dict) -> str:
    """Where does the target sit relative to the control anchors?
      above_all_positives  — target >= max(applicable positives): a top-tier abundance read
      within_positives      — target is among the positives (>= at least one, below the max)
      above_negatives_below_positives — clears every negative but below all positives
      below_negatives       — target < the highest FLOOR negative (below even a silent/lineage floor):
                              genuinely low abundance
      data_unavailable       — target or all controls unrankable
    Housekeeping negatives are CEILING refs; the 'below_negatives' floor uses the
    NON-housekeeping negatives (silent/lineage) so a target below housekeeping (normal for
    most antigens) is not mislabeled low. (Housekeeping still reported for context.)"""
    if target_pct is None:
        return "data_unavailable"
    pv = [p for p in pos_pcts.values() if p is not None]
    # floor = non-housekeeping negatives (silent/lineage); ceiling = housekeeping (context only)
    floor = [v["pct"] for v in neg_pcts.values() if v["pct"] is not None and v["role"] != "housekeeping"]
    if not pv and not floor:
        return "data_unavailable"
    if floor and target_pct < max(floor):
        return "below_negatives"
    if pv and target_pct >= max(pv):
        return "above_all_positives"
    if pv and target_pct >= min(pv):
        return "within_positives"
    return "above_negatives_below_positives"


def _assemble(target_pct, target_class, pos_pcts, neg_detail, excluded, source_label, context) -> dict:
    """Build the control_position summary block (shared by both entry points)."""
    n_pos = sum(1 for p in pos_pcts.values() if p is not None)
    n_pos_below = sum(1 for p in pos_pcts.values() if p is not None and target_pct is not None and target_pct >= p)
    neg_pcts = {k: v["pct"] for k, v in neg_detail.items()}
    n_neg = sum(1 for p in neg_pcts.values() if p is not None)
    n_neg_below = sum(1 for p in neg_pcts.values() if p is not None and target_pct is not None and target_pct >= p)
    klass = _classify_control_position(target_pct, pos_pcts, neg_detail)
    # human-readable position summary
    parts = []
    if n_pos:
        parts.append(f"above {n_pos_below}/{n_pos} positive control(s)")
    if n_neg:
        parts.append(f"above {n_neg_below}/{n_neg} negative control(s)")
    position = "; ".join(parts) if parts else "no applicable controls ranked"
    # NOTE: target_class is accepted for call-site symmetry with target_pct but is no longer
    # echoed here — control_target_percentile/_class were removed (#862): they unconditionally
    # byte-duplicated allgene_percentile/_class from the same lookup (see control_position_tumor
    # / control_position_cellline below), with no distinct control-target measurement behind
    # them. Undeclared in the target-contracts card (cellline-rna-distribution.card.yaml lists
    # them as reverted runtime orphans) — AM-only, no pin bump.
    del target_class
    return {
        "control_position_class": klass,
        "control_position": position,
        "control_positives": {k: round(v, 2) for k, v in pos_pcts.items() if v is not None},
        "control_negatives": {k: round(v["pct"], 2) for k, v in neg_detail.items() if v["pct"] is not None},
        "control_negatives_excluded_lineage_conflict": sorted(excluded.keys()),
        "control_position_context": context,
        "control_percentile_source": source_label,
        "control_position_method_version": METHOD_VERSION,
    }


def control_position_tumor(target: str, indication: str, contracts_dir: str = str(DEFAULT_TARGET_CONTRACTS)) -> dict:
    """Control-benchmark position for the tumor-rna-distribution card (per-study tumor
    median rank, allgene-tumor-rank-v1). Indication-matched negatives."""
    from methods.allgene_percentile_precompute.lookup import tumor_allgene_percentile
    from methods.tcga_gtex_expression_distribution.read import INDICATION_TO_TCGA_STUDIES, _symbol_to_ensembl_ids

    try:
        controls = _load_controls(contracts_dir)
    except Exception as e:  # noqa: BLE001  # absence-discipline: exempt -- verdict-inert control-benchmark display facet; the guarded read is the target-contracts controls VOCAB (_load_controls), whose deliberate contract is to degrade when the vocab is not yet merged in the sibling checkout (cross-repo staleness tolerance), not an S3 data product -- observability preserved via _control_note
        return {
            "control_position_class": "data_unavailable",
            "_control_note": f"controls vocab unavailable: {type(e).__name__}",
            "control_position_method_version": METHOD_VERSION,
        }

    studies = INDICATION_TO_TCGA_STUDIES.get((indication or "").upper().strip(), [])
    tissue = _indication_normal_tissue(indication, contracts_dir)

    def _pct(sym):
        ids = _symbol_to_ensembl_ids(sym) or []
        return tumor_allgene_percentile(ids, studies).get("allgene_percentile")

    target_res = tumor_allgene_percentile(_symbol_to_ensembl_ids(target) or [], studies)
    target_pct = target_res.get("allgene_percentile")
    target_class = target_res.get("allgene_percentile_class")

    pos_pcts = {sym: _pct(sym) for sym in (controls.get("positive_controls") or {})}
    applicable_neg, excluded = _applicable_negatives(controls, tissue)
    neg_detail = {sym: {"pct": _pct(sym), "role": spec.get("role")} for sym, spec in applicable_neg.items()}

    ctx = (
        f"tumor:{','.join(studies) or '?'} vs curated controls "
        f"(tumor_presence_controls v{controls.get('version')}; "
        f"indication_normal_tissue={tissue}; allgene-tumor-rank-v1)"
    )
    return _assemble(target_pct, target_class, pos_pcts, neg_detail, excluded, "allgene-tumor-rank-v1", ctx)


def control_position_cellline(target: str, contracts_dir: str = str(DEFAULT_TARGET_CONTRACTS)) -> dict:
    """Control-benchmark position for the cellline-rna-distribution card (DepMap
    pan-cancer panel-median rank, allgene-depmap-rank-26q3-v1). The DepMap null is a
    single pan-cancer panel (no indication), so lineage-marker negatives stay applicable
    (there is no single indication tissue to conflict with) — they anchor the FLOOR."""
    from methods.allgene_percentile_precompute.lookup import depmap_allgene_percentile

    try:
        controls = _load_controls(contracts_dir)
    except Exception as e:  # noqa: BLE001  # absence-discipline: exempt -- verdict-inert control-benchmark display facet; the guarded read is the target-contracts controls VOCAB (_load_controls), whose deliberate contract is to degrade when the vocab is not yet merged in the sibling checkout (cross-repo staleness tolerance), not an S3 data product -- observability preserved via _control_note
        return {
            "control_position_class": "data_unavailable",
            "_control_note": f"controls vocab unavailable: {type(e).__name__}",
            "control_position_method_version": METHOD_VERSION,
        }

    def _pct(sym):
        return depmap_allgene_percentile(sym).get("allgene_percentile")

    target_res = depmap_allgene_percentile(target)
    target_pct = target_res.get("allgene_percentile")
    target_class = target_res.get("allgene_percentile_class")

    pos_pcts = {sym: _pct(sym) for sym in (controls.get("positive_controls") or {})}
    # pan-cancer panel: no indication tissue → no lineage_conflict exclusion (tissue=None).
    applicable_neg, excluded = _applicable_negatives(controls, None)
    neg_detail = {sym: {"pct": _pct(sym), "role": spec.get("role")} for sym, spec in applicable_neg.items()}

    ctx = (
        f"DepMap pan-cancer panel vs curated controls "
        f"(tumor_presence_controls v{controls.get('version')}; allgene-depmap-rank-26q3-v1)"
    )
    return _assemble(target_pct, target_class, pos_pcts, neg_detail, excluded, "allgene-depmap-rank-26q3-v1", ctx)
