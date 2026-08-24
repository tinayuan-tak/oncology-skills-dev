"""pair_selectivity_gate.derive_batch — AMORTIZED batch materialization of the bulk pair-selectivity
product (pure compute; no S3).

The interactive `read.scan_pair` re-scans the 790M-row GTEx long product once PER PAIR (~60-75s). This
module amortizes that: the CLI pulls ALL seed-antigen per-sample TPM in ONE scan per source, hands the
in-memory {source: {gene: {group: {sample_id: tpm}}}} cube here, and this computes EVERY
(indication × target × partner × gate) row in-memory via the existing gate physics (gates.reduce_gate).
Deterministic given the upstream product md5s.

Grain: one row per (indication, target, partner, gate) — DIRECTED (NOT is asymmetric; AND/OR symmetric
but stored directed for a uniform target-centric read). Partner universe is fixed (the clinical-seed
antigens) so the product is a bounded batch, not an unbounded query — arbitrary partner sets stay served
by the interactive scan skill.
"""
from __future__ import annotations

from typing import Optional

from .gates import _positive_fraction_by_group, reduce_gate, _GATES, classify_and_selectivity


def _tumor_studies_for(indication: str, indication_to_studies: dict) -> list:
    return list(indication_to_studies.get(indication, []) or [])


def derive_bulk_pair_selectivity(
    tumor_cube: dict,
    normal_cube: dict,
    indication: str,
    indication_to_studies: dict,
    targets: list,
    partners: list,
    gates: tuple = _GATES,
) -> list:
    """Compute all (target × partner × gate) selectivity rows for ONE indication, from in-memory cubes.

    tumor_cube / normal_cube: {gene_symbol: {group: {sample_id: linear_tpm}}}  (group = TCGA study /
      GTEx tissue). Built ONCE by the CLI from a single amortized scan per source.
    indication_to_studies: {indication: [tcga_study, ...]}.
    targets / partners: gene-symbol lists (the fixed clinical-seed universe for v1).

    Returns a list of row dicts (one per indication×target×partner×gate; target != partner; the pair's
    two arms must both be present in the cubes for that group, else the gate is skipped honestly)."""
    studies = _tumor_studies_for(indication, indication_to_studies)
    rows: list[dict] = []
    for target in targets:
        t_tumor = tumor_cube.get(target)
        t_normal = normal_cube.get(target)
        if t_tumor is None and t_normal is None:
            continue                                  # target not measured at all — nothing to emit
        for partner in partners:
            if partner == target:
                continue                              # no self-pairs
            p_tumor = tumor_cube.get(partner, {})
            p_normal = normal_cube.get(partner, {})
            for gate in gates:
                tumor_frac_by_study = _positive_fraction_by_group(t_tumor or {}, p_tumor, gate)
                normal_frac_by_tissue = _positive_fraction_by_group(t_normal or {}, p_normal, gate)
                for study in studies:
                    if study not in tumor_frac_by_study:
                        continue                      # this pair not co-measured in this tumor study
                    res = reduce_gate(gate, tumor_frac_by_study, normal_frac_by_tissue, study)
                    rows.append({
                        "indication": indication,
                        "target": target,
                        "partner": partner,
                        "gate": gate,
                        "tumor_study": res["tumor_study"],
                        "tumor_fraction": res["tumor_fraction"],
                        "max_essential_normal_fraction": res["max_essential_normal_fraction"],
                        "max_essential_normal_tissue": res["max_essential_normal_tissue"],
                        "max_any_normal_fraction": res["max_any_normal_fraction"],
                        "max_any_normal_tissue": res["max_any_normal_tissue"],
                        "selectivity": res["selectivity"],
                        "call": res["call"],
                    })
    return rows


def best_partner_rollup(rows: list, target: str, indication: str) -> dict:
    """Target-centric rollup for the reader/card: the best (most selective) partner per gate for this
    target in this indication. Dissolves the 'no target_pair grain' blocker — grain stays target_indication
    with the best partner carried inside (mirrors surface-colocalization-avidity's rollup)."""
    mine = [r for r in rows if r.get("target") == target and r.get("indication") == indication
            and r.get("selectivity") is not None]
    out = {"target": target, "indication": indication, "n_partners_scanned":
           len({r["partner"] for r in mine})}
    for gate in _GATES:
        g = [r for r in mine if r["gate"] == gate]
        if not g:
            continue
        top = max(g, key=lambda r: r["selectivity"])
        key = gate.lower()
        out[f"best_{key}_partner"] = top["partner"]
        out[f"best_{key}_selectivity"] = top["selectivity"]
        out[f"best_{key}_tumor_study"] = top["tumor_study"]
        out[f"best_{key}_max_essential_normal_tissue"] = top["max_essential_normal_tissue"]
        out[f"best_{key}_call"] = top["call"]
        if gate == "AND":
            # Rule-matchable categorical companion to the free-text best_and_call (2026-08-24 audit) —
            # lets surface-intrinsic rules fire the bispecific-necessity signal instead of it reaching
            # only the LLM narrative. Derived from the winning AND row's structured fractions.
            out["best_and_call_class"] = classify_and_selectivity(
                top["tumor_fraction"], top["max_essential_normal_fraction"],
                top["max_any_normal_fraction"], top["selectivity"])
    return out


__all__ = ["derive_bulk_pair_selectivity", "best_partner_rollup"]
