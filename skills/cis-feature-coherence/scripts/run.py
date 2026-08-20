#!/usr/bin/env python3
"""cis-feature-coherence — does target X's OWN locus feature explain its OWN expression AND dependency?

Focused question skill: the coherence OWNER for the locus → expression → dependency chain.
Distinguishes amplification-driven oncogene addiction (ERBB2/MYC/KRAS-amp) from a co-occurring
passenger, an expressed-but-inert target, and a trans-driven dependency.

Integrates ONE new leg (cis-feature-expression-coherence: CN → own-expression cis-dosage) with TWO
reused leg-cards (expression-dependency-correlation + amp-expr-stratified-dependency) — no new
dependency measurement. Verdict via the SHARED declarative resolver on a DEDICATED axis:
resolve_or_raise(fired, "cis_coherence") → cis_coherence.resolver.yaml (a deterministic 2×2 cross-tab).

VERDICT-INERT at composition: cis_coherence is a dedicated self-contained axis, NOT a nomination gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import card_summary
from _skills_common.dispatcher import run_wired_skill
from _skills_common.resolver import resolve_or_raise


SKILL_NAME = "cis-feature-coherence"
SKILL_VERSION = "1.0.0"

CARDS = [
    "cis-feature-expression-coherence",     # GoF leg-1: CN → own-expression cis-dosage (amplification)
    "cellline-methylation-expression-coherence",  # LoF leg-1: promoter methylation → own LOW expression (silencing)
    "expression-dependency-correlation",     # leg-2 (reuse): expression → dependency
    "amp-expr-stratified-dependency",         # leg-2 (reuse): conjoint amp∩overexpr dependency
    "patient-cis-coherence",                  # VERDICT-INERT patient (TCGA) corroboration facet — fires NO
                                              # cis_coherence rule (verdict byte-stable); surfaced in the headline
                                              # as cross-grain agreement (does the cell-line call replicate in patients?)
    # ── MOLECULAR-FORM facets (2) — VERDICT-INERT display (R10 homing 2026-08-20) ──────────────
    # WHICH transcript of the target is expressed — molecular-FORM context for the cis read (a specific
    # dominant isoform can change which transcript the CN→expression coupling acts on). Cell-line grain
    # (DepMap), matching this skill. Fire NO cis_coherence rule → verdict byte-stable. Previously orphaned
    # (created by #424, consumed by no skill); homed here rather than presence (no molecular-form bucket in
    # its measurement×sample_context taxonomy) or target-intrinsic (excludes cell-line observations).
    "cellline-isoform-dominance",
    "cellline-isoform-expression",
]

QUESTION = ("Does {target}'s own locus feature (copy-number) explain its own expression AND its own "
            "dependency in {indication} — a coherent cis-driven addiction, or co-occurring axes?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """cis_coherence_verdict from the SHARED declarative resolver (cis_coherence.resolver.yaml).

    resolve_or_raise reads resolvers/cis_coherence.resolver.yaml (target-contracts) and evaluates the
    ordered 2×2 cross-tab against the fired cis-coherence rule set. Single source of truth — the ladder
    lives in the YAML (validated + golden-tested there), not re-encoded here."""
    return resolve_or_raise(fired, "cis_coherence")


def _headline(cards, fired, verdict_pair):
    def _s(cid):
        return card_summary(cards, cid)
    cis = _s("cis-feature-expression-coherence")   # GoF leg-1
    meth = _s("cellline-methylation-expression-coherence")  # LoF leg-1
    corr = _s("expression-dependency-correlation")  # leg-2 (correlation)
    ampx = _s("amp-expr-stratified-dependency")     # leg-2 (conjoint)
    pat = _s("patient-cis-coherence")               # VERDICT-INERT patient (TCGA) corroboration

    # Cross-grain agreement (verdict-inert confidence signal): does the patient tumour arm replicate the
    # cell-line call? Directional only (thresholds differ across grains) — None when either grain is unmeasured.
    _cl_coupled = (cis.get("cis_dosage_class") or "").startswith("cn_dosage_coupled")
    _pt_coupled = (pat.get("patient_cis_dosage_class") or "").startswith("cn_dosage_coupled")
    _cl_silenced = (meth.get("methylation_silencing_class") or "").startswith("silencing_coupled")
    _pt_silenced = pat.get("patient_methylation_silencing_class") == "epigenetic_silencing"
    _pt_measured = bool(pat.get("patient_cis_dosage_class")) and pat.get("patient_cis_dosage_class") != "data_unavailable"
    dosage_agreement = (_cl_coupled == _pt_coupled) if (_pt_measured and cis.get("cis_dosage_class")) else None
    silencing_agreement = (
        (_cl_silenced == _pt_silenced)
        if (pat.get("patient_methylation_silencing_class") not in (None, "insufficient_methylation_data")
            and meth.get("methylation_silencing_class") not in (None, "data_unavailable"))
        else None)

    verdict, driving = verdict_pair
    return {
        "cis_coherence_verdict": verdict,
        "driving_rule_id": driving,
        # LoF leg-1: promoter methylation → own LOW expression (epigenetic silencing)
        "methylation_silencing_class": meth.get("methylation_silencing_class"),
        "methylation_silencing_driver": meth.get("silencing_driver"),
        "methylation_subset_median_delta_log2tpm": meth.get("subset_median_delta_log2tpm"),
        "n_hypermethylated": meth.get("n_hypermethylated"),
        # GoF leg-1: feature → own-expression (the new measurement)
        "cis_dosage_class": cis.get("cis_dosage_class"),
        "cn_expr_spearman_r": cis.get("cn_expr_spearman_r"),
        "cn_expr_spearman_p": cis.get("cn_expr_spearman_p"),
        "cn_expr_slope_log2tpm_per_cn": cis.get("cn_expr_slope_log2tpm_per_cn"),
        "relative_cn_iqr": cis.get("relative_cn_iqr"),
        "delta_log2tpm_amplified_vs_neutral": cis.get("delta_log2tpm_amplified_vs_neutral"),
        "n_amplified": cis.get("n_amplified"),
        "cis_dosage_evidence_scope": cis.get("evidence_scope"),
        # leg-2: expression/feature → own-dependency (reused)
        "expression_dependency_correlation_class": corr.get("correlation_class"),
        "expression_dependency_pearson_r": corr.get("pearson_r"),
        "amp_expr_stratification_class": ampx.get("amp_expr_stratification_class"),
        "amp_expr_delta_chronos": ampx.get("delta_chronos_amp_expr_vs_rest"),
        # PATIENT (TCGA) cross-grain corroboration — VERDICT-INERT confidence signal
        "patient_cis_dosage_class": pat.get("patient_cis_dosage_class"),
        "patient_methylation_silencing_class": pat.get("patient_methylation_silencing_class"),
        "patient_n_cases_expression": pat.get("n_cases_expression"),
        "patient_dosage_agrees_with_cellline": dosage_agreement,
        "patient_silencing_agrees_with_cellline": silencing_agreement,
        # coherence framing
        "n_cell_lines_evaluated": cis.get("n_cell_lines_evaluated"),
    }


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="cis_coherence",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
    ))
