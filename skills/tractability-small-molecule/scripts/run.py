#!/usr/bin/env python3
"""tractability-small-molecule — chemical-genetic + structural small-molecule druggability.

Consumes the 3 chemical-genetic cards (prism-compound-activity — the CHEMICAL arm
of the dependency question, i.e. "does a compound perturb the target"; plus
prism-crispr-concordance, dependency-predictability) AND the structure-features-static
card (FORWARD ligandability) + the prism-* / predictability-* / E7 / E8 rule subsets.
Emits a data-package output tree with a rank-ordered small-molecule druggability snapshot.

SPLIT 2026-07-14: this is the small-molecule half of the former
`tractability-and-modality` skill. That skill had grown to 9 cards, but 6 of
them (surface topology / family / structure / density / adc-tce-fit / cohort-
ranking) could NOT change its verdict — the `_snapshot()` keyed entirely off
the 3 chemical-genetic rules. The surface cards were split out into the
sibling `surface-modality-fit` skill. See docs/SKILLS_SCOPE_REVIEW_2026-07-14.md.

E8 structure/ligandability (2026-07-17, gate-scaffold backtest follow-up): the
PRISM cards are RETROSPECTIVE — they credit only targets a compound has ALREADY
hit, so a structurally-druggable-but-not-yet-drugged target (the KRAS-G12C
switch-II pocket pre-sotorasib) read as `chemically_unhit`/`insufficient`. Added
structure-features-static + the intracellular E8 rules so a druggable pocket now
raises a FORWARD `structurally_ligandable` snapshot (ranked below a real chemical
hit, above chemically_unhit). structure-features-static is ALSO consumed by
surface-modality-fit on the surface axis — its surface rules stay there; the E8
rules here are small_molecule-scoped (rule_id suffix -e8).

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field
from _skills_common.tractability_claims import small_molecule_claim_vector, small_molecule_key_signals
from _skills_common.tractability_sm_question_table import tractability_sm_question_table
from _skills_common.resolver import resolve_or_raise
from _skills_common.claim_record import assemble_claim_record
from _skills_common.synthesis_tractability_sm import synthesize_tractability_sm
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.headline_hero import emit_headline_hero


def _emit_skill_figures(decision, figures_root):
    """Skill-level graphics (opt-in --figures): the canonical headline hero (verdict · confidence · top
    tension). Additive / display-only, offline, best-effort — mirrors tumor-presence."""
    return emit_headline_hero(decision, figures_root)


# ── canonical HEADLINE block (verdict + confidence + top tension) ─────────────────────────────────
# The tractability-small-molecule declaration for the shared headline_core builder: the 5 POSITIVE-valence
# claim axes (POTENCY / ACTIVITY / STRUCT / DRUG / DEGRADER), the druggability_snapshot vocabulary → human
# phrase, and the chemical↔genetic DISCORDANCE as the skill-specific tension source. Verdict-INERT — a
# one-way projection over the computed headline (druggability_snapshot spine byte-stable).
# The druggability_snapshot vocabulary (the resolver rungs) → human phrase. Positives are the tractable
# rungs; negatives are the intractable / off-target rungs; `insufficient` is the coverage gap.
_DRUGGABILITY_VERDICT_PHRASE = {
    # positives — a druggable / tractable call
    "well_covered":                 "Well-covered small-molecule target",
    "chemically_confirmed_genetic": "Chemically confirmed genetic dependency",
    "chemically_active":            "Chemically active compound",
    "measured_potent_ligand":       "Measured potent ligand",
    "clinical_precedent_only":      "Clinical precedent only",
    "tool_compound_only":           "Tool compound only",
    "weakly_active":                "Weakly active compound",
    "structurally_ligandable":      "Structurally ligandable pocket",
    # negatives — an intractable / undruggable / off-target call
    "structurally_intractable":     "Structurally intractable",
    "chemically_unhit":             "Chemically unhit (no compound found)",
    "discordant":                   "Discordant off-target activity",
    # gap
    "insufficient":                 "Insufficient evidence",
}

# Positive (tractable) vs negative (intractable / off-target) druggability rungs — used only to colour
# the hero badge polarity; never a gate. Kept in sync with the resolver rung vocabulary.
_TRACTABILITY_POSITIVE = frozenset({
    "well_covered", "chemically_confirmed_genetic", "chemically_active", "measured_potent_ligand",
    "clinical_precedent_only", "tool_compound_only", "weakly_active", "structurally_ligandable",
})
_TRACTABILITY_NEGATIVE = frozenset({"structurally_intractable", "chemically_unhit", "discordant"})


def _tractability_verdict_polarity(v) -> str:
    """The skill's OWN reading of the druggability_snapshot (colours the hero badge; never a gate)."""
    if v in _TRACTABILITY_POSITIVE:
        return "positive"
    if v in _TRACTABILITY_NEGATIVE:
        return "negative"
    return "neutral"


# ── FACTORED-RECORD SHADOW (M1) — the TRACTABILITY (small-molecule) per-axis builder. This axis is
#    SM-SPECIFIC, so modality_scope.small_molecule is the meaningful coordinate (favorable when
#    druggable, unfavorable when intractable; biologics='na' — tractability_sm does not speak to
#    biologics). tractability has NO verdict-disjoint corroborator (rated `unmeasured`), so certainty is
#    a minimal coverage-only object. VERDICT-INERT: surfaced by the fan-out into
#    decision.claim_record_shadow.tractability_small_molecule, consumed by NOTHING.
_TRACT_STRONG = {"well_covered", "chemically_confirmed_genetic", "measured_potent_ligand"}
_TRACT_MOD = {"chemically_active", "structurally_ligandable", "clinical_precedent_only"}
_TRACT_WEAK = {"tool_compound_only", "weakly_active"}


def _tract_availability(v) -> str:
    if v is None:
        return "not_wired"                       # open-world → assembler forces unknown/neutral
    if v == "insufficient":
        return "insufficient"                    # the coverage gap (measured underpowered)
    if v in _TRACTABILITY_NEGATIVE:
        return "measured_negative"               # measured intractable / unhit / discordant
    return "measured_positive"


def _tract_direction(v) -> str:
    if v in _TRACTABILITY_POSITIVE:
        return "supports"
    if v in _TRACTABILITY_NEGATIVE:
        return "opposes"
    return "neutral"


def _tract_level(v) -> str:
    if v in _TRACT_STRONG:
        return "strong"
    if v in _TRACT_MOD or v in _TRACTABILITY_NEGATIVE:
        return "moderate"
    if v in _TRACT_WEAK:
        return "weak"
    return "none"


# degrader-feasibility class (_degrader_snapshot) -> the record's _refinements.degrader favorability.
# The degrader channel is a MEASURED, degrader-channel-only fired-rule read (NOT the fabricating
# alteration-class inference #2 rejected): a degrader models COMPLETE removal, so an SM-intractable
# target can still be a degrader prospect (BRD4 scaffolding, STAT3 TF). Without this, the consumer's
# degrader channel silently INHERITED the SM base favorability (_CHANNEL_BASE['degrader']=small_molecule)
# -- parroting the SM call for a channel with its own evidence. insufficient -> omit (keep SM fallback).
_DEGRADER_CLASS_TO_SCOPE = {
    "strong_degrader_rationale": "favorable", "degrader_rationale": "favorable",
    "degrader_opposed": "conditional",        # a degrader-opposing signal fired -- downgrade, not a kill
    "degrader_unviable": "unfavorable",        # a degrader-killer fired (nothing to degrade)
}


def _tract_modality_scope(v, fired=None) -> dict | None:
    scope = None
    if v in _TRACTABILITY_POSITIVE:
        scope = {"small_molecule": "favorable", "biologics": "na"}
    elif v in _TRACTABILITY_NEGATIVE:
        scope = {"small_molecule": "unfavorable", "biologics": "na"}
    # degrader channel: lift the measured _degrader_snapshot class onto _refinements.degrader so the
    # per-modality view reflects the ACTUAL degrader-feasibility read, not SM inheritance.
    if fired is not None:
        try:
            deg_class, _drv = _degrader_snapshot(fired)          # reads fired[].signals[degrader]
        except Exception:  # noqa: BLE001 -- shadow must never crash the run (fired may lack signals)
            deg_class = "insufficient"
        deg = _DEGRADER_CLASS_TO_SCOPE.get(deg_class)
        if deg is not None:
            scope = dict(scope or {"small_molecule": "na", "biologics": "na"})
            scope["_refinements"] = {"degrader": deg}
    return scope                                 # None only when no SM call AND degrader insufficient


def _tract_certainty(v) -> dict:
    """Minimal coverage-only certainty — tractability has no verdict-disjoint corroborator
    (CERTAINTY_MODEL: `unmeasured`). level == coverage; unknown_mass reflects open-world/underpowered."""
    if v is None:
        return {"level": "low", "coverage": "low", "corroboration": "unmeasured", "unknown_mass": 1.0}
    if v == "insufficient":
        return {"level": "low", "coverage": "low", "corroboration": "unmeasured", "unknown_mass": 0.5}
    return {"level": "medium", "coverage": "medium", "corroboration": "unmeasured", "unknown_mass": 0.0}


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — standalone, mirrors the other axes' hook."""
    v = verdict_pair[0] if verdict_pair else (_snapshot(fired)[0] if fired is not None else None)
    return assemble_claim_record(
        axis="tractability_small_molecule",
        state=(v or "insufficient"),
        direction=_tract_direction(v),
        availability=_tract_availability(v),
        magnitude={"level": _tract_level(v)},
        modality_scope=_tract_modality_scope(v, fired=fired),
        certainty=_tract_certainty(v),
        fired=fired,
        cards=cards,
    )


def _tractability_tension_extra(headline: dict):
    """The sharpest small-molecule tractability caveat: a chemical↔genetic DISCORDANT read — an active
    compound whose cell-kill does NOT track the CRISPR/RNAi genetic dependency (off-target), which argues
    AGAINST small-molecule tractability. Surfaced from the `discordant` verdict + the concordance class."""
    if headline.get("druggability_snapshot") == "discordant":
        concord = headline.get("prism_crispr_concord")
        return {"text": ("chemical activity is discordant with the genetic dependency (off-target) — the "
                         "compound kill does not track the CRISPR/RNAi requirement"
                         + (f"; concordance: {concord}" if concord else "")),
                "source": "chemical_genetic_discordance", "severity": 3}
    return None


_TRACTABILITY_HEADLINE_SPEC = HeadlineSpec(
    gate="tractability_sm",
    axis_labels={"POTENCY": "measured binding", "ACTIVITY": "functional compound",
                 "STRUCT": "ligandable pocket", "DRUG": "known-drug pharmacology",
                 "DEGRADER": "degrader feasibility"},
    axis_keys=("POTENCY", "ACTIVITY", "STRUCT", "DRUG", "DEGRADER"),
    critical_axes=("POTENCY", "ACTIVITY"),
    verdict_label=lambda v: _DRUGGABILITY_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    tension_extra=_tractability_tension_extra,
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed tractability headline. Reads the
    druggability_snapshot + the verdict-inert claim_vector / key_signals; never moves the spine. The
    skill emits no CERTAINTY_MODEL sidecar, so confidence is the derived weakest-link over the claim
    vector's corroboration."""
    v = headline.get("druggability_snapshot")
    return build_headline(headline, headline.get("claim_vector"), headline.get("key_signals"),
                          spec=_TRACTABILITY_HEADLINE_SPEC, verdict_token=v,
                          driving_rule_id=headline.get("driving_rule_id"),
                          verdict_polarity=_tractability_verdict_polarity(v))


SKILL_NAME = "tractability-small-molecule"
SKILL_VERSION = "3.5.0"     # 3.5.0 (2026-08-21): emit existing per-question question_table into the headline
                            # 3.4.0/3.1.0 +E8; +known-drug; +degradation; +T1.1/T1.2/T3.1
                            #   (discordant reorder, clinical_precedent_only, measured-potency card).
                            # 3.0.0: split from tractability-and-modality 2.1.0.

CARDS = [
    "prism-compound-activity",
    "prism-crispr-concordance",
    "dependency-predictability",
    "structure-features-static",   # E8: FORWARD ligandability (pocket structure)
    "known-drug-tractability",     # E-known-drug: PHARMACOLOGY leg (DGIdb known-drug + druggable-category)
    "measured-potency-tractability",  # E-measured-potency (T3.1): ChEMBL/BindingDB MEASURED binding potency
    "degradation-feasibility",     # E3 slice 3: DEGRADER-lens degradability (E3-substrate + precedent + location gate)
    "gdsc-drug-activity",          # 2nd drug-response platform (Sanger GDSC1/2) — ORTHOGONAL corroboration of
                                   # PRISM. DISPLAY-ONLY / verdict-INERT: fires no rule, feeds no resolver rung,
                                   # so druggability_snapshot is byte-stable (the ProCan->Gygi analog).
]

QUESTION = ("Does {target} in {indication} show small-molecule druggability evidence "
            "— is there a compound that hits it (chemical), does that agree with the "
            "genetic dependency, and is there a druggable pocket even absent a known "
            "compound (structural / forward ligandability)?")


def _snapshot(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (B3a, 2026-08-06).
    The former 11-rung if-chain now lives in resolvers/tractability_small_molecule.resolver.yaml
    (target-contracts), evaluated by the ONE interpreter every gate skill calls. Proven byte-for-byte
    equivalent to the former if-chain by the golden-oracle test (test_tractability_sm_resolver_oracle.py,
    which enumerates every rule combination against the retained _snapshot_legacy_oracle). A missing spec
    raises (the resolver is the source of truth — no silent fallback to a stale copy, which would
    reintroduce drift). Mirrors surface-modality-fit's _verdict."""
    return resolve_or_raise(fired, "tractability_small_molecule")


def _snapshot_legacy_oracle(fired: list[dict]) -> tuple[str, str | None]:
    """RETAINED ONLY as the golden-oracle for the equivalence test — NOT called at runtime.
    The original rank-ordered if-chain (first match wins). Chemical-genetic evidence (E6/E7,
    RETROSPECTIVE — a compound has actually hit the target) ranks highest. Structural / forward
    ligandability (E8 — a druggable pocket) ranks BELOW a real chemical hit but ABOVE
    `chemically_unhit` (KRAS-G12C switch-II pre-sotorasib). A measured structural NEGATIVE ranks
    as an SM-opposing note. test_tractability_sm_resolver_oracle.py asserts the declarative resolver
    reproduces this function's output for EVERY rule combination; do not edit without re-freezing that
    equivalence.
    """
    fired_by_id = {r["rule_id"]: r for r in fired}
    # --- On-target chemical-genetic (retrospective, CONCORDANCE-confirmed) — top; discordant does
    #     NOT override an on-mechanism read. ---
    if "e7-triangulated-target-engaged-supportive" in fired_by_id:
        return "well_covered", "e7-triangulated-target-engaged-supportive"
    if "e7-crispr-confirmed-supportive-sm" in fired_by_id:
        return "chemically_confirmed_genetic", "e7-crispr-confirmed-supportive-sm"
    # --- Opposing off-target read (T1.1, 2026-08-09): MUST precede the retrospective chemical-ACTIVITY
    #     positives below (an active-but-off-target compound argues AGAINST tractability). Kept
    #     byte-in-sync with resolvers/tractability_small_molecule.resolver.yaml. ---
    if "e7-discordant-off-target-warning" in fired_by_id:
        return "discordant", "e7-discordant-off-target-warning"
    # --- Retrospective chemical ACTIVITY (a compound was found; NOT concordance-checked here) ---
    if "prism-clinically-active-supportive-sm" in fired_by_id:
        return "chemically_active", "prism-clinically-active-supportive-sm"
    # E-known-drug (DGIdb pharmacology leg, 2026-08-07): an APPROVED drug catalogued against the
    # target -> chemically_active (SAME verdict as PRISM clinically-active; rescues a target PRISM
    # missed). Byte-in-sync with resolvers/tractability_small_molecule.resolver.yaml.
    if "known-drug-approved-antineoplastic-sm-supportive" in fired_by_id:
        return "chemically_active", "known-drug-approved-antineoplastic-sm-supportive"
    # WS-E (2026-08-24): ChEMBL max_clinical_phase >= 4 (approved) -> chemically_active (a third
    # independent path corroborating the PRISM/DGIdb approved rungs). Byte-in-sync with the resolver.
    if "measured-chembl-approved-sm-supportive" in fired_by_id:
        return "chemically_active", "measured-chembl-approved-sm-supportive"
    # WS-E (2026-08-24): ChEMBL phase 1-3 -> clinical_precedent_only, AUTHORITATIVE over the PRISM
    # `Prioritized`-flag proxy below (placed ABOVE it so the real-phase rule is the driving_rule when
    # both fire; same verdict). Byte-in-sync with the resolver.
    if "measured-chembl-clinical-precedent-sm-supportive" in fired_by_id:
        return "clinical_precedent_only", "measured-chembl-clinical-precedent-sm-supportive"
    # T1.2 (2026-08-09): clinical annotation WITHOUT measured PRISM activity -> clinical_precedent_only
    # (weaker than measured chemically_active, above tool_compound_only).
    if "prism-clinical-precedent-only-weak-supportive-sm" in fired_by_id:
        return "clinical_precedent_only", "prism-clinical-precedent-only-weak-supportive-sm"
    if "prism-tool-compound-only-weak-supportive-sm" in fired_by_id:
        return "tool_compound_only", "prism-tool-compound-only-weak-supportive-sm"
    if "prism-weakly-active-weak-supportive-sm" in fired_by_id:
        return "weakly_active", "prism-weakly-active-weak-supportive-sm"
    # --- MEASURED potency (T3.1, 2026-08-09): a potent (<=1 uM) MEASURED chemotype series
    #     (ChEMBL/BindingDB) -> measured_potent_ligand. Below the retrospective chemical-activity
    #     rungs, above the structural tier. Byte-in-sync with the resolver. ---
    if "measured-potent-ligand-sm-supportive" in fired_by_id:
        return "measured_potent_ligand", "measured-potent-ligand-sm-supportive"
    # --- Structural / forward ligandability (E8: druggable pocket, no compound yet) ---
    # Ranked below any real chemical hit, above chemically_unhit — a druggable pocket
    # is a positive SM prospect even before a compound exists (the KRAS-G12C fix).
    # E8-lig (composite structure-ligandability-per-protein-v1, 2026-08-07): the LIVE structural
    # leg. A real experimental co-crystal is the STRONGEST forward handle → top of the structural
    # tier; predicted (pocket/VS-hit/cryptic) sits with the existing pocket rungs. Kept byte-in-sync
    # with resolvers/tractability_small_molecule.resolver.yaml (same rung order + driving ids).
    if "ligandability-experimental-sm-supportive" in fired_by_id:
        return "structurally_ligandable", "ligandability-experimental-sm-supportive"
    if "hotspot-in-druggable-pocket-sm-supportive-e8" in fired_by_id:
        return "structurally_ligandable", "hotspot-in-druggable-pocket-sm-supportive-e8"
    if "structure-pocket-adjacent-sm-supportive" in fired_by_id:
        return "structurally_ligandable", "structure-pocket-adjacent-sm-supportive"
    if "ligandability-predicted-sm-supportive" in fired_by_id:
        return "structurally_ligandable", "ligandability-predicted-sm-supportive"
    # E-known-drug (DGIdb): a druggable-CATEGORY membership (clinically-actionable / druggable-genome,
    # no approved drug) is a forward druggable-class prior -> structurally_ligandable tier.
    if "known-drug-druggable-category-sm-supportive" in fired_by_id:
        return "structurally_ligandable", "known-drug-druggable-category-sm-supportive"
    # T3.1: weak measured activity (a potent hit or two / sub-potent) -> structurally_ligandable tier
    # (a starting-point handle, same as a predicted pocket). Byte-in-sync with the resolver.
    if "measured-weak-ligand-sm-supportive" in fired_by_id:
        return "structurally_ligandable", "measured-weak-ligand-sm-supportive"
    if "structure-low-confidence-sm-opposing" in fired_by_id:
        return "structurally_intractable", "structure-low-confidence-sm-opposing"
    if "ligandability-disordered-sm-opposing" in fired_by_id:
        return "structurally_intractable", "ligandability-disordered-sm-opposing"
    if "prism-no-compounds-found-neutral" in fired_by_id:
        return "chemically_unhit", "prism-no-compounds-found-neutral"
    return "insufficient", None


def _degrader_snapshot(fired: list[dict]) -> tuple[str, str | None]:
    """DEGRADER lens projection (modality-specific-interpretation, slice 2) — reads the DEGRADER
    channel of the same fired rules the SM snapshot reads the small_molecule channel of. Additive:
    surfaces a degrader-specific read alongside druggability_snapshot; touches NO resolver (the SM
    gate's verdict spine is unchanged — this is a headline lens, one-directional).

    A degrader lens is NOT the SM lens: degradation models COMPLETE removal (KO-like) rather than
    catalytic inhibition, so a target with a dependency but no druggable pocket can still be a degrader
    prospect. This first pass reads the degrader signal channel; the FULL degrader question ("is the
    degradation MACHINERY intact?" — CRBN/VHL/proteasome) needs the E3-machinery card (slice 3, not yet
    built), so `degradability_machinery` is reported as not_yet_assessed until that card lands.

    Rank (first match): a degrader-killer (e.g. broadly-low expression — nothing to degrade) →
    degrader_unviable; a dominant degrader-supportive → strong_degrader_rationale; any degrader-
    supportive → degrader_rationale; a degrader-opposing → degrader_opposed; else insufficient."""
    from _skills_common import modality_lens
    tally = modality_lens(fired, "degrader")
    if tally["killer"]:
        return "degrader_unviable", tally["killer"][0]["rule_id"]
    dominant_support = [r for r in tally["supportive"] if r.get("dominant")]
    if dominant_support:
        return "strong_degrader_rationale", dominant_support[0]["rule_id"]
    if tally["supportive"]:
        return "degrader_rationale", tally["supportive"][0]["rule_id"]
    if tally["opposing"]:
        return "degrader_opposed", tally["opposing"][0]["rule_id"]
    return "insufficient", None


def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    degrader_class, degrader_drv = _degrader_snapshot(fired)
    hl = {
        "druggability_snapshot":     v,
        "driving_rule_id":           drv,
        # DEGRADER lens — additive to the SM verdict; degradation ≠ inhibition (KO-like complete
        # removal). The degrader_snapshot now folds in the E3-degradability slice (slice 3): the
        # degradation-feasibility card's degrader-channel rules fire into the same `fired` set the
        # lens tallies, so a scaffolding/precedented/ubiquitinatable target reads
        # strong_degrader_rationale and a surface/secreted target reads degrader_opposed — WITHOUT
        # touching the small-molecule druggability_snapshot (degrader-channel-only rules; SM spine
        # byte-stable, proven by the resolver golden-oracle test).
        "degrader_snapshot":         degrader_class,
        "degrader_driving_rule_id":  degrader_drv,
        # slice 3 LANDED: the target-degradability read (E3-substrate + PROTAC precedent + location
        # gate) from the degradation-feasibility card, replacing the not_yet_assessed placeholder.
        "degradability_machinery":   get_card_field(cards, "degradation-feasibility", "degradability_feasibility_class"),
        "degradability_e3_evidence": get_card_field(cards, "degradation-feasibility", "e3_substrate_evidence"),
        "degrader_precedent":        get_card_field(cards, "degradation-feasibility", "degrader_precedent"),
        # 2026-08-09 bugfix: these read the WRONG field names — the methods emit
        # `prism_activity_class` / `crispr_prism_concordance_class`, not `activity_class` /
        # `concordance_class`. get_card_field returns None on a missing key (no raise), so both
        # headline fields were ALWAYS None → decision.json blank + the LLM synthesis prompt
        # (synthesis_tractability_sm.py reads h['prism_activity_class'] / ['prism_crispr_concord'])
        # was starved of the two most important chemical facts. Verdict UNAFFECTED (the rules read
        # the correct field names directly via the rule engine).
        "prism_activity_class":      get_card_field(cards, "prism-compound-activity", "prism_activity_class"),
        "prism_crispr_concord":      get_card_field(cards, "prism-crispr-concordance", "crispr_prism_concordance_class"),
        # GDSC 2nd-platform ORTHOGONAL corroboration (2026-08-25): Sanger GDSC1+GDSC2 drug-response,
        # a DIFFERENT lab/assay/library than Broad PRISM. VERDICT-INERT display — the card fires no
        # rule + feeds no resolver rung, so these fields never move druggability_snapshot; a headline-
        # only cross-platform read (a target potent in BOTH GDSC and PRISM is more credible). NOT in
        # _SYNTHESIS_FACET_KEYS → the composed claim_vector/facet stay byte-stable.
        "gdsc_activity_class":       get_card_field(cards, "gdsc-drug-activity", "gdsc_activity_class"),
        "gdsc_most_sensitive_drug":  get_card_field(cards, "gdsc-drug-activity", "most_sensitive_drug_name"),
        "predictability_class":      get_card_field(cards, "dependency-predictability", "predictability_class"),
        # E8 structural / forward ligandability (2026-07-17)
        "hotspot_pocket_adjacency":  get_card_field(cards, "structure-features-static", "hotspot_pocket_adjacency_call"),
        "hotspot_in_druggable_pocket": get_card_field(cards, "structure-features-static", "mutation_hotspot_in_druggable_pocket"),
        "pdb_coverage_class":        get_card_field(cards, "structure-features-static", "pdb_coverage_class"),
        "alphafold_confidence_class": get_card_field(cards, "structure-features-static", "alphafold_confidence_class"),
        # E-known-drug PHARMACOLOGY leg (DGIdb, 2026-08-07): known-drug + druggable-category read
        "known_drug_tractability":   get_card_field(cards, "known-drug-tractability", "known_drug_tractability_class"),
        "has_approved_drug":         get_card_field(cards, "known-drug-tractability", "has_approved_drug"),
        "n_antineoplastic_interactions": get_card_field(cards, "known-drug-tractability", "n_antineoplastic_interactions"),
    }
    # verdict-INERT claim-vector projection (6th concrete) — POTENCY/ACTIVITY/STRUCT/DRUG/DEGRADER
    # signal decomposition + citable atoms the composed fan-out lifts to the cross-evidence agent.
    hl["claim_vector"] = small_molecule_claim_vector(hl, cards)
    hl["key_signals"] = small_molecule_key_signals(hl, cards)

    # The canonical HEADLINE block is a verdict-INERT projection over the claim_vector / key_signals just
    # built. Run it best-effort: a formatting/read fault must NEVER discard the druggability spine already
    # composed in `hl` (same degrade-on-exception discipline the dispatcher applies to synthesis/figures).
    # On the happy path this adds only the `headline_block` key (no _enrichment_errors), so the golden
    # ladder + replay fixtures stay byte-stable.
    def _enrich(label, fn, *fn_args):
        try:
            return fn(*fn_args)
        except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
            hl.setdefault("_enrichment_errors", {})[label] = f"{type(exc).__name__}: {exc}"
            return None

    # Canonical HEADLINE block (verdict + confidence + top tension) — deterministic text + a
    # renderer-agnostic hero payload for every consumer. Verdict-INERT; best-effort.
    hl["headline_block"] = _enrich("headline_block", _build_headline_block, hl)
    # The per-question (data · signal · confidence) LEADING table — verdict-INERT projection over the
    # just-built headline + claim_vector (mirrors tumor-presence / tumor-selectivity). Carried through
    # _synthesis_facet so the composed target-profile dashboard renders the same table. Best-effort.
    hl["question_table"] = _enrich("question_table", tractability_sm_question_table, hl, cards)
    return hl


_SYNTHESIS_FACET_KEYS = (
    "druggability_snapshot", "driving_rule_id", "degrader_snapshot",
    "prism_activity_class", "known_drug_tractability", "structural_ligandability_class",
    "degradability_machinery", "claim_vector", "key_signals",
    # the per-question (data·signal·confidence) rows — rendered as the leading table by target-profile too
    "question_table",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT small-molecule-tractability facet for the composed target-profile
    synthesis. Reuses _headline (single source) + returns the claim_vector (POTENCY/ACTIVITY/STRUCT/
    DRUG/DEGRADER, POSITIVE valence) + its citable atoms. Never moves the verdict; safe to omit."""
    h = _headline(cards, fired, verdict_pair)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = ("Deterministic small-molecule tractability facet; claim_vector is a "
                            "POSITIVE-valence druggability decomposition. Verdict owned by the "
                            "druggability resolver, not this projection.")
    return facet


def _llm_synthesis(cards, fired, verdict_pair, target, indication,
                   model_id=None, subtype=None):
    """Fan-out opt-in (mirrors _synthesis_facet): return this lens's provenance-tagged
    llm_synthesis block for the COMPOSED target-profile run. Builds the SAME minimal decision the
    narrator consumes standalone ({target, indication, headline, cards}) from the fan-out's already-
    resolved cards + this skill's _headline, then narrates through its OWN lens synthesizer. Best-
    effort + VERDICT-INERT: never enters fired/verdict/cards — a failure is the caller's to swallow."""
    headline = _headline(cards, fired, verdict_pair)
    decision = {
        "target": target, "indication": indication, "headline": headline,
        "cards": [{"card_id": c.get("card_id"), "summary": c.get("summary") or {}}
                  for c in cards],
    }
    return synthesize_tractability_sm(decision, model_id, subtype)


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_snapshot,
        headline_fn=_headline,
        # Skill-level graphics (opt-in --figures): the canonical headline hero (verdict · confidence ·
        # top tension). Additive / display-only; mirrors tumor-presence.
        skill_figures_fn=_emit_skill_figures,
        # Opt-in --synthesize narrates through the SMALL-MOLECULE tractability lens — its own tool schema
        # + prompt, foregrounding ON-TARGET-chemical vs FORWARD-structural vs neither (a discordant read
        # ARGUES AGAINST), plus the additive degrader read. Two-slot / verdict-inert: the dispatcher
        # attaches decision['llm_synthesis'] as a sibling key AFTER the spine is composed, so it is
        # structurally impossible for the narration to alter druggability_snapshot. Without this
        # synthesize_fn the dispatcher would fall back to the PRESENCE narrator (wrong lens — B3b, 2026-08-06).
        synthesize_fn=synthesize_tractability_sm,
    ))
