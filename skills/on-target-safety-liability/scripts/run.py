#!/usr/bin/env python3
"""on-target-safety-liability — Phase-G partial skill (graduated 2026-07-08).

Germline LoF-constraint safety signal from gnomAD.

Calls the shared run_wired_skill dispatcher (2026-07-09 refactor).
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field, card_summary
from _skills_common.claim_record import assemble_claim_record
from _skills_common.safety_claims import safety_claim_vector, safety_key_signals
from _skills_common.safety_question_table import safety_question_table
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.subgroup_derivation import make_value_classifier
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import ON_TARGET_SAFETY as _SAFETY_LENS

# Signals-first sub-group reader (VERDICT-INERT). Thesis: on-target safety LIABILITY — signal = strength
# of the liability, so high constraint / broad normal expression / germline pathogenicity → strong. NOTE
# the polarity INVERSION vs the dependency lens: a strongly_selective dependency is REASSURING for safety
# (low broad-tox liability) → weak, whereas pan-essential/broad = strong liability. default_classify fallback.
_SAFETY_VALUE_TIERS = {
    "highly_constrained": "strong", "moderately_constrained": "moderate", "unconstrained": "absent",
    "broadly_expressed_normal": "strong", "broad_normal_expression": "strong",
    "selective_normal_expression": "moderate", "restricted_normal_expression": "weak",
    "germline_pathogenic": "strong", "germline_likely_pathogenic": "moderate", "germline_benign": "absent",
    "autosomal_dominant_loss": "strong", "haploinsufficient": "strong", "recessive_only": "weak",
    "lof_risk_phenotype": "strong", "no_burden_signal": "absent",
    "lethal": "strong", "developmental_only": "moderate", "no_ko_phenotype": "absent",
    # pan-essentiality-as-safety: broadly essential = broad-tox liability; SELECTIVE = reassuring (low liability)
    "broad_nonselective": "strong", "pan_essential": "strong",
    "strongly_selective": "weak", "moderately_selective": "weak", "not_essential": "absent",
}
from _skills_common.resolver import resolve_or_raise
from _skills_common.modality_safety import safety_verdict_by_modality
from _skills_common.narrative import build_narrative


SKILL_NAME = "on-target-safety-liability"
SKILL_VERSION = "1.15.0"   # 1.15.0 (2026-08-28): NET-NEW capsule-driven narrator (had none). Verdict-INERT.   # 1.14.0 (2026-08-27): tuned signals-first sub-group reader. Verdict-INERT.  # 1.13.0 (2026-08-26): emit per-verdict `narrative` (movers/dissenters/
                          # flip_conditions/rule_sentences) in the headline — VERDICT-INERT, best-effort
                          # (Stage B of the interpretability workstream; safety pilot). Verdict byte-stable.
                          # 1.12.0 (2026-08-25): compose onsides-adverse-event-safety (OnSIDES
                          # drug-label ADE, per-MedDRA-term incl. boxed-warning severity) — VERDICT-INERT
                          # DISPLAY card, finer-grained than drug-warning-safety. Gene attribution is a
                          # FUZZY drug-name->gene join (~63% match) + per-MedDRA-term grain (no per-organ,
                          # MedDRA license), so it is context-only, never a resolver rung. Verdict byte-stable.
                          # 1.11.0 (2026-08-21): compose drug-warning-safety (OT pharmacovigilance
                          # CONTEXT) — VERDICT-INERT, closes the P5 drug_warning placeholder axis
                          # (only colocalisation remains). Verdict byte-stable (no resolver rung).
                          # NOTE: stamped into provenance.yaml — MUST equal SKILL.md metadata.version
                          # (guarded by skills/tests/test_version_parity.py).
                          # 1.10.0 (2026-08-21): data-utilization expansion — compose pan-cancer-crispr-
                          # dependency-distribution (pan-essential broad-tox HOLD) + normal-tissue-liability
                          # (HPA-IHC essential-tissue protein HOLD); + recessive-only reassurance leg (via
                          # safety.resolver 1.5.0). +2 headline/claim axes (PAN_ESSENTIAL, NORMAL_TISSUE).
                          # 1.8.0: compose copy-number-distribution to activate the
                          # amplification guard. run.py constant was left at 1.7.0 while SKILL.md
                          # advanced to 1.8.0 (2026-08-17 version-parity reconciliation).
                          # 1.4.0: + human-genetics leg — target-safety-prioritisation (OT context)
                          # + gene-burden-safety (OT rare-variant burden LoF-tolerance; verdict-moving
                          # rule resolver-wired).
                          # 1.3.0: + alteration-role for mutant-selective mechanism-conditioning of
                          # the WT gnomAD-constraint concern (activating-driver-role-safety-context)

CARDS = [
    "gnomad-lof-constraint",
    "target-safety-prioritisation",   # (2026-07-24) — OT 26.06 engineered target-priority
                                      # scores as safety-orienting CONTEXT (safety-event / genetic-
                                      # constraint / mouse-KO bands). VERDICT-INERT: no warning, no
                                      # resolver reference — it orients the reader alongside the
                                      # authoritative gnomAD constraint call; the verdict-moving human-
                                      # genetics signals arrive in the gene_burden/clingen/
                                      # mouse_phenotype legs. Spine byte-stable.
    "normal-tissue-liability-gtex",   # Q3 — GTEx normal-tissue atlas (critical-organ liability +
                                      # breadth). Its normal-liability-* rules emit SM/degrader
                                      # opposing on critical_organ_liability (on-target-off-tumor for
                                      # full-KO modalities); supportive on restricted_normal. Additive
                                      # signal — the safety RESOLVER stays keyed to gnomAD (byte-stable).
    "alteration-role",                # 2026-07-23 — mechanism CONTEXT for mutant-selective conditioning.
                                      # Its activating-driver-role-safety-context rule (intracellular axis)
                                      # fires on functional_direction==activating; the safety RESOLVER
                                      # combines it with highly-constrained-safety-warning (when_all_fired)
                                      # to DOWNGRADE the WT-constraint concern → wt_constraint_mechanism_
                                      # mismatch (a GoF driver is drugged mutant-selectively; gnomAD
                                      # constraint is about the WILD-TYPE protein the drug spares).
    "clinvar-pathogenicity-safety",   # (2026-07-24) — ClinVar germline-pathogenic
                                      # variants. germline_pathogenic -> clinvar-germline-pathogenic-
                                      # safety-warning (SM/degrader opposing, 4th corroborating germline
                                      # leg). SOMATIC guardrailed out. Resolver-wired (safety 1.3.0).
    "mouse-ko-phenotype",             # (2026-07-24) — mouse-KO normal-physiology safety.
                                      # lethal_ko (adult/postnatal) -> mouse-ko-lethal-safety-warning
                                      # (SM/degrader opposing, INFERRED-tier caution); developmental_
                                      # only -> neutral (the guardrail). Resolver-wired.
    "clingen-dosage",                 # (2026-07-24) — ClinGen dosage sensitivity. dosage_
                                      # sensitivity_class=autosomal_dominant_loss -> clingen-dominant-
                                      # loss-safety-warning (SM/degrader opposing, haploinsufficiency
                                      # full-KO concern). Verdict-moving rule resolver-wired.
    "gene-burden-safety",             # (2026-07-24) — population rare-variant BURDEN LoF-
                                      # tolerance (OT 26.06). burden_safety_class=lof_risk_phenotype ->
                                      # gene-burden-lof-safety-warning (SM/degrader opposing, the full-KO
                                      # WT-loss safety signal); protective -> drug-positive. The
                                      # verdict-moving rule is NOT yet resolver-referenced (byte-stable);
                                      # safety.resolver.yaml wires it, composed with the
                                      # same mutant-selective downgrade as the gnomAD path.
    "copy-number-distribution",       # (cards review 2026-08-17) — AMPLIFICATION guard for the
                                      # mutant-selective downgrade. The dispatcher enriches this card
                                      # with patient_focal_cn_class (TCGA GISTIC, indication-specific);
                                      # its copy-number-amplified-oncogene-safety-context rule fires on
                                      # recurrent_focal_amplification and the safety resolver's GROUP-0
                                      # guard KEEPS the on-target-safety HOLD
                                      # for an amplification-driven oncogene (ERBB2/MDM2) — the drug
                                      # hits WT protein, so the mutant-selective-sparing logic fails.
    "functional-gene-state",          # (PR-4c 2026-08-24) — RARELY-ALTERED guard, the mutation-state
                                      # analogue of the amplification guard above. functional_state_
                                      # class==rarely_altered fires functional-gene-state-rarely-altered-
                                      # neutral; the safety resolver's GROUP-0b guard KEEPS the WT-loss
                                      # HOLD for an amplification/role-only oncogene with no recurrent
                                      # activating mutation (MCL1) — drugged by PAN-inhibition, so the
                                      # mutant-selective-sparing (GROUP-1) downgrade must NOT fire.
    "pan-cancer-crispr-dependency-distribution",  # (data-util expansion 2026-08-21) — DepMap pan-
                                      # essentiality as a BROAD-TOX safety signal. dependency_class==
                                      # common_essential fires pan-essential-broad-tox-safety-warning
                                      # (safety.resolver 1.5.0) → pan_essential_broad_tox_concern HOLD:
                                      # a full-KO modality abrogates an essential function in NORMAL
                                      # tissue too. Same card the dependency skill vetoes as
                                      # pan_essential_killer (no window); here it is the SAFETY reading.
                                      # Mechanism-conditioned (GROUP-1 downgrade) + amp-guarded (GROUP-0).
    "normal-tissue-liability",        # (data-util expansion 2026-08-21) — HPA-IHC protein normal-tissue
                                      # liability. essential_tissue_flag==present fires normal-tissue-
                                      # protein-liability-safety-warning → normal_tissue_protein_safety_
                                      # concern HOLD: the intracellular (SM/degrader) reading of the same
                                      # card surface-modality-fit uses for its BiTE/TCE killer. This is
                                      # PROTEIN-level critical-organ liability; the GTEx card above is
                                      # RNA-breadth. No mutant-selective downgrade (full-KO hits WT).
    "drug-warning-safety",            # (2026-08-21) — OT pharmacovigilance CONTEXT: do drugs that ENGAGE
                                      # the target carry FDA black-box / withdrawn warnings (drug_warning ⋈
                                      # drug_mechanism_of_action)? VERDICT-INERT (no resolver rung; like
                                      # target-safety-prioritisation) — a confounded on-target signal that
                                      # ORIENTS, never HOLDs. Closes the P5 drug_warning placeholder axis.
    "onsides-adverse-event-safety",   # (2026-08-25) — OnSIDES drug-label ADE CONTEXT: per-MedDRA-term
                                      # adverse-effect profile (incl. boxed-warning severity) of drugs that
                                      # ENGAGE the target, finer-grained than the drug-warning boolean above.
                                      # VERDICT-INERT (no resolver rung): the gene attribution is a FUZZY
                                      # drug-name->gene join (~63% match; DGIdb directional recall-union so
                                      # drug-level + class-wide — cannot separate on- from off-target) and
                                      # per-MedDRA-TERM grain only (per-organ/SOC needs a MedDRA license).
                                      # ORIENTS, never HOLDs. Same posture as drug-warning-safety.
]

QUESTION = ("Is {target} highly constrained against loss-of-function "
            "variants in the gnomAD population, and what does this imply "
            "for on-target safety of full-KO modalities (degrader, RNA "
            "therapeutic, full-inhibition SM) in {indication}?")

PARTIAL_STATUS_NOTE = (
    "on-target-safety-liability now integrates a FIVE-leg human-genetics safety axis, all "
    "verdict-moving via safety.resolver 1.3.0: gnomAD germline LoF-constraint + rare-variant "
    "BURDEN (gene-burden-safety) + ClinGen dosage-sensitivity (clingen-dosage) + mouse-KO "
    "normal-physiology (mouse-ko-phenotype) + ClinVar germline pathogenicity (clinvar-"
    "pathogenicity-safety) — each mechanism-conditioned by the mutant-selective downgrade "
    "(wt_constraint_mechanism_mismatch / wt_human_genetics_mechanism_mismatch) when an activating "
    "driver is present (requires alteration-role in-scope; wired 2026-07-24). target-safety-"
    "prioritisation is verdict-inert OT context. DATA-UTILIZATION EXPANSION (2026-08-21, safety.resolver "
    "1.5.0): three further already-ingested legs now move the verdict — DepMap pan-essentiality "
    "(pan_essential_broad_tox_concern HOLD, broad normal-tissue tox), HPA-IHC essential-tissue protein "
    "(normal_tissue_protein_safety_concern HOLD — the intracellular reading of the normal-tissue-liability "
    "card, no longer only on the surface axis), and ClinGen recessive-only carrier-health REASSURANCE "
    "(tolerant_reduced_safety_risk, above the data-unavailable rung only). REMAINING GAPS keeping this "
    "`partial`: the readers must still fire in an emitted package / dashboard_spec; and the P5 "
    "drug_warning is now WIRED as VERDICT-INERT pharmacovigilance context (drug-warning-safety card, "
    "2026-08-21); only the colocalisation OT leg remains deferred (study-locus-keyed; marginal on-target "
    "signal for oncology)."
)


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (2026-07-20).
    The former if-chain now lives in resolvers/safety.resolver.yaml (target-contracts),
    evaluated by the ONE interpreter both engines call. Proven byte-for-byte equivalent to
    the former if-chain by the golden-oracle test. A missing spec raises (the resolver is
    the source of truth — no silent fallback to a stale copy, which would reintroduce drift)."""
    return resolve_or_raise(fired, "safety")

# The mutant-selective DOWNGRADE verdicts — a WT-constraint / human-genetics concern that is
# largely nullified for an allele-selective mechanism. Every such verdict must carry the
# mechanism-conditioning note (incl. the conditionality caveat). By naming convention these end in
# `_mechanism_mismatch`; the Guard-A test (skills/tests/test_resolver_verdict_consumers.py) asserts
# this set == the resolver's *_mechanism_mismatch verdicts, so a new downgrade verdict can't
# silently lose its note (the wt_human_genetics_mechanism_mismatch bug).
# RETIRED 2026-08-24 (VERDICT_REPRESENTATION.md Layer-2b/3): the resolver no longer emits a scalar
# mutant-selective downgrade — the modality-conditional downgrade moved to the per-modality safety
# verdict (safety_verdict_by_modality) + tp_gates exists-safe-modality logic. Empty set; Guard-A
# (test_resolver_verdict_consumers) now asserts the resolver emits ZERO *_mechanism_mismatch verdicts.
_MECHANISM_MISMATCH_VERDICTS = frozenset()


# ── canonical HEADLINE block (verdict + confidence + top tension) ────────────────────────────────
# The safety declaration for the shared headline_core builder: the five INVERSE-VALENCE liability claim
# axes (CONSTRAINT/BURDEN/DOSAGE/CLINVAR/MOUSE_KO), the safety-verdict vocabulary → human phrase, and the
# mutant-selective-downgrade conditionality as the skill-specific tension source. Verdict-INERT — a
# one-way projection over the already-computed headline (the safety spine stays byte-stable, frozen by
# test_safety_replay.py + the golden-oracle resolver test).
#
# POLARITY (colours the hero badge). These are LIABILITY axes: a STRONG claim signal is a safety CONCERN.
# But the BADGE polarity encodes the DESIRABILITY of the resolved verdict FOR A DRUG PROGRAM (how a reader
# reads a red/blue badge), NOT the raw signal direction:
#   * a safety-LIABILITY / LoF-intolerant HOLD (highly_constrained / human_genetics concern) is UNdesirable
#     → "negative" (red);
#   * a tolerant / reduced-risk read — AND a mutant-selective mechanism DOWNGRADE, where the WT-loss
#     concern no longer applies to an allele-selective agent — is desirable/reassuring → "positive" (blue);
#   * the equivocal mid-band (moderately_constrained) + coverage gaps (data_unavailable / insufficient)
#     → "neutral" (grey).
_SAFETY_VERDICT_PHRASE = {
    # safety CONCERNS (nomination HOLDs) — undesirable for a full-KO modality
    "highly_constrained_safety_concern":     "Highly LoF-constrained — safety concern",
    "human_genetics_safety_concern":         "Human-genetics safety concern",
    "pan_essential_broad_tox_concern":       "Pan-essential — broad-tox safety concern",
    "normal_tissue_protein_safety_concern":  "Essential-tissue protein — safety concern",
    # (mutant-selective downgrade RETIRED 2026-08-24 — modality-conditionality now in the per-modality
    #  safety verdict + tp_gates exists-safe-modality; the resolver emits the raw concern, no mismatch token)
    # tolerant / reduced-risk
    "tolerant_reduced_safety_risk":          "LoF-tolerant — reduced safety risk",
    # equivocal mid-band + gaps
    "moderately_constrained_safety":         "Moderately LoF-constrained (equivocal)",
    "data_unavailable":                      "Data unavailable",
    "insufficient":                          "Insufficient evidence",
}

# Verdict → program-desirability polarity (see the POLARITY note above). Reused by the hero-badge colour;
# never a gate.
_SAFETY_CONCERN_VERDICTS = frozenset({
    "highly_constrained_safety_concern", "human_genetics_safety_concern",
    "pan_essential_broad_tox_concern", "normal_tissue_protein_safety_concern",
})
_SAFETY_REASSURING_VERDICTS = frozenset({
    "tolerant_reduced_safety_risk",
    # (mutant-selective mismatch downgrades RETIRED 2026-08-24 — see _MECHANISM_MISMATCH_VERDICTS)
})


def _safety_verdict_polarity(v) -> str:
    """The skill's OWN reading of the resolved verdict (colours the hero badge; never a gate). Polarity
    encodes DESIRABILITY for a drug program, not raw signal direction (these are inverse-valence liability
    axes): a LoF-intolerant HOLD is a CONCERN (negative); a tolerant read OR a mutant-selective downgrade
    is reassuring (positive); the equivocal mid-band + coverage gaps stay neutral."""
    if v in _SAFETY_CONCERN_VERDICTS:
        return "negative"
    if v in _SAFETY_REASSURING_VERDICTS:
        return "positive"
    return "neutral"


def _safety_tension_extra(headline: dict):
    """The sharpest safety caveat: the mutant-selective DOWNGRADE is CONDITIONAL on an allele-selective
    modality — a pan-target degrader / WT-hitting inhibitor re-exposes the WT-loss concern. Surfaced only
    when the verdict is a downgrade (mechanism_conditioning_note is set)."""
    if headline.get("mechanism_conditioning_note"):
        return {"text": ("the downgraded WT-loss safety concern is CONDITIONAL on an allele-selective "
                         "modality — a pan-target degrader / WT-hitting inhibitor re-exposes it"),
                "source": "mechanism_conditioning_note", "severity": 3}
    return None


_SAFETY_HEADLINE_SPEC = HeadlineSpec(
    gate="safety",
    axis_labels={"CONSTRAINT": "gnomAD LoF constraint", "BURDEN": "population gene-burden",
                 "DOSAGE": "ClinGen dosage", "CLINVAR": "germline pathogenicity",
                 "MOUSE_KO": "mouse-KO phenotype", "PAN_ESSENTIAL": "DepMap pan-essentiality",
                 "NORMAL_TISSUE": "normal-tissue protein (HPA-IHC)"},
    axis_keys=("CONSTRAINT", "BURDEN", "DOSAGE", "CLINVAR", "MOUSE_KO", "PAN_ESSENTIAL", "NORMAL_TISSUE"),
    critical_axes=("CONSTRAINT",),
    verdict_label=lambda v: _SAFETY_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    tension_extra=_safety_tension_extra,
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed safety headline. Reads the resolved
    verdict + the verdict-inert claim_vector / key_signals; never moves the spine. No CERTAINTY_MODEL
    sidecar is emitted by this skill, so confidence is derived from the claim vector's corroboration."""
    v = headline.get("safety_verdict")
    return build_headline(headline, headline.get("claim_vector"), headline.get("key_signals"),
                          spec=_SAFETY_HEADLINE_SPEC, verdict_token=v,
                          driving_rule_id=headline.get("driving_rule_id"),
                          verdict_polarity=_safety_verdict_polarity(v))


def _emit_skill_figures(decision, figures_root):
    """--figures emitter: the canonical headline hero (verdict · confidence · top tension). Additive /
    display-only, offline, best-effort (missing block → [], spine unaffected)."""
    return emit_headline_hero(decision, figures_root)


# ── FACTORED-RECORD SHADOW (M1) — the SAFETY per-axis builder, and the axis that best exercises the
#    record's `modality_scope` coordinate (VERDICT_REPRESENTATION §8): a WT-loss safety concern is
#    modality-CONDITIONAL, not a scalar. It opposes an engages-WT biologic (degrader/RNA), is only
#    conditional for an allele-selective small molecule, and is n/a on surface modalities. The record
#    carries that per-channel from safety_verdict_by_modality(fired) — the honest replacement for the
#    retired GoF-role-proxy downgrade. VERDICT-INERT: surfaced by the fan-out into
#    decision.claim_record_shadow.safety, consumed by NOTHING. Mirrors the other axes' _claim_record.
_SAFETY_CONCERNS = frozenset({
    "highly_constrained_safety_concern", "human_genetics_safety_concern",
    "normal_tissue_protein_safety_concern", "pan_essential_broad_tox_concern",
})
_SAFETY_OPEN_WORLD = {"data_unavailable", None}
# the verdict-driving concern instruments — coverage/unknown_mass are computed over these
_SAFETY_DECISION_CARDS = ("gnomad-lof-constraint", "normal-tissue-liability-gtex",
                          "clinvar-pathogenicity-safety", "mouse-ko-phenotype", "clingen-dosage",
                          "gene-burden-safety", "pan-cancer-crispr-dependency-distribution",
                          "normal-tissue-liability")
# safety_verdict_by_modality action -> the record's modality_scope value
_SAFETY_ACTION_TO_SCOPE = {"hold": "unfavorable", "conditional": "conditional",
                           "supportive": "favorable", "no_concern": "favorable",
                           "not_applicable": "na"}


def _safety_availability(v) -> str:
    if v in _SAFETY_OPEN_WORLD:
        return "not_wired"                       # open-world → assembler forces unknown/neutral
    if v == "insufficient":
        return "insufficient"
    if v == "tolerant_reduced_safety_risk":
        return "measured_negative"               # measured, concern ABSENT (reassuring)
    return "measured_positive"                   # a measured safety concern present


def _safety_finding(v):
    """(direction, magnitude.level) for the safety liability finding."""
    if v in _SAFETY_CONCERNS:
        return "opposes", "strong"
    if v == "moderately_constrained_safety":
        return "opposes", "moderate"
    if v == "tolerant_reduced_safety_risk":
        return "supports", "none"                # reduced risk supports nomination
    return "neutral", "none"                     # insufficient / open-world


def _safety_certainty(cards) -> dict:
    """Coverage-only certainty (CERTAINTY_MODEL): safety has NO verdict-disjoint corroborator — every
    independent constraint line already drives the verdict — so corroboration is `unmeasured` and
    level == coverage. Coverage/unknown_mass over the concern instruments (_SAFETY_DECISION_CARDS)."""
    present = sum(1 for cid in _SAFETY_DECISION_CARDS
                  if (card_summary(cards, cid) and not card_summary(cards, cid).get("_missing")))
    frac = present / len(_SAFETY_DECISION_CARDS)
    coverage = "high" if frac >= 0.66 else ("medium" if frac >= 0.33 else "low")
    return {"level": coverage, "coverage": coverage, "corroboration": "unmeasured",
            "unknown_mass": round(1.0 - frac, 4)}


def _safety_modality_scope(fired) -> dict | None:
    """Map safety_verdict_by_modality's per-channel actions onto the record's modality_scope. The
    2-channel base = small_molecule + biologics (the engages-WT biologic, rna/degrader — the modality
    a WT-loss concern actually bears on); surface biologics (adc/bite_tce/antibody) + degrader carried
    as _refinements where the vector reports them (na for a WT-loss concern)."""
    vbm = safety_verdict_by_modality(fired) or {}

    def scope(ch):
        a = (vbm.get(ch) or {}).get("action")
        return _SAFETY_ACTION_TO_SCOPE.get(a)

    out: dict = {}
    sm = scope("small_molecule")
    if sm:
        out["small_molecule"] = sm
    bio = scope("rna") or scope("degrader")      # the engages-WT biologic represents the base
    if bio:
        out["biologics"] = bio
    refinements = {}
    for ch in ("adc", "bite_tce", "degrader", "antibody"):
        s = scope(ch)
        if s:
            refinements[ch] = s
    if refinements:
        out["_refinements"] = refinements
    return out or None


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — standalone, mirrors the other axes' hook."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    direction, level = _safety_finding(v)
    return assemble_claim_record(
        axis="safety",
        state=(v or "insufficient"),
        direction=direction,
        availability=_safety_availability(v),
        magnitude={"level": level},
        modality_scope=_safety_modality_scope(fired or []),
        certainty=_safety_certainty(cards),
        fired=fired,
        cards=cards,
    )


def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    # Mechanism-conditioning context: when the verdict is the mutant-selective downgrade, surface WHY
    # (the activating driver role) + the conditionality caveat so a consumer isn't left guessing.
    functional_direction = get_card_field(cards, "alteration-role", "functional_direction")
    is_mismatch = (v in _MECHANISM_MISMATCH_VERDICTS)
    hl = {
        "safety_verdict":   v,
        "driving_rule_id":  drv,
        "constraint_class": get_card_field(cards, "gnomad-lof-constraint", "constraint_class"),
        "pli_score":        get_card_field(cards, "gnomad-lof-constraint", "pli_score"),
        "loeuf_score":      get_card_field(cards, "gnomad-lof-constraint", "loeuf_score"),
        "mis_z_score":      get_card_field(cards, "gnomad-lof-constraint", "mis_z_score"),
        "syn_z_score":      get_card_field(cards, "gnomad-lof-constraint", "syn_z_score"),
        "obs_lof_count":    get_card_field(cards, "gnomad-lof-constraint", "obs_lof_count"),
        "exp_lof_count":    get_card_field(cards, "gnomad-lof-constraint", "exp_lof_count"),
        # Human OBSERVED-KO (2026-08-07) — the DIRECT-observation complement to
        # constraint: obs_hom_lof counts healthy humans HOMOZYGOUS for a predicted-LoF variant
        # (natural knockouts). natural_ko_observed = full loss tolerated in the population →
        # strong on-target safety reassurance for a full-KO modality (degrader/RNA), where
        # pLI/LOEUF only INFER intolerance. Additive/verdict-inert; surfaced for LLM/reviewer.
        "human_ko_observed_class": get_card_field(cards, "gnomad-lof-constraint", "human_ko_observed_class"),
        "obs_hom_lof_count":       get_card_field(cards, "gnomad-lof-constraint", "obs_hom_lof_count"),
        # human-genetics rare-variant burden (verdict-moving)
        "burden_safety_class": get_card_field(cards, "gene-burden-safety", "burden_safety_class"),
        "burden_min_pvalue":   get_card_field(cards, "gene-burden-safety", "min_pvalue"),
        "burden_top_disease":  get_card_field(cards, "gene-burden-safety", "top_disease"),
        # ClinGen dosage sensitivity (verdict-moving)
        "dosage_sensitivity_class": get_card_field(cards, "clingen-dosage", "dosage_sensitivity_class"),
        "dosage_top_disease":       get_card_field(cards, "clingen-dosage", "top_disease"),
        # Germline INHERITANCE MODE (2026-08-06) — the in-hand OMIM-style KO-safety facet: recessive_only
        # = het carriers healthy → full-KO REASSURANCE the dominant-focused dosage class understates.
        # Additive/verdict-inert; surfaced for the LLM/reviewer beside the dosage call.
        "germline_inheritance_mode": get_card_field(cards, "clingen-dosage", "germline_inheritance_mode"),
        # mouse-KO normal-physiology (verdict-moving)
        "mouse_ko_phenotype_class": get_card_field(cards, "mouse-ko-phenotype", "ko_phenotype_class"),
        "mouse_ko_top_lethal":      get_card_field(cards, "mouse-ko-phenotype", "top_lethal_label"),
        # ClinVar germline-pathogenicity
        "clinvar_pathogenic_class": get_card_field(cards, "clinvar-pathogenicity-safety", "clinvar_pathogenic_class"),
        "clinvar_top_disease":      get_card_field(cards, "clinvar-pathogenicity-safety", "top_disease"),
        # DepMap pan-essentiality — BROAD-TOX safety leg (verdict-moving via pan-essential-broad-tox-
        # safety-warning). common_essential = required across the whole panel → normal-tissue tox for
        # a full-KO modality (the SAFETY reading of the same signal the dependency skill vetoes).
        "dependency_class":   get_card_field(cards, "pan-cancer-crispr-dependency-distribution", "dependency_class"),
        "pan_essential_score": get_card_field(cards, "pan-cancer-crispr-dependency-distribution", "pan_essential_score"),
        # HPA-IHC protein normal-tissue liability — verdict-moving via normal-tissue-protein-liability-
        # safety-warning (essential_tissue_flag==present → essential-tissue on-target-off-tumor tox).
        "essential_tissue_flag":              get_card_field(cards, "normal-tissue-liability", "essential_tissue_flag"),
        "essential_tissues_flagged":          get_card_field(cards, "normal-tissue-liability", "essential_tissues_flagged"),
        "normal_tissue_breadth_class":        get_card_field(cards, "normal-tissue-liability", "normal_tissue_breadth_class"),
        # OT pharmacovigilance CONTEXT (verdict-inert): do drugs engaging the target carry black-box /
        # withdrawn warnings? Orients the reader; no resolver rung reads these.
        "drug_warning_class":                 get_card_field(cards, "drug-warning-safety", "drug_warning_class"),
        "drug_warning_has_black_box":         get_card_field(cards, "drug-warning-safety", "has_black_box"),
        "drug_warning_toxicity_classes":      get_card_field(cards, "drug-warning-safety", "toxicity_classes"),
        # OnSIDES drug-label ADE CONTEXT (verdict-inert): per-MedDRA-term adverse-effect profile (incl.
        # boxed-warning severity) of drugs engaging the target — fuzzy drug-name->gene join, per-term
        # grain. Orients the reader; no resolver rung reads these.
        "onsides_ade_class":                  get_card_field(cards, "onsides-adverse-event-safety", "onsides_ade_class"),
        "onsides_has_boxed_warning":          get_card_field(cards, "onsides-adverse-event-safety", "has_boxed_warning"),
        "onsides_example_boxed_warning_terms": get_card_field(cards, "onsides-adverse-event-safety", "example_boxed_warning_terms"),
        # mutant-selective conditioning (2026-07-23)
        "alteration_functional_direction": functional_direction,
        "mechanism_conditioning_note": (
            "gnomAD constraint reflects WILD-TYPE LoF-intolerance; this target is an ACTIVATING (GoF) "
            "driver typically drugged MUTANT-SELECTIVELY, so the WT-constraint safety concern is "
            "largely nullified (the therapy spares WT protein in normal tissue). CONDITIONAL on an "
            "allele-selective modality — a pan-target degrader / WT-hitting inhibitor re-exposes it."
        ) if is_mismatch else None,
    }
    # verdict-INERT claim-vector projection (5th concrete over claim_vector_core) — the SIGNAL
    # decomposition + citable liability atoms the composed target-profile fan-out surfaces to the
    # cross-evidence agent via _synthesis_facet. Never feeds the safety verdict.
    hl["claim_vector"] = safety_claim_vector(hl, cards)
    hl["key_signals"] = safety_key_signals(hl, cards)
    # PER-MODALITY safety verdict (VERDICT_REPRESENTATION.md Layer-2b, ADDITIVE/verdict-INERT).
    # Crosses the WT-loss safety concerns (wt_loss_safety_conditioning.yaml) against each modality's
    # wt_engagement (modality.enum.yaml): engages_wt (degrader/RNA) -> hold; conditional (small_molecule)
    # -> allele-selective agents spare WT; not_applicable (surface) -> dropped. The HONEST replacement
    # for the scalar `safety_verdict`'s GoF-role-proxy downgrade. Does NOT feed the scalar or the gate
    # yet (the gate-swap + retirement of the 6 role-proxy rungs is a separate calibration-verified change).
    hl["safety_verdict_by_modality"] = safety_verdict_by_modality(fired)
    # PER-VERDICT NARRATIVE (Stage B, VERDICT-INERT) — re-materialises the traversal the resolver
    # distils away: movers (the winning driver + same-direction referenced rules present), dissenters
    # (fired rules whose per-channel signal OPPOSES the resolved liability — e.g. a reassuring
    # tolerant/recessive-only leg that lost to a constraint concern), single-rule flip_conditions
    # (what would flip the call), and rule_sentences for every cited rule_id (fired OR not). The
    # deterministic, citeable substrate both the dashboard "why this verdict" panel and the Tier-3
    # synthesis consume. Best-effort: a build fault must never discard the safety spine.
    try:
        hl["narrative"] = build_narrative(axis="safety", gate="safety", fired=fired,
                                          verdict=v, driving_rule_id=drv)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["narrative"] = f"{type(exc).__name__}: {exc}"
        hl["narrative"] = None
    # Canonical HEADLINE block (verdict + confidence + top tension) — the concise, consumer-facing headline
    # message as deterministic text + a renderer-agnostic hero payload. A verdict-INERT projection over the
    # claim_vector / key_signals just built. Best-effort: a formatting/read fault must NEVER discard the
    # safety spine already fully built in `hl` (same degrade discipline the dispatcher applies to synthesis
    # / figures). On the happy path this is byte-identical (no _enrichment_errors key added), so the
    # golden-oracle + replay fixtures are unaffected.
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # The per-question (data · signal · confidence) LEADING table — verdict-INERT projection over the
    # just-built headline + claim_vector (mirrors tumor-presence / tumor-selectivity). Carried through
    # _synthesis_facet so the composed target-profile dashboard renders the same table. Best-effort.
    try:
        hl["question_table"] = safety_question_table(hl, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        hl["question_table"] = None
    return hl


# ── OPTIONAL cross-modal synthesis facet (lifts the claim_vector to the composed target-profile) ────
_SYNTHESIS_FACET_KEYS = (
    "safety_verdict", "driving_rule_id",
    "constraint_class", "burden_safety_class", "dosage_sensitivity_class",
    "clinvar_pathogenic_class", "mouse_ko_phenotype_class",
    "dependency_class", "pan_essential_score", "essential_tissue_flag", "normal_tissue_breadth_class",
    "drug_warning_class", "drug_warning_has_black_box", "drug_warning_toxicity_classes",
    "human_ko_observed_class", "germline_inheritance_mode", "alteration_functional_direction",
    "claim_vector", "key_signals",
    # the per-question (data·signal·confidence) rows — rendered as the leading table by target-profile too
    "question_table",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
    # the per-verdict narrative (movers / dissenters / flip_conditions / rule_sentences) — the citeable
    # substrate the composed "why this verdict" panel + Tier-3 synthesis consume (Stage C wires those)
    "narrative",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT safety facet for the composed target-profile synthesis. Reuses _headline
    (single source of truth) and returns the reconciliation-relevant subset, incl. the liability
    claim_vector + its citable atoms. Never moves the verdict; safe to omit."""
    h = _headline(cards, fired, verdict_pair)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = (
        "Deterministic on-target-safety facet. claim_vector is an INVERSE-valence LIABILITY decomposition "
        "(CONSTRAINT / BURDEN / DOSAGE / CLINVAR / MOUSE_KO) — a strong signal is a safety CONCERN, not a "
        "win; the safety VERDICT (incl. the mutant-selective-GoF WT-constraint downgrade) is owned by the "
        "safety resolver, not this projection.")
    return facet


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
        # Skill-level graphics (opt-in --figures): the canonical headline hero. Additive / display-only.
        skill_figures_fn=_emit_skill_figures,
        partial_status_note=PARTIAL_STATUS_NOTE,
        # Signals-first: tuned sub-group reader for the safety-LIABILITY vocabulary (note the polarity
        # inversion vs the dependency lens). Verdict-INERT.
        subgroup_classify=make_value_classifier(_SAFETY_VALUE_TIERS),
        # NET-NEW single-lens narrator (this skill had none → --synthesize was a no-op). Generic
        # capsule-driven engine + the safety LensConfig (LIABILITY polarity). Two-slot / verdict-inert.
        synthesize_fn=make_synthesize_fn(_SAFETY_LENS),
    ))
