"""genomic_claims — genomic-alteration-profile's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT projection
of the alteration cards into (signal × corroboration) per orthogonal claim.

The FOURTH concrete instance of the shared claim_vector_core contract (presence, dependency,
selectivity are the first three). Genomic-alteration is inherently MULTI-CLASS — its whole point is
"which alteration class drives" — so the claim decomposition is by alteration class:

  SNV recurrent SNV/indel driver — driver-recurrence (pooled TCGA-MC3 + GENIE + MSK) + mutation
                                   landscape; corroboration = cross-cohort agreement.
  CN  copy-number driver         — cell-line amplification/deletion + patient-tumour focal CN;
                                   corroboration = cell-line ↔ patient agreement.
  FUS fusion driver              — recurrent fusion/rearrangement; corroboration = GENIE-SV recurrence.
  DEP alteration confers dependency — the "so what": is the target a biomarker-stratified genetic
                                   dependency (max over the 4 stratified-dependency classes — mutation /
                                   CN / fusion / amp-expr)? corroboration = mutation-drug-response
                                   (pharmacological confirmation). A WT/neutral-dependent signal is
                                   `absent` here (the ALTERATION does not confer the dependency).

FIT: like dependency + selectivity (and unlike presence), genomic's claims are cleanly SEPARABLE — a
class primary call for the signal, a distinct provenance for corroboration — so they map onto the
core's signal_fn / corroboration_fn ClaimSpec contract directly. The per-class primaries are read from
the skill's own `genomic_alteration_by_class` breakdown (single source — cannot drift from the cards).

Verdict-INERT: reads the ALREADY-computed headline; never feeds the genomic_alteration resolver. All
inputs come from `headline` (its `genomic_alteration_by_class` block + the guard-covered _HEADLINE_FIELDS
lifts); the `cards` param is accepted for contract-uniformity but unused.
"""
from __future__ import annotations

from _skills_common.claim_vector_core import (ClaimSpec, build_claim_vector, build_key_signals,
                                              SIGNAL_ORD, bump_corroboration, sig_ge)

# ── enum → tier maps (grounded in the target-contracts card summary_fields_vocabulary) ────────────
# driver_recurrence_class / pooled_driver_recurrence_class / genie_sv_recurrence_class (percentile bands)
_RECURRENCE_SIGNAL = {"top_1pct": "strong", "top_decile": "moderate", "mid": "weak",
                      "bottom_decile": "absent", "data_unavailable": "unmeasured"}
# copy_number_class / patient_copy_number_class
_CN_SIGNAL = {"recurrently_amplified": "moderate", "recurrently_deleted": "moderate",
              "mixed": "weak", "broadly_neutral": "absent", "data_unavailable": "unmeasured"}
_CN_FOCAL_POS = {"recurrent_focal_amplification", "recurrent_focal_deletion"}
# fusion_class
_FUS_SIGNAL = {"recurrent_fusion_driver": "strong", "sporadic_fusion": "weak",
               "no_recurrent_fusion": "absent", "data_unavailable": "unmeasured"}
# splice_exon_skip_class (splice-exon-skip-landscape) — curated oncogenic exon-skip DRIVER (METex14)
_SPLICE_SIGNAL = {"recurrent_splice_driver": "strong", "no_exon_skip": "absent",
                  "data_unavailable": "unmeasured"}
# the four stratified-dependency classes → "does the ALTERATION-positive subgroup selectively depend?"
# POSITIVE (alteration-positive dependent) vs NEGATIVE (WT/neutral dependent = alteration doesn't confer)
_STRAT_SIGNAL = {
    "mutant_strongly_dependent": "strong", "mutant_moderately_dependent": "moderate",
    "amplified_strongly_dependent": "strong", "amplified_moderately_dependent": "moderate",
    "fusion_positive_strongly_dependent": "strong", "fusion_positive_moderately_dependent": "moderate",
    "amplified_overexpressed_strongly_dependent": "strong", "amplified_overexpressed_moderately_dependent": "moderate",
    # WT/neutral/negative dependent → the alteration does NOT confer the dependency
    "wt_strongly_dependent": "absent", "neutral_strongly_dependent": "absent",
    "fusion_negative_strongly_dependent": "absent", "amp_expr_negative_more_dependent": "absent",
    # measured, not stratified by the alteration
    "not_mutation_stratified": "absent", "not_cn_stratified": "absent",
    "not_fusion_stratified": "absent", "not_amp_expr_stratified": "absent",
    # underpowered = gap, NOT absent
    "insufficient_mutation_rate": "unmeasured", "insufficient_amplification_rate": "unmeasured",
    "insufficient_fusion_rate": "unmeasured", "insufficient_amp_expr_rate": "unmeasured",
    "data_unavailable": "unmeasured",
}
# mutation-drug-response.drug_response_stratification_class → DEP corroboration (pharmacology)
_DRUG_CORR = {
    "mutant_strongly_drug_sensitive": "high", "mutant_moderately_drug_sensitive": "moderate",
    "mutant_drug_resistant": "low",
    "not_drug_response_stratified": "moderate",
    "insufficient_mutant_or_drug_data": "unmeasured", "no_on_target_compound": "unmeasured",
    "data_unavailable": "unmeasured",
}
_INDICATION_SCOPES = {"within_indication", "within_indication_mut_vs_pan_wt"}

_INFORMS = {
    "SNV": "recurrent SNV/indel driver — patient-selection (mutation-defined subgroup)",
    "CN": "copy-number driver — amplification/deletion biomarker",
    "FUS": "fusion driver — rearrangement-defined subgroup",
    "SPL": "splice exon-skip driver — a transcript-form driver (e.g. METex14), rearrangement-independent",
    "DEP": "alteration confers a genetic dependency — the actionability 'so what' (biomarker-stratified)",
}


def _by_class(h):
    return (h.get("genomic_alteration_by_class") or {}) if isinstance(h, dict) else {}


def _f(v, nd=0):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "n/a"


# ── the four claims (signal_fn -> (tier, evidence, conflict); corroboration_fn -> tier) ───────────
def _snv_signal(h, c):
    bc = _by_class(h).get("snv_indel") or {}
    landscape = bc.get("verdict")   # mutation_landscape_class
    if landscape == "no_mutations":
        return "absent", "no SNV/indel mutations in cohort", None
    rec = h.get("pooled_driver_recurrence_class") or h.get("driver_recurrence_class") or bc.get("recurrence_class")
    sig = _RECURRENCE_SIGNAL.get(rec, "unmeasured")
    ev = (f"SNV: {landscape or 'data_unavailable'}, recurrence {rec or 'data_unavailable'}"
          + (f" ({_f((h.get('pooled_mutation_frequency') or h.get('overall_mutation_frequency') or 0) * 100, 1)}% freq)"
             if isinstance(h.get("pooled_mutation_frequency") or h.get("overall_mutation_frequency"), (int, float)) else ""))
    return sig, ev, None


def _snv_corroboration(h, c):
    rec = h.get("pooled_driver_recurrence_class") or h.get("driver_recurrence_class")
    if _RECURRENCE_SIGNAL.get(rec, "unmeasured") == "unmeasured":
        return "unmeasured"
    cohorts = h.get("pooled_recurrence_cohorts")
    n_cohorts = len(cohorts) if isinstance(cohorts, (list, tuple)) else (cohorts if isinstance(cohorts, int) else 0)
    genie = h.get("genie_driver_recurrence_class")
    base = "moderate"
    if n_cohorts and n_cohorts >= 2:
        base = bump_corroboration(base, True)   # independent multi-cohort recurrence
    if genie in ("bottom_decile",) and rec in ("top_1pct", "top_decile"):
        base = "low"                            # WES says driver, panel says not — disagreement
    return base


def _cn_signal(h, c):
    bc = _by_class(h).get("copy_number") or {}
    cls = bc.get("verdict")   # copy_number_class (cell-line)
    sig = _CN_SIGNAL.get(cls, "unmeasured")
    focal = h.get("patient_focal_cn_class")
    if focal in _CN_FOCAL_POS:
        # Patient-tumour focal CN is the clinically-relevant driver event and drives the signal
        # INDEPENDENTLY of the cell-line arm. HER2/CCND1 are recurrently focally amplified in patient
        # tumours but read broadly_neutral in the DepMap cell-line panel; keying the signal off the
        # cell-line arm alone (the prior `sig_ge(sig,"moderate")` gate) silently discarded the focal
        # amplification and mis-read them as CN-`absent`. Now: cell-line + patient agree -> strong;
        # patient-focal alone (cell-line neutral) -> moderate. Mirrors the tumor-presence de-differentiation
        # fix (a measured tumour-tissue positive is not vetoed by a neutral cell-line proxy).
        sig = "strong" if sig_ge(sig, "moderate") else "moderate"
    ev = f"CN: cell-line {cls or 'data_unavailable'}, patient-focal {focal or 'data_unavailable'}"
    return sig, ev, None


def _cn_corroboration(h, c):
    bc = _by_class(h).get("copy_number") or {}
    cls = bc.get("verdict")
    if _CN_SIGNAL.get(cls, "unmeasured") == "unmeasured":
        return "unmeasured"
    focal = h.get("patient_focal_cn_class")
    amp = cls == "recurrently_amplified"
    deld = cls == "recurrently_deleted"
    if (amp and focal == "recurrent_focal_amplification") or (deld and focal == "recurrent_focal_deletion"):
        return "high"         # cell-line + patient-tumour agree on direction
    if focal in ("focal_neutral",) and cls in ("recurrently_amplified", "recurrently_deleted"):
        return "low"          # cell-line recurrent but patient tumour focal-neutral — disagreement
    return "moderate"


def _fus_signal(h, c):
    bc = _by_class(h).get("fusion") or {}
    cls = bc.get("verdict")   # fusion_class
    sig = _FUS_SIGNAL.get(cls, "unmeasured")
    # VERDICT-INERT confidence-aware downgrade: a `recurrent_fusion_driver` call flagged
    # `fusion_recurrence_confidence == moderate_promiscuous` rests on a promiscuous recurrence with NO
    # recurrent partner — the mixed bucket that also catches amplicon-artifact SVs at amplified oncogenes
    # (SKILL.md). Downgrade strong->weak so the signals-first layer + key_signals headline stop over-reading
    # a thin/promiscuous fusion as a co-driver (MET/LUAD: n=3 promiscuous, contradicted by literature). This
    # does NOT touch the resolver rung — that verdict-moving fusion-competence/CN gate is tracked in #983.
    if sig == "strong" and h.get("fusion_recurrence_confidence") == "moderate_promiscuous":
        return "weak", f"fusion: {cls} (low-confidence: moderate_promiscuous — no recurrent partner)", None
    return sig, f"fusion: {cls or 'data_unavailable'}", None


def _spl_signal(h, c):
    bc = _by_class(h).get("splice") or {}
    cls = bc.get("verdict")   # splice_exon_skip_class
    sig = _SPLICE_SIGNAL.get(cls, "unmeasured" if cls in (None, "data_unavailable") else "absent")
    ev = f"splice exon-skip: {cls or 'data_unavailable'}" + (f" ({bc.get('event_id')})" if bc.get("event_id") else "")
    return sig, ev, None


def _spl_corroboration(h, c):
    bc = _by_class(h).get("splice") or {}
    if _SPLICE_SIGNAL.get(bc.get("verdict"), "unmeasured") == "unmeasured":
        return "unmeasured"
    # a curated oncogenic exon-skip driver with live DepMap carrier confirmation is well-corroborated
    n = bc.get("n_depmap_carriers")
    return "high" if isinstance(n, (int, float)) and n >= 1 else "moderate"


def _fus_corroboration(h, c):
    bc = _by_class(h).get("fusion") or {}
    if _FUS_SIGNAL.get(bc.get("verdict"), "unmeasured") == "unmeasured":
        return "unmeasured"
    return _RECURRENCE_SIGNAL_TO_CORR.get(bc.get("genie_sv_recurrence_class"), "moderate")


# GENIE-SV recurrence percentile → corroboration tier (top bands corroborate; low band doesn't)
_RECURRENCE_SIGNAL_TO_CORR = {"top_1pct": "high", "top_decile": "high", "mid": "moderate",
                              "bottom_decile": "low", "data_unavailable": "moderate"}


def _resistance_actionability(h) -> str | None:
    """VERDICT-INERT clinical-actionability breadcrumb from CIViC per-variant interpretation (the
    variant-level-interpretation card, this skill's own). Summarises the THERAPY-RESISTANCE alleles
    (`civic_resistance_variants`, already lifted onto the headline) as a compact clause the DEP claim's
    rendered evidence surfaces to the narrator. Motivated by the KRAS/COADREAD benchmark: the single most
    clinically-important CRC-specific KRAS fact — that KRAS mutation is a NEGATIVE predictive biomarker for
    anti-EGFR mAbs (cetuximab/panitumumab; extended-RAS testing = standard of care) — is fully present in
    the card but was invisible to the claim_vector / key_signals / narrator (the capsule projection does
    not surface resistance_variants), so the LLM synthesis missed it. Class-generic (no hardcoded therapy /
    indication); returns None when no resistance alleles are curated (axis byte-stable — no clause added).
    This is a clinical-INTERPRETATION annotation on the target's OWN alterations, squarely within this
    skill's variant-level-interpretation card — NOT a selectivity / therapeutic-window call (owned by
    tumor-selectivity) and NOT a nomination input (the claim vector never feeds the genomic resolver)."""
    rv = h.get("civic_resistance_variants") if isinstance(h, dict) else None
    if not isinstance(rv, list) or not rv:
        return None
    therapies: dict[str, int] = {}
    n_alleles = 0
    for v in rv:
        if not isinstance(v, dict):
            continue
        n_alleles += 1
        for combo in (v.get("therapies") or []):
            # a CIViC "therapies" entry can be a combination ("Panitumumab,Cetuximab"); count each agent
            for t in str(combo).split(","):
                t = t.strip()
                if t:
                    therapies[t] = therapies.get(t, 0) + 1
    if not n_alleles or not therapies:
        return None
    top = sorted(therapies, key=lambda t: (-therapies[t], t))[:3]
    return (f"CIViC therapy-resistance: {n_alleles} allele(s) annotated resistant to {len(therapies)} "
            f"therapies (top: {', '.join(top)}) [variant-level-interpretation]")


def _dep_signal(h, c):
    bc = _by_class(h)
    fields = [
        h.get("mutation_stratification_class") or (bc.get("snv_indel") or {}).get("stratified_dependency_class"),
        h.get("cn_stratification_class") or (bc.get("copy_number") or {}).get("stratified_dependency_class"),
        h.get("amp_expr_stratification_class") or (bc.get("copy_number") or {}).get("amp_expr_dependency_class"),
        h.get("fusion_stratification_class") or (bc.get("fusion") or {}).get("stratified_dependency_class"),
    ]
    tiers = [_STRAT_SIGNAL.get(f, "unmeasured") for f in fields if f is not None]
    measured = [t for t in tiers if SIGNAL_ORD.get(t) is not None]
    # VERDICT-INERT clinical-actionability breadcrumb (CIViC therapy-resistance) folded into the DEP
    # ("actionability so what") claim's rendered evidence so the narrator surfaces it; None → no clause.
    _res = _resistance_actionability(h)
    _res_clause = f"; {_res}" if _res else ""
    if not measured:
        return "unmeasured", "no biomarker-stratified dependency measured" + _res_clause, None
    best = max(measured, key=lambda t: SIGNAL_ORD[t])
    fired = [f for f in fields if f and _STRAT_SIGNAL.get(f) == best]
    return best, f"biomarker-stratified dependency: strongest = {fired[0] if fired else best}" + _res_clause, None


def _dep_corroboration(h, c):
    # only meaningful when the alteration confers a dependency (a positive DEP signal)
    drug = h.get("drug_response_stratification_class")
    base = _DRUG_CORR.get(drug, "unmeasured")
    # within-indication (not a pan-cancer extrapolation) localisation raises confidence
    scopes = [h.get("stratified_evidence_scope"), h.get("cn_stratified_evidence_scope"),
              h.get("fusion_stratified_evidence_scope"), h.get("amp_expr_stratified_evidence_scope")]
    if base in ("moderate", "low") and any(s in _INDICATION_SCOPES for s in scopes):
        base = bump_corroboration(base, True)
    return base


SNV, CN, FUS, SPL, DEP = "SNV", "CN", "FUS", "SPL", "DEP"


# ── citable evidence atoms (claim_vector_core atom_fn) ──────────────────────────────────────────────
# Bind each genomic axis's load-bearing VALUES to its source {card_id, fields} + entity keys, so the
# cross-evidence reasoner can cite the number (frequency, recurrence percentile, stratified effect
# size + q) by a discrete token rather than the bare class label. Verdict-inert; returns None when the
# source card is absent (axis stays byte-stable — no evidence_atom key).
from _skills_common.claim_vector_core import build_summary_atom  # shared atom builder (Group D)


def _gatom(card_id: str, summary: dict, keys: tuple, entity: dict, read) -> dict | None:
    return build_summary_atom(card_id=card_id, summary=summary, keys=keys, read=read, entity=entity)


def _snv_atom(h, c):
    cid = "mutation-hotspot-frequency"
    return _gatom(cid, c.get(cid) or {},
                  ("driver_recurrence_class", "pooled_mutation_frequency", "overall_mutation_frequency",
                   "pooled_driver_recurrence_percentile", "driver_recurrence_percentile",
                   "n_samples_in_indication", "n_samples_mutated"),
                  {"measurement_type": "mutation_hotspot_recurrence", "grain": "target_indication"},
                  (h.get("pooled_driver_recurrence_class") or h.get("driver_recurrence_class")))


def _cn_atom(h, c):
    cid = "copy-number-distribution"
    return _gatom(cid, c.get(cid) or {},
                  ("copy_number_class", "cn_distribution_shape", "cn_median_panel", "cn_p95_panel",
                   "cn_fraction_deep_deletion", "patient_focal_cn_class"),
                  {"measurement_type": "copy_number_alteration", "sample_context": "cell_line"},
                  (c.get(cid) or {}).get("copy_number_class"))


def _fus_atom(h, c):
    cid = "fusion-rearrangement-landscape"
    return _gatom(cid, c.get(cid) or {},
                  ("fusion_class", "n_samples_with_fusion", "genie_sv_frequency",
                   "genie_sv_recurrence_percentile"),
                  {"measurement_type": "fusion_rearrangement", "grain": "target_indication"},
                  (c.get(cid) or {}).get("fusion_class"))


def _gdep_atom(h, c):
    cid = "mutation-stratified-dependency"
    return _gatom(cid, c.get(cid) or {},
                  ("mutation_stratification_class", "delta_chronos_hotspot_mut_vs_wt",
                   "median_chronos_hotspot_mutant", "median_chronos_hotspot_wildtype",
                   "hotspot_mannwhitney_q", "n_hotspot_mutant", "n_hotspot_wildtype", "evidence_scope"),
                  {"measurement_type": "mutation_stratified_dependency", "sample_context": "cell_line",
                   "stratum": "hotspot_mutant_vs_wt"},
                  (c.get(cid) or {}).get("mutation_stratification_class"))


GENOMIC_CLAIM_SPEC = [
    ClaimSpec(SNV, "recurrent SNV/indel driver", _snv_signal, _snv_corroboration, _INFORMS["SNV"], _snv_atom),
    ClaimSpec(CN, "copy-number driver", _cn_signal, _cn_corroboration, _INFORMS["CN"], _cn_atom),
    ClaimSpec(FUS, "fusion driver", _fus_signal, _fus_corroboration, _INFORMS["FUS"], _fus_atom),
    # SPLICE exon-skip driver (METex14): the verdict-driving class added to the resolver in v2.13.0 but
    # historically absent from the claim vector — so a splice_exon_skip_driver verdict had no signal-layer
    # representation (the narrator led with SNV/fusion, not the driving splice class). No atom_fn yet
    # (curated event, not a numeric anchor). Verdict-INERT.
    ClaimSpec(SPL, "splice exon-skip driver", _spl_signal, _spl_corroboration, _INFORMS["SPL"]),
    ClaimSpec(DEP, "alteration confers dependency", _dep_signal, _dep_corroboration, _INFORMS["DEP"], _gdep_atom),
]

_DISCLAIMER = (
    "Verdict-INERT projection of the alteration cards into orthogonal per-class claims (SNV recurrent "
    "SNV/indel driver / CN copy-number driver / FUS fusion driver / SPL splice exon-skip driver / "
    "DEP alteration-confers-dependency), "
    "each signal×corroboration. Claims are NOT additive; genomic-alteration is a MIX — a strong CN does "
    "not degrade a weak SNV, and the strongest class is what drives. DEP asks whether the ALTERATION "
    "confers a genetic dependency (a WT/neutral-dependent signal is `absent` here). corroboration is a "
    "within-claim support tier, NOT the axis certainty. Never feeds the genomic_alteration verdict.")


def genomic_claim_vector(headline: dict, cards: list) -> dict:
    """The verdict-inert claim vector {SNV,CN,FUS,SPL,DEP: {signal, corroboration, evidence, conflict,
    informs}, _disclaimer}. Projection over the computed headline."""
    return build_claim_vector(GENOMIC_CLAIM_SPEC, headline, cards, _DISCLAIMER)


def genomic_key_signals(headline: dict, cards: list) -> dict:
    """A brief, direct, CITED read (deterministic; available without the LLM)."""
    vec = genomic_claim_vector(headline, cards)
    h = headline

    def sup_snv(claim):
        rec = h.get("pooled_driver_recurrence_class") or h.get("driver_recurrence_class")
        return f"Recurrent SNV/indel driver — {rec} recurrence [mutation-hotspot-frequency]"

    def sup_cn(claim):
        bc = _by_class(h).get("copy_number") or {}
        return (f"Copy-number driver — {bc.get('verdict')} (patient-focal {h.get('patient_focal_cn_class')}) "
                f"[copy-number-distribution]")

    def sup_fus(claim):
        return f"Fusion driver — {(_by_class(h).get('fusion') or {}).get('verdict')} [fusion-rearrangement-landscape]"

    def sup_spl(claim):
        bc = _by_class(h).get("splice") or {}
        n = bc.get("n_depmap_carriers")
        return (f"Splice exon-skip driver — {bc.get('verdict')} ({bc.get('event_id') or 'event'}"
                + (f", {n} DepMap carriers" if n is not None else "") + ") [splice-exon-skip-landscape]")

    def sup_dep(claim):
        return (f"Alteration confers a dependency — {vec['DEP']['evidence'].split('= ')[-1]} "
                f"(drug-response {h.get('drug_response_stratification_class')}) [stratified-dependency + drug-response]")

    def cav_snv(claim):
        return f"Not a recurrent SNV driver — {h.get('pooled_driver_recurrence_class') or h.get('driver_recurrence_class')} recurrence [mutation-hotspot-frequency]"

    def cav_cn(claim):
        return f"No recurrent copy-number alteration — {(_by_class(h).get('copy_number') or {}).get('verdict')} [copy-number-distribution]"

    def cav_spl(claim):
        return "No recurrent splice exon-skip driver [splice-exon-skip-landscape]"

    def cav_dep(claim):
        return "Alteration does not confer a measured genetic dependency (WT/neutral or not-stratified) [stratified-dependency]"

    # The alteration-CLASS keys whose (moderate+) signal names a driver — now includes SPL so a
    # splice_exon_skip_driver (METex14) verdict is NAMED in the headline (was previously omitted, and a
    # spuriously-strong promiscuous fusion led the line instead — see _fus_signal downgrade + #983).
    _CLASS_KEYS = (SNV, CN, FUS, SPL)

    def head(v, supports):
        drivers = [k for k in _CLASS_KEYS if sig_ge(v[k]["signal"], "moderate")]
        names = {SNV: "SNV/indel", CN: "Copy-number", FUS: "Fusion", SPL: "Splice exon-skip"}
        if len(drivers) >= 2:
            base = "Multi-class alteration driver (" + " + ".join(names[k] for k in drivers) + ")."
        elif len(drivers) == 1:
            base = f"{names[drivers[0]]}-driven alteration."
        elif any(v[k]["signal"] == "weak" for k in _CLASS_KEYS):
            base = "Sub-threshold alteration signal (passenger-leaning)."
        elif all(v[k]["signal"] in ("absent", "unmeasured") for k in _CLASS_KEYS):
            base = "No recurrent alteration (passenger / not altered)."
        else:
            base = "Alteration profile largely unmeasured."
        if sig_ge(v[DEP]["signal"], "moderate"):
            # Respect the emitted-verdict reconciliation: when the collapsed word was demoted to
            # `biomarker_dependency_unconfirmed` (both KO-dependency confidence cards contradict the
            # claimed dependency — see run.py reconcile_genomic_verdict), the DEP claim must be surfaced
            # as an UNCONFIRMED caveat here rather than asserted as a clean biomarker-stratified
            # dependency, so this most-read summary line can't over-read the verdict.
            if h.get("genomic_alteration_profile") == "biomarker_dependency_unconfirmed":
                base = base.rstrip(".") + " — biomarker dependency UNCONFIRMED (orthogonal KO-dependency evidence contradicts)."
            else:
                base = base.rstrip(".") + ", biomarker-stratified dependency."
        return base

    return build_key_signals(
        vec,
        rank_keys=(SNV, CN, FUS, SPL, DEP),
        support_fns={SNV: sup_snv, CN: sup_cn, FUS: sup_fus, SPL: sup_spl, DEP: sup_dep},
        # DEP first: the decision-critical caveat for a genomic call is "the alteration is a passenger /
        # confers no dependency"; then the class drivers.
        critical_keys=(DEP, SNV, CN, FUS, SPL),
        caveat_fns={SNV: cav_snv, CN: cav_cn, FUS: cav_cn, SPL: cav_spl, DEP: cav_dep},
        headline_fn=head,
    )


__all__ = ["genomic_claim_vector", "genomic_key_signals", "GENOMIC_CLAIM_SPEC"]
