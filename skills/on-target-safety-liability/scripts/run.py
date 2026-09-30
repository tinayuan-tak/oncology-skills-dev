#!/usr/bin/env python3
"""on-target-safety-liability — Phase-G partial skill (graduated 2026-07-08).

Germline LoF-constraint safety signal from gnomAD.

Calls the shared run_wired_skill dispatcher (2026-07-09 refactor).
"""

from __future__ import annotations

import sys

from _skills_common import card_summary, get_card_field
from _skills_common.claim_record import assemble_claim_record
from _skills_common.dispatcher import run_wired_skill
from _skills_common.headline_core import HeadlineSpec, build_headline, build_synthesis_facet
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.literature_retrieval import default_retrieve, verify_citations

# OPTIONAL (--literature) verdict-INERT LLM literature lane — the same shared fleet module wired into
# genomic-alteration #982 / functional-requirement #987 / tumor-presence #965 / tumor-selectivity #968.
# This skill uses run_wired_skill, so Phase-5 is a ONE-LINER: pass literature_fn=make_literature_fn(...)
# to the dispatcher (it attaches decision['literature_synthesis'] at seam 8a-iii and feeds it to the
# --synthesize narrator). Grounded in Europe PMC (PubTator3 fallback via default_retrieve; the safety
# lens query terms live in literature_retrieval._LENS_QUERY_TERMS) + PMID-verified via verify_citations.
from _skills_common.literature_synthesis import make_literature_fn
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import ON_TARGET_SAFETY as _SAFETY_LENS
from _skills_common.safety_claims import SAFETY_CLAIM_SPEC, safety_claim_vector, safety_key_signals
from _skills_common.safety_question_table import safety_question_table
from _skills_common.skill_report import ROLE_GATING, build_skill_report
from _skills_common.subgroup_derivation import make_value_classifier

# Signals-first sub-group reader (VERDICT-INERT). Thesis: on-target safety LIABILITY — signal = strength
# of the liability, so high constraint / broad normal expression / germline pathogenicity → strong. NOTE
# the polarity INVERSION vs the dependency lens: a strongly_selective dependency is REASSURING for safety
# (low broad-tox liability) → weak, whereas pan-essential/broad = strong liability. default_classify fallback.
_SAFETY_VALUE_TIERS = {
    "highly_constrained": "strong",
    "moderately_constrained": "moderate",
    "unconstrained": "absent",
    "broadly_expressed_normal": "strong",
    "broad_normal_expression": "strong",
    "selective_normal_expression": "moderate",
    "restricted_normal_expression": "weak",
    "germline_pathogenic": "strong",
    "germline_likely_pathogenic": "moderate",
    "germline_benign": "absent",
    "autosomal_dominant_loss": "strong",
    "haploinsufficient": "strong",
    "recessive_only": "weak",
    "lof_risk_phenotype": "strong",
    "no_burden_signal": "absent",
    "lethal": "strong",
    "developmental_only": "moderate",
    "no_ko_phenotype": "absent",
    # pan-essentiality-as-safety: broadly essential = broad-tox liability; SELECTIVE = reassuring (low liability)
    "broad_nonselective": "strong",
    "pan_essential": "strong",
    "strongly_selective": "weak",
    "moderately_selective": "weak",
    "not_essential": "absent",
}
from _skills_common.modality_safety import safety_verdict_by_modality
from _skills_common.narrative import build_narrative
from _skills_common.resolver import resolve_or_raise

SKILL_NAME = "on-target-safety-liability"
SKILL_VERSION = "1.25.0"  # 1.25.0 (2026-09-30, #2306 step 2 of epic SK#2210 / #1507 — reliability-facet EMIT on the landed L2a domain): each source_properties[*] entry now carries a typed, verdict-INERT (SK#2091) `reliability` object derived by the shared _skills_common/reliability.py _derive_reliability — n_effective projected from the property's own n-anchor (omitted where the property has no sample-N anchor); powered='unmeasured' UNIFORMLY (no calibrated per-property-kind floor exists yet — a #2219-style calibration follow-on); confound_flags/artifact_flags=[] (microenvironment_weighted path implemented + synthetic-tested, does not fire on safety anchors; floor_tie_percentile deferred); detection_strength OMITTED (no safety property is detection-kind). The L2b normal_liability_concordance island does NOT carry the facet (it reads only categorical per-source direction tokens with no per-arm anchors to derive from → honestly omitted per the locked shape's derive-from-arm rule). Skills-only (the governed catalog derivation-declaration is a deferred #2306 follow-on). ADDITIVE — every other field stays byte-stable; feeds no rule, moves no verdict.   # 1.24.0 (2026-09-30, PR-1a of epic SK#2210 / #1507 — the SAFETY generalisation of the tumor-presence L2a vertical SK#1941): the per-source observational (L2a) properties, which existed only IMPLICITLY inside the eight claim signal blocks, are lifted into a NAMED typed map `claim_vector.source_properties` (safety_claims.py `_SOURCE_PROPERTY_RECIPES_SAFETY`, 8 entries: germline_lof_constraint / dominant_lof_selection / population_burden_liability / germline_pathogenicity / dosage_sensitivity / ko_organismal_phenotype / normal_tissue_protein_liability / normal_tissue_rna_liability), each carrying its L1 card_id, the resolved observational property class, the RETAINED quantitative anchors ({field, value, scale} + ledger-declared semantic_role / interpretation_reach, #1525) and comparability metadata; and under --emit-envelope evidence_package.json gains the NAMED top-level sections source_properties (L2a) / integrated_properties (L2b normal_liability_concordance) / local_composites (the 8 axes), built by _evidence_sections(headline) and threaded through run_wired_skill(evidence_sections_fn=...). No `l3d` section — safety has no within-domain story object. TWO firsts piloted here for 1b-1e to copy: `comparability.valence: liability` (the inverse-valence marker, reusing the token the 24 existing safety atoms already emit, so a reader holding only the L2a export cannot mistake a STRONG read for a win) and the Wave-0c `interpretation` provenance object {function_id, version, disjunct_fired} — DECLARED in envelope v1.1 (ii) and until now implemented NOWHERE (its presence implementation #2227 is golden-blocked) — emitted on the ONE entry this domain resolves through a genuine multi-arm disjunction (normal_tissue_protein_liability / _normaltissue_sig: essential_tissue_flag | normal_tissue_breadth_fallback | tphp_hpa_blind_vital_organ_promotion | unmeasured) and OMITTED on the seven whose class token is a verbatim card read. DepMap pan-essentiality is deliberately NOT duplicated as a safety L2a property (it is the dependency domain's, read here at liability valence; the shared card is recorded in the catalog's dependence_group), nor is pharmacovigilance (on/off-target-confounded clinical CONTEXT, not an on-target biological property). ADDITIVE / VERDICT-INERT: no axis renamed, no new L2b family, no token minted; `source_properties` is omitted byte-stably when no source resolves; carries no `signal` key and is read by no rule/verdict/ladder, so safety_verdict + safety_verdict_by_modality + the resolver goldens + test_safety_replay are byte-stable. New contracts governance: contracts/vocabularies/property_catalog/safety.yaml.   # 1.23.0 (2026-09-29, SK#1794 pan-essential fail-open closure, PIN-COUPLED with TC fb43651e / safety.resolver 2.4.0 + AM 507439fc depmap_chronos_distribution 0.3.0): registers the two new verdict paths the resolver grew — (a) dependency_class == common_essential_unanchored (well-powered >=85% strongly-dependent fraction, curated core-essential anchor UNREACHABLE; split out of the safety-DARK common_essential_underpowered) fires pan-essential-unanchored-broad-tox-safety-warning → the SAME pan_essential_broad_tox_concern HOLD as the curated arm (an unverifiable pan-essential is a concern, never clean; driving_rule keeps provenance distinct); (b) broad_dependency_band == partial_broad_band (the 0.60-0.85 band that previously read CLEAN and co-corroborated the TC#895 tolerant reassurance) fires broad-dependency-partial-tox-safety-warning → NEW GRADED verdict broad_dependency_partial_tox_concern (caution ABOVE every tolerant rung, BELOW the HOLDs; deliberately NOT a nomination-gate hold — tp_gates registers it recognized/non-gating so the 12/504 band carriers stop fail-closing to a forced hold at pin time). Wiring: census-visible headline read of broad_dependency_band + synthesis-facet key; verdict phrase + concern polarity; risk_projection _SAFETY_BINS=1; PAN_ESSENTIAL claim signal/evidence + atom field + question-table row for common_essential_unanchored; resolver goldens (safety 19→21 rule_ids, dependency 26→27) + field_read_health regen. None-stable on pre-0.3.0 packages (band reads None; replay byte-stable).   # 1.22.0 (2026-09-28, SK#1793 organ-coverage spine, PIN-COUPLED with TC b2e19734 / safety.resolver 2.3.0): the TPHP HPA-BLIND vital-organ view goes VERDICT-BEARING — consumes the 4 new tphp_normal_protein 0.5.0 fields (tphp_hpa_blind_vital_organ_liability_class + count/names/uncovered; AM ae94fb3e): census-visible headline reads (aperture ratchet), synthesis facet, NORMAL_TISSUE claim signal/evidence/atom + key-signals label (safety_claims.py), question-table normal-tissue leg (safety_question_table.py). vital_organ_abundant fires tphp-hpa-blind-vital-organ-protein-safety-warning (intracellular_intrinsic axis) → resolver rung → normal_tissue_protein_safety_concern HOLD — closes the thyroid/adrenal/pituitary/nerve/blood coverage hole where an HPA-absent + gnomAD-tolerant target previously resolved REASSURING (tolerant_reduced_safety_risk). hpa_blind_vital_organs_uncovered surfaces the explicit coverage GAP (pituitary today), never silent absence. None-stable on pre-0.5.0 packages: all reads/claims degrade to the pre-1.22.0 bytes when the fields are absent (replay fixtures byte-stable).   # 1.21.0 (2026-09-28, SK#1792): whole-axis coverage gating on the SURFACED confidence — critical_axes broadened from ("CONSTRAINT",) to all 7 legs, so a clean verdict measured on gnomAD-tolerant alone is confidence-capped `weak` ("capped by thin coverage") instead of reading `strong`/`moderate`; question-table per-leg confidence graded from the claim-vector corroboration (high/moderate/single_arm/low) instead of a flat `moderate` (safety_question_table.py). Verdict-INERT: resolver/scalar verdict byte-stable (test_safety_replay); only headline_block.confidence + question_table confidence cells move.   # 1.20.0 (2026-09-24, L2b-3 / SK#1546): +sc-normal-celltype-expression card to feed a new VERDICT-INERT cross-source claim `normal_liability_concordance` (GTEx bulk × scRNA-normal × HPA-IHC normal-tissue liability, deterministic/no-LLM, on safety_claim_vector). The sc-normal veto enters the fired list but is NOT a safety.resolver rung nor in wt_loss_safety_conditioning ⇒ scalar + per-modality verdict byte-stable (test_safety_replay). Advances the evidence-property epic #1507 scorecard M3 (vocabulary reuse 2→3).   # 1.19.0 (2026-09-10, T0-3): +normal-tissue-protein-abundance-tphp (TPHP DIA-MS QUANTITATIVE vital-organ PROTEIN — tphp_vital_organ_liability_class). The safety substrate had RNA (GTEx) + categorical IHC (HPA) but NO quantitative protein; this fills the endocrine/vascular/CNS organs HPA-IHC is blind to (nerve/muscle/blood/adrenal/thyroid). VERDICT-INERT display CONTEXT: the card's rules live on the tumor-selectivity axis, not this skill's intracellular_intrinsic rules_scope, so it fires no safety rung and the scalar verdict is byte-stable. Backtested SM/degrader gate rule is a deliberate follow-on.   # 1.18.0 (2026-09-07, CASE-009 literature-discordance loop): +VERDICT-INERT pharmacovigilance_scope_caveat — clarifies drug_warning_class='no_warning' = no OT-registered FDA warning among engaging drugs, NOT absence of on-target toxicity (mechanism-based dose-limiting tox — TLS/cytopenias/neuropathy — often not boxed). Fires only on the measured-negative no_warning state; verdict/resolver/golden/replay byte-stable.
# 1.17.0 (2026-09-04): +OPTIONAL --literature lane (verdict-INERT LLM literature synthesis, Europe-PMC-grounded + PMID-verified via the shared _skills_common.literature_synthesis; run_wired_skill one-liner) mirroring genomic #982 / FR #987 / TP #965 / TS #968. + VERDICT-INERT signal-surfacing of the rich safety sub-fields the capsule projection ignored: a new PHARMACOVIGILANCE claim axis (on-target FDA warnings + toxicity classes of target-engaging drugs — OT drug-warning ⋈ MoA + OnSIDES boxed ADEs; confounded CONTEXT, corroboration capped, orients-not-holds), MOUSE_KO claim evidence += affected organ systems (organ_classes), CLINVAR claim evidence += confident germline-pathogenic variant count. PHARMACOVIGILANCE is LEFT OUT of the safety HeadlineSpec.axis_keys so headline_block/confidence/hero + the golden-oracle resolver + test_safety_replay verdict fixtures stay BYTE-STABLE. Verdict spine untouched.   # 1.16.0 (2026-08-28): + shet-lof-intolerance (continuous GeneBayes s_het, VERDICT-INERT complement to gnomAD constraint).   # 1.15.0: NET-NEW capsule-driven narrator (had none). Verdict-INERT.   # 1.14.0 (2026-08-27): tuned signals-first sub-group reader. Verdict-INERT.  # 1.13.0 (2026-08-26): emit per-verdict `narrative` (movers/dissenters/
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
    "shet-lof-intolerance",  # (2026-08-28) — CONTINUOUS dominant-LoF selection coefficient
    # (GeneBayes s_het, Zeng 2024). The continuous complement to the
    # binary gnomAD pLI/LOEUF constraint call — catches dosage-sensitive
    # small genes constraint misses. VERDICT-INERT (fires no rule, not in
    # the safety resolver) → spine byte-stable; a corroboration/confidence
    # annotation. Verdict-bearing rung is a deferred backtest-gated follow-up.
    "target-safety-prioritisation",  # (2026-07-24) — OT 26.06 engineered target-priority
    # scores as safety-orienting CONTEXT (safety-event / genetic-
    # constraint / mouse-KO bands). VERDICT-INERT: no warning, no
    # resolver reference — it orients the reader alongside the
    # authoritative gnomAD constraint call; the verdict-moving human-
    # genetics signals arrive in the gene_burden/clingen/
    # mouse_phenotype legs. Spine byte-stable.
    "normal-tissue-liability-gtex",  # Q3 — GTEx normal-tissue atlas (critical-organ liability +
    # breadth). Its normal-liability-* rules emit SM/degrader
    # opposing on critical_organ_liability (on-target-off-tumor for
    # full-KO modalities); supportive on restricted_normal. Additive
    # signal — the safety RESOLVER stays keyed to gnomAD (byte-stable).
    "alteration-role",  # 2026-07-23 — mechanism CONTEXT for the modality-conditional WT-loss
    # reading. Its activating-driver-role-safety-context rule fires on
    # functional_direction==activating but is now ORPHAN in the safety
    # resolver (the role-proxy DOWNGRADE was retired v2.0.0, 2026-08-24).
    # functional_direction feeds the per-modality safety verdict
    # (small_molecule=conditional: a GoF driver drugged mutant-selectively
    # spares the WT protein) + the claim_vector — NOT a scalar downgrade.
    "clinvar-pathogenicity-safety",  # (2026-07-24) — ClinVar germline-pathogenic
    # variants. germline_pathogenic -> clinvar-germline-pathogenic-
    # safety-warning (SM/degrader opposing, 4th corroborating germline
    # leg). SOMATIC guardrailed out. Resolver-wired (safety 1.3.0).
    "mouse-ko-phenotype",  # (2026-07-24) — mouse-KO normal-physiology safety.
    # lethal_ko (adult/postnatal) -> mouse-ko-lethal-safety-warning
    # (SM/degrader opposing, INFERRED-tier caution); developmental_
    # only -> neutral (the guardrail). Resolver-wired.
    "clingen-dosage",  # (2026-07-24) — ClinGen dosage sensitivity. dosage_
    # sensitivity_class=autosomal_dominant_loss -> clingen-dominant-
    # loss-safety-warning (SM/degrader opposing, haploinsufficiency
    # full-KO concern). Verdict-moving rule resolver-wired.
    "gene-burden-safety",  # (2026-07-24) — population rare-variant BURDEN LoF-
    # tolerance (OT 26.06). burden_safety_class=lof_risk_phenotype ->
    # gene-burden-lof-safety-warning (SM/degrader opposing, the full-KO
    # WT-loss safety signal); protective -> drug-positive. Resolver-wired
    # (human_genetics_safety_concern when_any_fired).
    "copy-number-distribution",  # (cards review 2026-08-17) — was the AMPLIFICATION guard for the
    # retired resolver GROUP-0 downgrade. The dispatcher enriches this card
    # with patient_focal_cn_class (TCGA GISTIC); its copy-number-amplified-
    # oncogene-safety-context rule is now ORPHAN (role-proxy downgrade
    # retired v2.0.0). Near-dead composition, retained as amplification
    # context only.
    "functional-gene-state",  # (PR-4c 2026-08-24) — RARELY-ALTERED guard. functional_state_
    # class==rarely_altered fires functional-gene-state-rarely-altered-
    # neutral (now ORPHAN in the resolver); the disqualifier moved to the
    # per-modality safety verdict — a rarely-altered oncogene (MCL1, pan-
    # inhibited) keeps small_molecule=hold so exists-safe-modality does NOT
    # clear the WT-loss concern (replaces the retired GROUP-0b guard).
    "pan-cancer-crispr-dependency-distribution",  # (data-util expansion 2026-08-21) — DepMap pan-
    # essentiality as a BROAD-TOX safety signal. dependency_class==
    # common_essential fires pan-essential-broad-tox-safety-warning
    # (safety.resolver 1.5.0) → pan_essential_broad_tox_concern HOLD:
    # a full-KO modality abrogates an essential function in NORMAL
    # tissue too. Same card the dependency skill vetoes as
    # pan_essential_killer (no window); here it is the SAFETY reading.
    # #1794 (safety.resolver 2.4.0): two further arms — common_essential_
    # unanchored (anchor UNREACHABLE, fraction trusted) fires the
    # unanchored twin → the SAME HOLD; broad_dependency_band==
    # partial_broad_band (0.60-0.85) fires the graded broad_dependency_
    # partial_tox_concern caution (never a gate hold).
    # The modality-conditional read (mutant-selective sparing) lives in
    # the per-modality safety verdict, not a scalar-verdict downgrade.
    "normal-tissue-liability",  # (data-util expansion 2026-08-21) — HPA-IHC protein normal-tissue
    # liability. essential_tissue_flag==present fires normal-tissue-
    # protein-liability-safety-warning → normal_tissue_protein_safety_
    # concern HOLD: the intracellular (SM/degrader) reading of the same
    # card surface-modality-fit uses for its BiTE/TCE killer. This is
    # PROTEIN-level critical-organ liability; the GTEx card above is
    # RNA-breadth. No mutant-selective downgrade (full-KO hits WT).
    "sc-normal-celltype-expression",  # (L2b-3, SK#1546, 2026-09-24; scRNA arm repointed SK#1575, 2026-09-25) —
    # scRNA CELL-TYPE-RESOLVED normal-tissue liability (sc_normal_safety_essential_class): the single-cell RNA
    # sibling of the GTEx-bulk + HPA-IHC normal-liability legs. Added ONLY to feed the L2b-3
    # `normal_liability_concordance` cross-source claim (GTEx bulk × scRNA-normal × HPA-IHC). VERDICT-INERT:
    # unlike TPHP (whose rules live on a different axis), this card's tvn-sc-normal-critical-organ-veto rule IS
    # on the intracellular_intrinsic axis, so it DOES enter this skill's fired list — but it is NOT a
    # safety.resolver.yaml rung and NOT in the wt_loss_safety_conditioning modality contract, so the scalar
    # `safety_verdict` AND `safety_verdict_by_modality` both stay byte-stable (test_safety_replay). NOT added to
    # _SAFETY_DECISION_CARDS (coverage unchanged). The concordance claim reads sc_normal_safety_essential_class
    # (ORGAN-AWARE apples-to-apples with the GTEx/HPA arms — SK#1575 fixed the prior organ-agnostic
    # sc_normal_expression_class mismatch); it is a DISPLAY class no interpretation rule keys on (every gate
    # reads sc_normal_essential_veto_grade), so the claim still perturbs no verdict path.
    "drug-warning-safety",  # (2026-08-21) — OT pharmacovigilance CONTEXT: do drugs that ENGAGE
    # the target carry FDA black-box / withdrawn warnings (drug_warning ⋈
    # drug_mechanism_of_action)? VERDICT-INERT (no resolver rung; like
    # target-safety-prioritisation) — a confounded on-target signal that
    # ORIENTS, never HOLDs. Closes the P5 drug_warning placeholder axis.
    "onsides-adverse-event-safety",  # (2026-08-25) — OnSIDES drug-label ADE CONTEXT: per-MedDRA-term
    # adverse-effect profile (incl. boxed-warning severity) of drugs that
    # ENGAGE the target, finer-grained than the drug-warning boolean above.
    # VERDICT-INERT (no resolver rung): the gene attribution is a FUZZY
    # drug-name->gene join (~63% match; DGIdb directional recall-union so
    # drug-level + class-wide — cannot separate on- from off-target) and
    # per-MedDRA-TERM grain only (per-organ/SOC needs a MedDRA license).
    # ORIENTS, never HOLDs. Same posture as drug-warning-safety.
    "normal-tissue-protein-abundance-tphp",  # (T0-3, 2026-09-10; VERDICT-BEARING since #1793) — TPHP
    # DIA-MS QUANTITATIVE vital-organ PROTEIN. The safety skill had RNA (GTEx) + categorical IHC (HPA)
    # but NO quantitative protein; this adds the dose-limiting-organ protein read, resolving the
    # endocrine/vascular/CNS organs HPA-IHC is blind to (nerve/muscle/blood/adrenal/thyroid). #1793
    # (TC rules 1.3.0 / safety.resolver 2.3.0): tphp_hpa_blind_vital_organ_liability_class ==
    # vital_organ_abundant fires tphp-hpa-blind-vital-organ-protein-safety-warning (intracellular_
    # intrinsic axis) → normal_tissue_protein_safety_concern HOLD — the ORGAN-COVERAGE twin of the HPA
    # rung (same verdict token; driving_rule distinguishes the arms). The FULL vital-organ view
    # (tphp_vital_organ_liability_class) stays display context — a full-set rung would double-fire the
    # organs the HPA killer already owns.
]

QUESTION = (
    "Is {target} highly constrained against loss-of-function "
    "variants in the gnomAD population, and what does this imply "
    "for on-target safety of full-KO modalities (degrader, RNA "
    "therapeutic, full-inhibition SM) in {indication}?"
)

PARTIAL_STATUS_NOTE = (
    "on-target-safety-liability now integrates a FIVE-leg human-genetics safety axis, all "
    "verdict-moving via safety.resolver 1.3.0: gnomAD germline LoF-constraint + rare-variant "
    "BURDEN (gene-burden-safety) + ClinGen dosage-sensitivity (clingen-dosage) + mouse-KO "
    "normal-physiology (mouse-ko-phenotype) + ClinVar germline pathogenicity (clinvar-"
    "pathogenicity-safety). The scalar verdict is the HONEST raw WT-loss concern; the mutant-selective "
    "downgrade for an activating driver was RETIRED from the resolver (v2.0.0, 2026-08-24) and now lives "
    "in the per-modality safety verdict (safety_verdict_by_modality), not the scalar. target-safety-"
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


# RETIRED 2026-08-24 (VERDICT_REPRESENTATION.md Layer-2b/3): the resolver no longer emits a scalar
# mutant-selective downgrade — the modality-conditional downgrade moved to the per-modality safety
# verdict (safety_verdict_by_modality) + tp_gates exists-safe-modality logic. Kept as a permanently-
# empty frozenset (not deleted) because skills/tests/test_resolver_verdict_consumers.py (Guard-A,
# fleet-wide) asserts this set == the resolver's *_mechanism_mismatch verdicts == set(), so a future
# downgrade verdict can't silently lose its note. #1799: the consuming branch below (is_mismatch /
# mechanism_conditioning_note / _safety_tension_extra) was dead — this set can never gain a member
# without a resolver change, which would also need a new consuming branch — so it was removed;
# mechanism_conditioning_note is now hardcoded None.
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
    "highly_constrained_safety_concern": "Highly LoF-constrained — safety concern",
    "human_genetics_safety_concern": "Human-genetics safety concern",
    "pan_essential_broad_tox_concern": "Pan-essential — broad-tox safety concern",
    "normal_tissue_protein_safety_concern": "Essential-tissue protein — safety concern",
    # #1794 (safety.resolver 2.4.0): GRADED caution for the 0.60-0.85 strongly-dependent band
    # (broad_dependency_band == partial_broad_band) — a measured PARTIAL broad-tox liability,
    # deliberately weaker than the HOLDs above (12/504 corpus carriers include managed clinical-stage
    # targets) but stronger than every tolerant reassurance rung. A concern (red badge), never a gate.
    "broad_dependency_partial_tox_concern": "Partial broad dependency (0.60–0.85 band) — graded broad-tox caution",
    # tolerant / reduced-risk
    "tolerant_reduced_safety_risk": "LoF-tolerant — reduced safety risk",
    # equivocal mid-band + gaps
    "moderately_constrained_safety": "Moderately LoF-constrained (equivocal)",
    "data_unavailable": "Data unavailable",
    "insufficient": "Insufficient evidence",
}

# Verdict → program-desirability polarity (see the POLARITY note above). Reused by the hero-badge colour;
# never a gate.
_SAFETY_CONCERN_VERDICTS = frozenset(
    {
        "highly_constrained_safety_concern",
        "human_genetics_safety_concern",
        "pan_essential_broad_tox_concern",
        "normal_tissue_protein_safety_concern",
        # #1794: the graded partial broad-dependency caution IS a measured liability (undesirable for a
        # full-KO program → negative badge) even though it is deliberately NOT a nomination-gate hold.
        "broad_dependency_partial_tox_concern",
    }
)
_SAFETY_REASSURING_VERDICTS = frozenset(
    {
        "tolerant_reduced_safety_risk",
    }
)


def _safety_verdict_polarity(v) -> str:
    """The skill's OWN reading of the resolved verdict (colours the hero badge; never a gate). Polarity
    encodes DESIRABILITY for a drug program, not raw signal direction (these are inverse-valence liability
    axes): a LoF-intolerant HOLD is a CONCERN (negative); a tolerant read is reassuring (positive); the
    equivocal mid-band + coverage gaps stay neutral."""
    if v in _SAFETY_CONCERN_VERDICTS:
        return "negative"
    if v in _SAFETY_REASSURING_VERDICTS:
        return "positive"
    return "neutral"


_SAFETY_HEADLINE_SPEC = HeadlineSpec(
    gate="safety",
    axis_labels={
        "CONSTRAINT": "gnomAD LoF constraint",
        "BURDEN": "population gene-burden",
        "DOSAGE": "ClinGen dosage",
        "CLINVAR": "germline pathogenicity",
        "MOUSE_KO": "mouse-KO phenotype",
        "PAN_ESSENTIAL": "DepMap pan-essentiality",
        "NORMAL_TISSUE": "normal-tissue protein (HPA-IHC)",
    },
    axis_keys=("CONSTRAINT", "BURDEN", "DOSAGE", "CLINVAR", "MOUSE_KO", "PAN_ESSENTIAL", "NORMAL_TISSUE"),
    # #1792 whole-axis coverage gating: every safety leg can independently drive a concern HOLD, so ALL
    # 7 legs are decision-critical — a single critical axis made headline_core's thin-coverage floor
    # (`n_crit_measured*2 < len(crit)`) unfireable on any measured-CONSTRAINT gene, letting a clean verdict
    # read `strong` on gnomAD-tolerant alone while BURDEN/DOSAGE/CLINVAR/MOUSE_KO/PAN_ESSENTIAL/
    # NORMAL_TISSUE were entirely unmeasured. With all 7 critical, <4 measured legs caps confidence at
    # `weak` ("capped by thin coverage"). This is the claim-level equivalent of `_safety_certainty`'s
    # card-presence coverage reaching the SURFACED confidence (it previously fed only the dead
    # claim_record_shadow); we deliberately do NOT pass `_safety_certainty` as the `certainty=` sidecar —
    # the sidecar WINS outright in derive_confidence, which would replace the corroboration weakest-link
    # + conflict cap with card-presence-only coverage (confidence INFLATION on a covered-but-conflicted
    # gene, the same dishonesty in the opposite direction).
    critical_axes=("CONSTRAINT", "BURDEN", "DOSAGE", "CLINVAR", "MOUSE_KO", "PAN_ESSENTIAL", "NORMAL_TISSUE"),
    verdict_label=lambda v: _SAFETY_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed safety headline. Reads the resolved
    verdict + the verdict-inert claim_vector / key_signals; never moves the spine. Confidence is derived
    from the claim vector's corroboration, floored by whole-axis coverage over ALL 7 legs (#1792 — the
    CERTAINTY_MODEL sidecar `_safety_certainty` is deliberately NOT passed: sidecar-wins would discard
    the corroboration weakest-link + conflict cap for card-presence-only coverage)."""
    v = headline.get("safety_verdict")
    return build_headline(
        headline,
        headline.get("claim_vector"),
        headline.get("key_signals"),
        spec=_SAFETY_HEADLINE_SPEC,
        verdict_token=v,
        driving_rule_id=headline.get("driving_rule_id"),
        verdict_polarity=_safety_verdict_polarity(v),
    )


# ── FACTORED-RECORD SHADOW (M1) — the SAFETY per-axis builder, and the axis that best exercises the
#    record's `modality_scope` coordinate (VERDICT_REPRESENTATION §8): a WT-loss safety concern is
#    modality-CONDITIONAL, not a scalar. It opposes an engages-WT biologic (degrader/RNA), is only
#    conditional for an allele-selective small molecule, and is n/a on surface modalities. The record
#    carries that per-channel from safety_verdict_by_modality(fired) — the honest replacement for the
#    retired GoF-role-proxy downgrade. VERDICT-INERT: surfaced by the fan-out into
#    decision.claim_record_shadow.safety, consumed by NOTHING. Mirrors the other axes' _claim_record.
_SAFETY_CONCERNS = frozenset(
    {
        "highly_constrained_safety_concern",
        "human_genetics_safety_concern",
        "normal_tissue_protein_safety_concern",
        "pan_essential_broad_tox_concern",
    }
)
_SAFETY_OPEN_WORLD = {"data_unavailable", None}
# the verdict-driving concern instruments — coverage/unknown_mass are computed over these
_SAFETY_DECISION_CARDS = (
    "gnomad-lof-constraint",
    "normal-tissue-liability-gtex",
    "clinvar-pathogenicity-safety",
    "mouse-ko-phenotype",
    "clingen-dosage",
    "gene-burden-safety",
    "pan-cancer-crispr-dependency-distribution",
    "normal-tissue-liability",
)
# safety_verdict_by_modality action -> the record's modality_scope value
_SAFETY_ACTION_TO_SCOPE = {
    "hold": "unfavorable",
    "conditional": "conditional",
    "supportive": "favorable",
    "no_concern": "favorable",
    "not_applicable": "na",
}


def _safety_availability(v) -> str:
    if v in _SAFETY_OPEN_WORLD:
        return "not_wired"  # open-world → assembler forces unknown/neutral
    if v == "insufficient":
        return "insufficient"
    if v == "tolerant_reduced_safety_risk":
        return "measured_negative"  # measured, concern ABSENT (reassuring)
    return "measured_positive"  # a measured safety concern present


def _safety_finding(v):
    """(direction, magnitude.level) for the safety liability finding."""
    if v in _SAFETY_CONCERNS:
        return "opposes", "strong"
    if v == "moderately_constrained_safety":
        return "opposes", "moderate"
    if v == "tolerant_reduced_safety_risk":
        return "supports", "none"  # reduced risk supports nomination
    return "neutral", "none"  # insufficient / open-world


def _safety_certainty(cards) -> dict:
    """Coverage-only certainty (CERTAINTY_MODEL): safety has NO verdict-disjoint corroborator — every
    independent constraint line already drives the verdict — so corroboration is `unmeasured` and
    level == coverage. Coverage/unknown_mass over the concern instruments (_SAFETY_DECISION_CARDS)."""
    present = sum(
        1
        for cid in _SAFETY_DECISION_CARDS
        if (card_summary(cards, cid) and not card_summary(cards, cid).get("_missing"))
    )
    frac = present / len(_SAFETY_DECISION_CARDS)
    coverage = "high" if frac >= 0.66 else ("medium" if frac >= 0.33 else "low")
    return {
        "level": coverage,
        "coverage": coverage,
        "corroboration": "unmeasured",
        "unknown_mass": round(1.0 - frac, 4),
    }


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
    bio = scope("rna") or scope("degrader")  # the engages-WT biologic represents the base
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


def _pharmacovigilance_scope_caveat(hl: dict) -> str | None:
    """VERDICT-INERT scope clarifier for the PHARMACOVIGILANCE context axis. drug_warning_class ==
    'no_warning' means target-engaging drugs were assessed but NONE carry an OT-registered FDA warning
    (black-box / withdrawn / other) — it does NOT establish absence of on-target toxicity. Mechanism-based,
    dose-limiting clinical liabilities (tumor-lysis syndrome, cytopenias, peripheral neuropathy) are common
    for approved on-target agents yet are frequently NOT boxed warnings, so they lie outside this axis's
    coarse OT drug-warning + OnSIDES-boxed scope. Fires ONLY on the measured-negative 'no_warning' state
    (engaging drugs assessed); None for no_targeted_drug (coverage gap), any warned class, insufficient, or
    absent → byte-stable. Never enters the resolver (the safety verdict is already independent of this
    context axis). Surfaced by the literature↔deterministic discordance loop (eval/CASE_LOG.md CASE-009)."""
    if hl.get("drug_warning_class") != "no_warning":
        return None
    return (
        "PHARMACOVIGILANCE SCOPE: drug_warning_class='no_warning' means target-engaging drugs were "
        "assessed and none carry an OT-registered FDA warning (black-box / withdrawn / other) — it does "
        "NOT establish absence of on-target toxicity. Mechanism-based, dose-limiting clinical "
        "liabilities (e.g. tumor-lysis syndrome, cytopenias, peripheral neuropathy) are common for "
        "approved on-target agents yet are frequently not boxed warnings, so they fall outside this "
        "axis's coarse OT drug-warning + OnSIDES-boxed scope. This axis ORIENTS, never HOLDs — consult "
        "toxicity_classes / OnSIDES ADE terms and the literature lane (--literature) for the full "
        "on-target adverse-effect profile."
    )


def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    # alteration-role mechanism context (GoF/LoF direction) — surfaced below as
    # alteration_functional_direction. The scalar mutant-selective mismatch DOWNGRADE this fed was
    # RETIRED 2026-08-24 (see _MECHANISM_MISMATCH_VERDICTS above); functional_direction now only
    # feeds the per-modality safety verdict + claim_vector, never a scalar note.
    functional_direction = get_card_field(cards, "alteration-role", "functional_direction")

    # TPHP card summary via the graceful lookup (#1793): the card is OPTIONAL (applies_when gates on
    # tphp_normal_proteome_available), so a missing card must degrade every read to None, never abort
    # the safety spine. The local single-arg helper (not a bare card_summary call) is deliberate: it is
    # the census-visible alias idiom (_skills_common.field_disposition._card_aliases), so each
    # tphp.get("<field>") below earns an EXACT skill_code reader credit — a `_cf` read is invisible to
    # the aperture instrument and would leave the new #1793 fields counted declared-but-unread.
    def _summary(cid):
        return card_summary(cards, cid)

    tphp = _summary("normal-tissue-protein-abundance-tphp")
    hl = {
        "safety_verdict": v,
        "driving_rule_id": drv,
        "constraint_class": get_card_field(cards, "gnomad-lof-constraint", "constraint_class"),
        "pli_score": get_card_field(cards, "gnomad-lof-constraint", "pli_score"),
        "loeuf_score": get_card_field(cards, "gnomad-lof-constraint", "loeuf_score"),
        "mis_z_score": get_card_field(cards, "gnomad-lof-constraint", "mis_z_score"),
        "syn_z_score": get_card_field(cards, "gnomad-lof-constraint", "syn_z_score"),
        "obs_lof_count": get_card_field(cards, "gnomad-lof-constraint", "obs_lof_count"),
        "exp_lof_count": get_card_field(cards, "gnomad-lof-constraint", "exp_lof_count"),
        # Continuous dominant-LoF selection (GeneBayes s_het, 2026-08-28) — the continuous complement to
        # the binary constraint_class; catches dosage-sensitive small genes pLI/LOEUF miss. VERDICT-INERT
        # (fires no rule); surfaced for LLM/reviewer as corroboration of the constraint call.
        "shet_class": get_card_field(cards, "shet-lof-intolerance", "shet_class"),
        "shet_score": get_card_field(cards, "shet-lof-intolerance", "shet_score"),
        "shet_lower_95": get_card_field(cards, "shet-lof-intolerance", "shet_lower_95"),
        "shet_upper_95": get_card_field(cards, "shet-lof-intolerance", "shet_upper_95"),
        # Human OBSERVED-KO (2026-08-07) — the DIRECT-observation complement to
        # constraint: obs_hom_lof counts healthy humans HOMOZYGOUS for a predicted-LoF variant
        # (natural knockouts). natural_ko_observed = full loss tolerated in the population →
        # strong on-target safety reassurance for a full-KO modality (degrader/RNA), where
        # pLI/LOEUF only INFER intolerance. Additive/verdict-inert; surfaced for LLM/reviewer.
        "human_ko_observed_class": get_card_field(cards, "gnomad-lof-constraint", "human_ko_observed_class"),
        "obs_hom_lof_count": get_card_field(cards, "gnomad-lof-constraint", "obs_hom_lof_count"),
        # human-genetics rare-variant burden (verdict-moving)
        "burden_safety_class": get_card_field(cards, "gene-burden-safety", "burden_safety_class"),
        "burden_min_pvalue": get_card_field(cards, "gene-burden-safety", "min_pvalue"),
        "burden_top_disease": get_card_field(cards, "gene-burden-safety", "top_disease"),
        # ClinGen dosage sensitivity (verdict-moving)
        "dosage_sensitivity_class": get_card_field(cards, "clingen-dosage", "dosage_sensitivity_class"),
        "dosage_top_disease": get_card_field(cards, "clingen-dosage", "top_disease"),
        # Germline INHERITANCE MODE (2026-08-06) — the in-hand OMIM-style KO-safety facet: recessive_only
        # = het carriers healthy → full-KO REASSURANCE the dominant-focused dosage class understates.
        # Additive/verdict-inert; surfaced for the LLM/reviewer beside the dosage call.
        "germline_inheritance_mode": get_card_field(cards, "clingen-dosage", "germline_inheritance_mode"),
        # mouse-KO normal-physiology (verdict-moving)
        "mouse_ko_phenotype_class": get_card_field(cards, "mouse-ko-phenotype", "ko_phenotype_class"),
        "mouse_ko_top_lethal": get_card_field(cards, "mouse-ko-phenotype", "top_lethal_label"),
        # affected ORGAN SYSTEMS on knockout (2026-09-04 signal-surfacing) — the rich mouse-KO sub-field the
        # capsule projection ignored (class + top_lethal only). Folded into the MOUSE_KO claim evidence so
        # the narrator names WHICH organ systems a full KO perturbs. VERDICT-INERT.
        "mouse_ko_organ_systems": get_card_field(cards, "mouse-ko-phenotype", "organ_classes"),
        # IMPC preweaning-viability screen (2026-09-10, #1001) — the fine-grained viability read
        # (lethal_preweaning / subviable / viable / unmeasured) the coarse ko_phenotype_class collapses:
        # a constitutive embryonic-lethal maps to developmental_only OR is ABSENT from IMPC
        # (-> no_phenotype / insufficient), so the highest-WT-loss-liability genes read as a coverage GAP.
        # Surfaced into the MOUSE_KO claim so the gap is not mistaken for "no phenotype". VERDICT-INERT.
        "impc_viability_class": get_card_field(cards, "mouse-ko-phenotype", "impc_viability_class"),
        # Finer lethality/organ-system bins beneath the coarse ko_phenotype_class (2026-09-27, #1893
        # orphan-aperture wire) — the complementary granularity behind the read fraction: adult vs
        # developmental lethal-row COUNTS + the distinct lethal STAGES that drive top_lethal_label, and
        # the IMPC top-level organ systems (the IMPC-direct twin of the OT-MGI organ_classes above).
        # Folded into the MOUSE_KO claim evidence so the narrator can name WHICH lethal stage/system a full
        # KO perturbs beside the bare class. VERDICT-INERT (no warning_predicate keys on these; sig unchanged).
        "mouse_ko_n_adult_lethal": get_card_field(cards, "mouse-ko-phenotype", "n_adult_lethal"),
        "mouse_ko_n_developmental_lethal": get_card_field(cards, "mouse-ko-phenotype", "n_developmental_lethal"),
        "mouse_ko_lethal_stages": get_card_field(cards, "mouse-ko-phenotype", "lethal_stages"),
        "mouse_ko_impc_top_level_systems": get_card_field(cards, "mouse-ko-phenotype", "impc_top_level_systems"),
        # ClinVar germline-pathogenicity
        "clinvar_pathogenic_class": get_card_field(cards, "clinvar-pathogenicity-safety", "clinvar_pathogenic_class"),
        "clinvar_top_disease": get_card_field(cards, "clinvar-pathogenicity-safety", "top_disease"),
        # confident germline-pathogenic variant COUNT (2026-09-04 signal-surfacing) — the rich ClinVar
        # sub-field the capsule projection ignored (class + top_disease only). Folded into the CLINVAR claim
        # evidence so the narrator can say "N confident germline-pathogenic variants". VERDICT-INERT.
        "clinvar_n_pathogenic_germline_confident": get_card_field(
            cards, "clinvar-pathogenicity-safety", "n_pathogenic_germline_confident"
        ),
        # DepMap pan-essentiality — BROAD-TOX safety leg (verdict-moving via pan-essential-broad-tox-
        # safety-warning). common_essential = required across the whole panel → normal-tissue tox for
        # a full-KO modality (the SAFETY reading of the same signal the dependency skill vetoes).
        "dependency_class": get_card_field(cards, "pan-cancer-crispr-dependency-distribution", "dependency_class"),
        "pan_essential_score": get_card_field(
            cards, "pan-cancer-crispr-dependency-distribution", "pan_essential_score"
        ),
        # ★ #1794 (VERDICT-BEARING, TC safety.resolver 2.4.0 / card 3.1.0): SAFETY grading of the
        # strongly-dependent fraction, orthogonal to dependency_class. partial_broad_band (0.60–0.85)
        # fires broad-dependency-partial-tox-safety-warning → the GRADED broad_dependency_partial_tox_
        # concern (a caution ABOVE every tolerant reassurance rung, BELOW the HOLDs — previously this
        # band read CLEAN and even co-corroborated the TC#895 tolerant reassurance). The sibling
        # dependency_class value common_essential_unanchored (well-powered >=85% fraction, curated
        # anchor UNREACHABLE) fires pan-essential-unanchored-broad-tox-safety-warning → the SAME
        # pan_essential_broad_tox_concern HOLD as the curated arm (unverified ≠ refuted; driving_rule
        # keeps the arms distinct). None-stable: reads None on packages emitted before
        # analysis-methods depmap_chronos_distribution 0.3.0 (507439fc).
        "broad_dependency_band": get_card_field(
            cards, "pan-cancer-crispr-dependency-distribution", "broad_dependency_band"
        ),
        # HPA-IHC protein normal-tissue liability — verdict-moving via normal-tissue-protein-liability-
        # safety-warning (essential_tissue_flag==present → essential-tissue on-target-off-tumor tox).
        "essential_tissue_flag": get_card_field(cards, "normal-tissue-liability", "essential_tissue_flag"),
        "essential_tissues_flagged": get_card_field(cards, "normal-tissue-liability", "essential_tissues_flagged"),
        "normal_tissue_breadth_class": get_card_field(cards, "normal-tissue-liability", "normal_tissue_breadth_class"),
        # TPHP DIA-MS QUANTITATIVE vital-organ PROTEIN (T0-3) — display CONTEXT for the full vital-organ
        # view. Orthogonal to HPA-IHC: resolves the endocrine/vascular/CNS organs HPA is blind to
        # (nerve/muscle/blood/adrenal/thyroid). Read defensively via the `tphp` graceful summary — the
        # card is absent for a target with no TPHP coverage.
        "tphp_vital_organ_liability_class": tphp.get("tphp_vital_organ_liability_class"),
        "n_vital_organs_above_abundance_floor": tphp.get("n_vital_organs_above_abundance_floor"),
        "tphp_vital_organ_abundance": tphp.get("tphp_vital_organ_abundance"),
        # ★ HPA-BLIND vital-organ view (#1793) — VERDICT-BEARING as of TC safety.resolver 2.3.0: the
        # vital-organ read SCOPED to the organs the HPA-IHC essential-tissue killer structurally cannot
        # represent (nerve / blood / adrenal_gland / thyroid / pituitary — HPA's closed 16-name
        # vocabulary has no name for them). tphp_hpa_blind_vital_organ_liability_class ==
        # vital_organ_abundant fires tphp-hpa-blind-vital-organ-protein-safety-warning
        # (intracellular_intrinsic axis) → resolver rung → normal_tissue_protein_safety_concern HOLD —
        # the ORGAN-COVERAGE twin of the HPA rung, same verdict token, distinguishable by driving_rule.
        # The companion fields let the narrator NAME the implicated organs and surface the explicit
        # coverage GAP (pituitary today is covered by NO verdict-bearing protein arm; the whole blind
        # set when the gene is data_unavailable) — never silent absence. None-stable: all four read
        # None on packages frozen before analysis-methods tphp_normal_protein 0.5.0 (ae94fb3e).
        "tphp_hpa_blind_vital_organ_liability_class": tphp.get("tphp_hpa_blind_vital_organ_liability_class"),
        "n_hpa_blind_vital_organs_above_abundance_floor": tphp.get("n_hpa_blind_vital_organs_above_abundance_floor"),
        "hpa_blind_vital_organs_above_floor": tphp.get("hpa_blind_vital_organs_above_floor"),
        "hpa_blind_vital_organs_uncovered": tphp.get("hpa_blind_vital_organs_uncovered"),
        # OT pharmacovigilance CONTEXT (verdict-inert): do drugs engaging the target carry black-box /
        # withdrawn warnings? Orients the reader; no resolver rung reads these.
        "drug_warning_class": get_card_field(cards, "drug-warning-safety", "drug_warning_class"),
        "drug_warning_has_black_box": get_card_field(cards, "drug-warning-safety", "has_black_box"),
        "drug_warning_toxicity_classes": get_card_field(cards, "drug-warning-safety", "toxicity_classes"),
        # OnSIDES drug-label ADE CONTEXT (verdict-inert): per-MedDRA-term adverse-effect profile (incl.
        # boxed-warning severity) of drugs engaging the target — fuzzy drug-name->gene join, per-term
        # grain. Orients the reader; no resolver rung reads these.
        "onsides_ade_class": get_card_field(cards, "onsides-adverse-event-safety", "onsides_ade_class"),
        "onsides_has_boxed_warning": get_card_field(cards, "onsides-adverse-event-safety", "has_boxed_warning"),
        "onsides_example_boxed_warning_terms": get_card_field(
            cards, "onsides-adverse-event-safety", "example_boxed_warning_terms"
        ),
        # mutant-selective conditioning (2026-07-23). mechanism_conditioning_note's scalar-downgrade
        # trigger was RETIRED 2026-08-24 (_MECHANISM_MISMATCH_VERDICTS is permanently empty) — the note
        # can never fire, so it is hardcoded None rather than computed. Kept as a field (not deleted)
        # for output shape stability; consumers (_safety_tension_extra, tests) that read it as the
        # downgrade signal were removed alongside it.
        "alteration_functional_direction": functional_direction,
        "mechanism_conditioning_note": None,
    }
    # verdict-INERT claim-vector projection (5th concrete over claim_vector_core) — the SIGNAL
    # decomposition + citable liability atoms the composed target-profile fan-out surfaces to the
    # cross-evidence agent via _synthesis_facet. Never feeds the safety verdict.
    hl["claim_vector"] = safety_claim_vector(hl, cards)
    hl["key_signals"] = safety_key_signals(hl, cards)
    # VERDICT-INERT scope clarifier (CASE-009): 'no_warning' = no OT-registered FDA warning among engaging
    # drugs, NOT absence of on-target toxicity (mechanism-based dose-limiting tox — TLS, cytopenias,
    # neuropathy — is often not a boxed warning). Fires only on the measured-negative no_warning state;
    # None otherwise → byte-stable. Never feeds the resolver (pharmacovigilance is verdict-inert context).
    hl["pharmacovigilance_scope_caveat"] = _pharmacovigilance_scope_caveat(hl)
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
        hl["narrative"] = build_narrative(axis="safety", gate="safety", fired=fired, verdict=v, driving_rule_id=drv)
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
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the ONE cross-skill output shape, assembled
    # from the verdict + claim_vector + headline_block + question_table just built. safety is a GATING
    # skill (∈ target-profile _SHORT_TO_GATE). First adopter of the contract. Best-effort + verdict-INERT.
    try:
        # Provenance from the REAL resolved-card state (not the static declared CARDS list): a card that
        # resolved absent carries `_missing` (dispatcher scaffolds {card_id, _missing:True}). Splitting
        # used vs missing makes the report's coverage auditable — and lets a consumer tell an `unmeasured`
        # chip whose card is ABSENT from one whose card ran-but-indeterminate.
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        hl["skill_report"] = build_skill_report(
            role=ROLE_GATING,
            verdict=hl.get("safety_verdict"),
            driving_rule_id=hl.get("driving_rule_id"),
            headline_block=hl.get("headline_block"),
            claim_vector=hl.get("claim_vector"),
            question_table=hl.get("question_table"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
            # FOR-WHAT projection onto the spine (the SAME dict the claim_record_shadow carries), so
            # target_report.modality_fit rolls up the per-channel WT-loss safety FROM the report.
            modality_scope=_safety_modality_scope(fired or []),
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        hl["skill_report"] = None
    return hl


# ── OPTIONAL cross-modal synthesis facet (lifts the claim_vector to the composed target-profile) ────
_SYNTHESIS_FACET_KEYS = (
    "safety_verdict",
    "driving_rule_id",
    "constraint_class",
    "burden_safety_class",
    "dosage_sensitivity_class",
    "clinvar_pathogenic_class",
    "clinvar_n_pathogenic_germline_confident",
    "mouse_ko_phenotype_class",
    "mouse_ko_organ_systems",
    "dependency_class",
    "pan_essential_score",
    # ★ #1794 — VERDICT-BEARING band (partial_broad_band → graded broad_dependency_partial_tox_concern;
    # the composed synthesis must see WHICH regime the strongly-dependent fraction sits in). None on
    # pre-0.3.0 packages (omitted → byte-stable).
    "broad_dependency_band",
    "essential_tissue_flag",
    "normal_tissue_breadth_class",
    # TPHP DIA-MS quantitative vital-organ protein (T0-3) — display context for the full vital-organ
    # view (fills the endocrine/vascular/CNS organs HPA-IHC is blind to).
    "tphp_vital_organ_liability_class",
    "n_vital_organs_above_abundance_floor",
    # ★ HPA-BLIND vital-organ view (#1793) — VERDICT-BEARING (TC safety.resolver 2.3.0 rung →
    # normal_tissue_protein_safety_concern). The class + the named organs + the explicit coverage gap,
    # so the composed synthesis can NAME the implicated/uncovered organs. None on pre-0.5.0 packages.
    "tphp_hpa_blind_vital_organ_liability_class",
    "hpa_blind_vital_organs_above_floor",
    "hpa_blind_vital_organs_uncovered",
    "drug_warning_class",
    "drug_warning_has_black_box",
    "drug_warning_toxicity_classes",
    # OnSIDES drug-label ADE class (#1577 item 2, verdict-INERT) — the card's PRIMARY class was read
    # into the headline (above) but stranded from every downstream consumer, incl. this synthesis
    # facet. Surfaces the pharmacovigilance ADE signal to the composed target-profile fan-out.
    "onsides_ade_class",
    # CASE-009: scope clarifier — 'no_warning' ≠ no on-target toxicity (verdict-INERT)
    "pharmacovigilance_scope_caveat",
    "human_ko_observed_class",
    "germline_inheritance_mode",
    "alteration_functional_direction",
    "claim_vector",
    "key_signals",
    # the per-question (data·signal·confidence) rows — rendered as the leading table by target-profile too
    "question_table",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
    # the per-verdict narrative (movers / dissenters / flip_conditions / rule_sentences) — the citeable
    # substrate the composed "why this verdict" panel + Tier-3 synthesis consume (Stage C wires those)
    "narrative",
    # the UNIFIED cross-skill output object (docs/UNIFIED_OUTPUT_CONTRACT.md) — safety is the first adopter
    "skill_report",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT safety facet for the composed target-profile synthesis. Reuses _headline
    (single source of truth) and returns the reconciliation-relevant subset, incl. the liability
    claim_vector + its citable atoms. Never moves the verdict; safe to omit."""
    h = _headline(cards, fired, verdict_pair)
    return build_synthesis_facet(
        h,
        _SYNTHESIS_FACET_KEYS,
        (
            "Deterministic on-target-safety facet. claim_vector is an INVERSE-valence LIABILITY decomposition "
            "(CONSTRAINT / BURDEN / DOSAGE / CLINVAR / MOUSE_KO) — a strong signal is a safety CONCERN, not a "
            "win; the scalar safety VERDICT is owned by the safety resolver, not this projection. The mutant-"
            "selective-GoF WT-loss downgrade is MODALITY-CONDITIONAL (realised in the per-modality safety "
            "verdict, safety_verdict_by_modality), NOT applied to the scalar verdict."
        ),
    )


# ─── EXPORTED bounded evidence-package sections (PR-1a, epic #2210 Wave 1 / #1507) ───────────────────
# The safety generalisation of the tumour-presence reference vertical
# (`skills/tumor-presence/scripts/run.py::_evidence_sections`). Under `--emit-envelope` the emitted
# evidence_package.json gains NAMED top-level sections so the L1→L2a→L2b layering is STRUCTURE rather
# than a convention over `synthesis.headline.claim_vector`. The schema
# (`contracts/schemas/evidence_package.schema.json`) ALREADY declares all four as optional — no schema
# change, and a section this domain does not produce is simply OMITTED.
#
# The L2b property island promoted to a shared top-level section. ONE for safety today —
# `normal_liability_concordance` (GTEx bulk × scRNA-normal × HPA-IHC, SK#1546), which reconstructs to L1
# through `provenance.sources[*].provenance.card_id`. Deliberately a ROSTER, not "everything without a
# `signal` key": a future L2b fold must be listed here consciously, exactly as the presence roster works.
_INTEGRATED_ISLAND_KEYS = ("normal_liability_concordance",)

# The composites that stay INSIDE the domain with their epistemic type declared — the eight liability
# claim axes. NOT promoted to shared L2 properties: each is this skill's own (signal × corroboration)
# read of one source, in the domain's INVERSE-valence frame, and each reconstructs to L1 via
# `evidence_atom.cite.card_id`. Pinned to the ClaimSpec roster below so an axis added to
# SAFETY_CLAIM_SPEC cannot silently go unexported.
_LOCAL_COMPOSITE_KEYS = tuple(spec.axis_key for spec in SAFETY_CLAIM_SPEC)


def _evidence_sections(headline: dict) -> "dict | None":
    """Build the NAMED, bounded top-level evidence-package sections from the rich decision headline.

    Pure read-projection over the already-built `headline`: partitions content it ALREADY carries into the
    doc's named sections (`source_properties` L2a, `integrated_properties` L2b, `local_composites`).
    Nothing is recomputed and nothing is dropped that a consumer could not already read on the headline.
    Every emitted section reconstructs downward to L1:
      * source_properties[*].card_id (+ per-anchor {field, value} → the L1 card field)
      * integrated_properties[*].provenance.sources[*].card_id (or .provenance.card_id — the island's
        sources carry it at either depth, and a consumer reads both)
      * local_composites.claims.<AXIS>.evidence_atom.cite.card_id
    `l3d` is NOT emitted: safety has no within-domain L3d story object (the presence vertical's
    `tumor_expression_biology_story` has no safety counterpart), and an empty section is worse than an
    absent one — so this domain emits THREE of the schema's four optional sections. Returns None when no
    claim_vector resolved, so the dispatcher passes `evidence_sections=None` and the emitted package is
    byte-identical to the pre-PR-1a shape. VERDICT-INERT throughout."""
    if not isinstance(headline, dict):
        return None
    cv = headline.get("claim_vector")
    if not isinstance(cv, dict):
        return None

    sections: dict = {}

    # L2a — per-source observational biological properties (each entry carries its L1 card_id).
    sp = cv.get("source_properties")
    if sp:
        sections["source_properties"] = sp

    # L2b — the property islands (reconstructable to card_ids via provenance.sources[*].provenance.card_id).
    integrated = {k: cv[k] for k in _INTEGRATED_ISLAND_KEYS if cv.get(k) is not None}
    if integrated:
        sections["integrated_properties"] = integrated

    # Local composites — carried inside the domain with the epistemic type declared.
    carried = {k: cv[k] for k in _LOCAL_COMPOSITE_KEYS if cv.get(k) is not None}
    if carried:
        sections["local_composites"] = {"epistemic_type": "domain_local_composite", "claims": carried}

    return sections or None


if __name__ == "__main__":
    sys.exit(
        run_wired_skill(
            skill_name=SKILL_NAME,
            skill_version=SKILL_VERSION,
            cards=CARDS,
            axis="intracellular_intrinsic",
            question=QUESTION,
            verdict_fn=_verdict,
            headline_fn=_headline,
            # Skill-level graphics (opt-in --figures): the canonical headline hero. Additive / display-only.
            skill_figures_fn=emit_headline_hero,
            partial_status_note=PARTIAL_STATUS_NOTE,
            # Signals-first: tuned sub-group reader for the safety-LIABILITY vocabulary (note the polarity
            # inversion vs the dependency lens). Verdict-INERT.
            subgroup_classify=make_value_classifier(_SAFETY_VALUE_TIERS),
            # NET-NEW single-lens narrator (this skill had none → --synthesize was a no-op). Generic
            # capsule-driven engine + the safety LensConfig (LIABILITY polarity). Two-slot / verdict-inert.
            synthesize_fn=make_synthesize_fn(_SAFETY_LENS),
            # OPT-IN (--literature) verdict-INERT literature lane (Europe-PMC-grounded + PMID-verified). One-liner
            # because run_wired_skill owns the seam (dispatcher 8a-iii); NEVER alters the spine (byte-identical
            # without the flag). Routes each safety literature axis back to this skill (it OWNS the WT-loss call).
            literature_fn=make_literature_fn(_SAFETY_LENS, retrieve_fn=default_retrieve, verify_fn=verify_citations),
            # PR-1a (#2210): under --emit-envelope, splice the NAMED bounded evidence-package sections
            # (source_properties L2a / integrated_properties L2b / local_composites) in as top-level keys
            # of evidence_package.json — a VIEW over the same headline content, each reconstructable
            # downward to its claim IDs / L1 card_ids. Verdict-INERT (decision.json spine untouched).
            evidence_sections_fn=_evidence_sections,
        )
    )
