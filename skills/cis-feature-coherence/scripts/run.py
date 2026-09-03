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
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import CIS_FEATURE_COHERENCE as _LENS
from _skills_common.resolver import resolve_or_raise
from _skills_common.claim_record import assemble_claim_record
from _skills_common.cis_coherence_claims import cis_coherence_claim_vector, cis_coherence_key_signals
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.skill_report import build_skill_report, ROLE_INERT
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.subgroup_derivation import make_value_classifier

# Signals-first sub-group reader (VERDICT-INERT). Thesis: cis locus→expression→dependency coherence.
# default_classify is the fallback for unmapped values.
_CIS_VALUE_TIERS = {
    "cn_dosage_coupled_strong": "strong", "cn_dosage_coupled_moderate": "moderate",
    "cn_dosage_uncoupled": "absent",
    "amplified_overexpressed_strongly_dependent": "strong",
    "amplified_overexpressed_moderately_dependent": "moderate",
    # real cellline-methylation-expression-coherence vocab (methylation_silencing_class ∈
    # {silencing_coupled_strong, silencing_coupled_moderate, methylation_uncoupled,
    # methylation_invariant_panel, data_unavailable}); the prior methylation_silenced/
    # methylation_variable keys never existed, so methylation subgroup rows fell through to default.
    "silencing_coupled_strong": "strong", "silencing_coupled_moderate": "moderate",
    "methylation_uncoupled": "absent",
    "methylation_invariant_panel": "absent",
    "strong_negative": "strong", "moderate_negative": "moderate", "weak_negative": "weak",
    "no_correlation": "absent",
}


SKILL_NAME = "cis-feature-coherence"
SKILL_VERSION = "1.3.0"   # 1.3.0 (2026-08-28): PROTEIN legs (cis-feature-protein-coherence CN→protein + abundance-dependency protein→dep) + mRNA-vs-protein dosage slope ratio. VERDICT-INERT.   # 1.2.0 (2026-08-28): capsule-driven narrator via generic engine.

CARDS = [
    "cis-feature-expression-coherence",     # GoF leg-1: CN → own-expression cis-dosage (amplification, mRNA)
    "cis-feature-protein-coherence",         # GoF leg-1 (PROTEIN): CN → own-PROTEIN cis-dosage. The slope
                                              # RATIO vs the mRNA leg separates dosage-SENSITIVE cis-drivers
                                              # (ERBB2/MYC/MDM2) from dosage-BUFFERED passengers. VERDICT-INERT
                                              # (fires no cis_coherence rule → verdict byte-stable).
    "cellline-methylation-expression-coherence",  # LoF leg-1: promoter methylation → own LOW expression (silencing)
    "expression-dependency-correlation",     # leg-2 (reuse): expression → dependency
    "abundance-dependency",                   # leg-2 (PROTEIN reuse): protein abundance → dependency. Borrowed
                                              # from the dependency axis; the protein sibling of the RNA leg-2.
                                              # VERDICT-INERT here (fires no cis_coherence rule).
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


# ── FACTORED-RECORD SHADOW (M1) — the CIS-COHERENCE per-axis builder. DESCRIPTIVE / non-gating: it
#    reads out whether the locus→expression→dependency chain is coherent. A coherent-driver call
#    SUPPORTS the thesis; the other measured patterns are informational (neutral). VERDICT-INERT:
#    surfaced by the fan-out into decision.claim_record_shadow.cis_coherence, consumed by NOTHING.
#    No verdict-disjoint corroborator → minimal coverage-only certainty. Mirrors the other axes' hook.
_CIS_COHERENT = {"coherent_cis_driver", "coherent_epigenetic_silencing"}


def _cis_availability(v) -> str:
    if v is None:
        return "not_wired"
    if v == "insufficient_cis_coherence":
        return "insufficient"
    return "measured_positive"                   # a measured coherence pattern


def _cis_certainty(v) -> dict:
    if v is None:
        return {"level": "low", "coverage": "low", "corroboration": "unmeasured", "unknown_mass": 1.0}
    if v == "insufficient_cis_coherence":
        return {"level": "low", "coverage": "low", "corroboration": "unmeasured", "unknown_mass": 0.5}
    return {"level": "medium", "coverage": "medium", "corroboration": "unmeasured", "unknown_mass": 0.0}


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — standalone, mirrors the other axes' hook."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    coherent = v in _CIS_COHERENT
    return assemble_claim_record(
        axis="cis_coherence",
        state=(v or "insufficient_cis_coherence"),
        direction=("supports" if coherent else "neutral"),
        availability=_cis_availability(v),
        magnitude={"level": ("moderate" if coherent else "none")},
        certainty=_cis_certainty(v),
        fired=fired,
        cards=cards,
    )


# ── canonical HEADLINE block (verdict + confidence + top tension) ────────────────────────────────
# cis-feature-coherence's declaration for the shared headline_core builder: the four coherence-LEG claim
# axes (CIS_DOSAGE / SILENCING / EXPR_DEP / CONJOINT), the cis_coherence-verdict vocabulary → human
# phrase, and the cross-grain PATIENT-disagreement caveat as the skill-specific tension source.
# Verdict-INERT — a one-way projection over the already-computed headline (the cis_coherence spine stays
# byte-stable, frozen by test_verdict.py + the target-contracts resolver golden). The cis_coherence
# verdict is a 2×2 INTERACTION owned by the resolver; the claim_vector axes are its LEG decomposition.
#
# POLARITY (colours the hero badge). This skill is VERDICT-INERT / coherence-CLASSIFYING — every class
# is a description of the locus→expression→dependency coherence pattern, not a drug call, so the DEFAULT
# is neutral. The one clearly FAVORABLE class is `coherent_cis_driver` (CN explains expression AND
# expression explains dependency — a coherent cis-driven oncogene addiction, the amplification-addiction
# signal that supports the target). No class is a clear UNfavorable call (an inert/uncoupled read is
# informative, not adverse), so everything else stays neutral.
_CIS_COHERENCE_VERDICT_PHRASE = {
    "coherent_cis_driver":          "Coherent cis-driven addiction (CN → expression → dependency)",
    "expressed_cis_coupled_inert":  "Expressed via cis-dosage, but dependency-inert",
    "dependency_without_cis_dosage": "Dependency without cis-dosage coupling (trans-regulated)",
    "cis_uncoupled_no_dependency":  "Cis-uncoupled, no dependency",
    "insufficient_cis_coherence":   "Insufficient cis-coherence evidence",
}

_CIS_COHERENCE_FAVORABLE = frozenset({"coherent_cis_driver"})


def _cis_coherence_verdict_polarity(v) -> str:
    """The skill's OWN reading of the coherence class (colours the hero badge; never a gate). VERDICT-INERT
    coherence-classifying skill → neutral by default; the one clearly FAVORABLE call is coherent_cis_driver
    (a coherent cis-driven oncogene addiction). No class is a clear UNfavorable drug call, so everything
    else stays neutral."""
    return "positive" if v in _CIS_COHERENCE_FAVORABLE else "neutral"


def _cis_tension_extra(headline: dict):
    """The sharpest cis-coherence caveat that is NOT already a per-axis claim conflict (the wrong-direction
    positive_anomaly / amp_expr_negative reads are surfaced by headline_core.rank_tension as claim
    conflicts): the cross-grain PATIENT arm DISAGREES with the cell-line call — the TCGA patient tumours do
    NOT replicate the cell-line cis-dosage (or methylation-silencing) coupling, a real corroboration
    failure. Severity 2 (below a wrong-direction conflict on a strong claim, which can reach 3, so that
    still wins the single slot). None when the patient arm agrees or was not measured."""
    if headline.get("patient_dosage_agrees_with_cellline") is False:
        return {"text": ("the cell-line cis-dosage coupling is NOT replicated in the TCGA patient arm "
                         "(cross-grain disagreement)"),
                "source": "patient_dosage_agrees_with_cellline", "severity": 2}
    if headline.get("patient_silencing_agrees_with_cellline") is False:
        return {"text": ("the cell-line methylation-silencing coupling is NOT replicated in the TCGA "
                         "patient arm (cross-grain disagreement)"),
                "source": "patient_silencing_agrees_with_cellline", "severity": 2}
    return None


_CIS_COHERENCE_HEADLINE_SPEC = HeadlineSpec(
    gate="cis_coherence",
    axis_labels={"CIS_DOSAGE": "CN→expression cis-dosage", "SILENCING": "methylation→low-expression",
                 "EXPR_DEP": "expression→dependency", "CONJOINT": "amp∩overexpr addiction"},
    axis_keys=("CIS_DOSAGE", "SILENCING", "EXPR_DEP", "CONJOINT"),
    critical_axes=("EXPR_DEP",),   # EXPR_DEP (does expression explain dependency?) is THE decision-critical
                                   # leg — without it the CN→expression coupling is abundance, not addiction.
    verdict_label=lambda v: _CIS_COHERENCE_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    tension_extra=_cis_tension_extra,
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed cis-coherence headline. Reads the
    resolved cis_coherence_verdict + the verdict-inert claim_vector / key_signals; never moves the spine.
    No CERTAINTY_MODEL sidecar is emitted by this skill, so confidence is derived from the claim vector's
    corroboration (which draws on the cross-grain TCGA patient-agreement arm — a real second leg)."""
    v = headline.get("cis_coherence_verdict")
    return build_headline(headline, headline.get("claim_vector"), headline.get("key_signals"),
                          spec=_CIS_COHERENCE_HEADLINE_SPEC, verdict_token=v,
                          driving_rule_id=headline.get("driving_rule_id"),
                          verdict_polarity=_cis_coherence_verdict_polarity(v))


def _emit_skill_figures(decision, figures_root):
    """--figures emitter: the canonical headline hero (verdict · confidence · top tension). Additive /
    display-only, offline, best-effort (missing block → [], spine unaffected)."""
    return emit_headline_hero(decision, figures_root)


def _slope_ratio(protein_slope, mrna_slope):
    """mRNA-vs-protein dosage-buffering ratio = protein_slope / mrna_slope (VERDICT-INERT fingerprint).

    ~1 → the CN dosage-effect is preserved at the protein level = a genuinely dosage-sensitive cis-driver
    (ERBB2/MYC/MDM2); ≪1 → protein is post-transcriptionally BUFFERED (mRNA rises with CN, protein does
    not). None when either slope is missing or the mRNA slope is ~0 (ratio undefined / uninformative)."""
    if protein_slope is None or mrna_slope is None:
        return None
    if abs(mrna_slope) < 1e-6:
        return None
    return round(float(protein_slope) / float(mrna_slope), 4)


def _headline(cards, fired, verdict_pair):
    def _s(cid):
        return card_summary(cards, cid)
    cis = _s("cis-feature-expression-coherence")   # GoF leg-1 (mRNA)
    prot = _s("cis-feature-protein-coherence")      # GoF leg-1 (PROTEIN) — verdict-inert
    meth = _s("cellline-methylation-expression-coherence")  # LoF leg-1
    corr = _s("expression-dependency-correlation")  # leg-2 (correlation)
    abdep = _s("abundance-dependency")              # leg-2 (PROTEIN) — verdict-inert
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
    hl = {
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
        # GoF leg-1 (PROTEIN): CN → own-PROTEIN cis-dosage (VERDICT-INERT). The mRNA-vs-protein slope
        # RATIO is the dosage-buffering fingerprint: ~1 = dosage-sensitive cis-driver (CN raises both
        # mRNA and protein, ERBB2/MYC/MDM2); ≪1 = post-transcriptionally BUFFERED passenger.
        "cis_protein_dosage_class": prot.get("cis_protein_dosage_class"),
        "cn_prot_spearman_r": prot.get("cn_prot_spearman_r"),
        "cn_prot_slope_log2abundance_per_cn": prot.get("cn_prot_slope_log2abundance_per_cn"),
        "delta_log2abundance_amplified_vs_neutral": prot.get("delta_log2abundance_amplified_vs_neutral"),
        "n_paired_models_cn_protein": prot.get("n_paired_models_cn_protein"),
        "mrna_vs_protein_dosage_slope_ratio": _slope_ratio(
            prot.get("cn_prot_slope_log2abundance_per_cn"), cis.get("cn_expr_slope_log2tpm_per_cn")),
        # leg-2: expression/feature → own-dependency (reused)
        "expression_dependency_correlation_class": corr.get("correlation_class"),
        "expression_dependency_pearson_r": corr.get("pearson_r"),
        # leg-2 (PROTEIN reuse): protein abundance → dependency (VERDICT-INERT)
        "abundance_dependency_class": abdep.get("abundance_dependency_class"),
        "protein_dependency_pearson_r": abdep.get("protein_dependency_pearson_r"),
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
    # verdict-INERT LEG-decomposition claim-vector (12th concrete) — CIS_DOSAGE/SILENCING/EXPR_DEP/
    # CONJOINT, each with citable atoms + cross-grain PATIENT-agreement corroboration. The cis_coherence
    # VERDICT is an INTERACTION of these legs (owned by the resolver); this is the decomposition, NOT a
    # verdict echo, so it stays verdict-inert (byte-stable).
    hl["claim_vector"] = cis_coherence_claim_vector(hl, cards)
    hl["key_signals"] = cis_coherence_key_signals(hl, cards)
    # Canonical HEADLINE block (verdict + confidence + top tension) — the concise, consumer-facing headline
    # message as deterministic text + a renderer-agnostic hero payload. A verdict-INERT projection over the
    # claim_vector / key_signals just built. Best-effort: a formatting/read fault must NEVER discard the
    # cis-coherence spine already fully built in `hl` (same degrade discipline as tumor-presence / safety).
    # On the happy path this is byte-additive (no _enrichment_errors key), so the verdict spine is unaffected.
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — cis-feature-coherence emits a verdict-SHAPED
    # string (e.g. expressed_cis_coupled_inert) that is explicitly NOT a call, so role=INERT → the report
    # renders as a view with polarity=not_scored, never scored. Best-effort + verdict-INERT.
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        hl["skill_report"] = build_skill_report(
            role=ROLE_INERT,
            verdict=hl.get("cis_coherence_verdict"),
            driving_rule_id=hl.get("driving_rule_id"),
            headline_block=hl.get("headline_block"),
            claim_vector=hl.get("claim_vector"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        hl["skill_report"] = None
    return hl


_SYNTHESIS_FACET_KEYS = (
    "cis_coherence_verdict", "driving_rule_id", "cis_dosage_class", "methylation_silencing_class",
    "expression_dependency_correlation_class", "amp_expr_stratification_class",
    # protein legs (VERDICT-INERT): CN→protein dosage + the mRNA-vs-protein buffering ratio, and protein→dep
    "cis_protein_dosage_class", "mrna_vs_protein_dosage_slope_ratio", "abundance_dependency_class",
    "patient_dosage_agrees_with_cellline", "patient_silencing_agrees_with_cellline",
    "claim_vector", "key_signals",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
    # the UNIFIED cross-skill output object (docs/UNIFIED_OUTPUT_CONTRACT.md) — Wave-3 inert-role adoption
    "skill_report",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT cis-coherence facet for the composed synthesis. Reuses _headline (single
    source) + returns the LEG-decomposition claim_vector (CIS_DOSAGE/SILENCING/EXPR_DEP/CONJOINT) with its
    citable atoms + the cross-grain patient-agreement flags. The verdict is an INTERACTION owned by the
    resolver — this never echoes or moves it."""
    h = _headline(cards, fired, verdict_pair)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = ("Deterministic cis-feature-coherence facet; claim_vector is the LEG decomposition "
                            "of the coherence cross-tab (the verdict is their INTERACTION, owned by the "
                            "resolver). CIS_DOSAGE/SILENCING corroboration uses the TCGA patient-agreement arm.")
    return facet


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="cis_coherence",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
        # NET-NEW capsule-driven narrator (generic engine + this lens's LensConfig).
        synthesize_fn=make_synthesize_fn(_LENS),
        # Skill-level graphics (opt-in --figures): the canonical headline hero. Additive / display-only.
        skill_figures_fn=_emit_skill_figures,
        # Signals-first: tuned sub-group reader for the cis-coherence vocabulary. Verdict-INERT.
        subgroup_classify=make_value_classifier(_CIS_VALUE_TIERS),
    ))
