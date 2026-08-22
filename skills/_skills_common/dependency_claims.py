"""dependency_claims — functional-requirement's CLAIM VECTOR + KEY SIGNALS: a modality-blind,
verdict-INERT projection of the dependency cards into (signal × corroboration) per orthogonal claim.

The SECOND concrete instance of the shared claim_vector_core contract (presence_claims is the first).
Declares functional-requirement's four axes as a ClaimSpec list:

  DEP  genetic dependency          — CRISPR distribution (dependency_class), RNAi as an orthogonal-LoF
                                      within-claim corroboration; corroboration from CRISPR×RNAi concordance
                                      + Broad↔Sanger cross-consortium replication + omics-predictability.
  SEL  context-selectivity         — lineage-selectivity enrichment_class; corroboration from n lineages.
  COND conditional / synthetic-SL  — partner-conditional-dependency (WRN×MSI-style rescue); corroboration
                                      from the partner-deficient stratification q + n.
  CHEM chemical-genetic confirm.   — prism-crispr-concordance triangulation; corroboration from PRISM n.

KEY FIT (why dependency validates the shape): functional-requirement ALREADY separates SIGNAL from
CONFIDENCE — it resolves the verdict from CRISPR/RNAi/concordance, and carries dependency-predictability
+ cross-consortium-dependency as CONFIDENCE ANNOTATIONS, never the verdict. Those map DIRECTLY onto the
corroboration axis, so (signal × corroboration) is a natural fit here, not a presence-specific one.

Verdict-INERT: reads the ALREADY-computed _headline; never feeds the dependency resolver. The
KRAS/COADREAD offline replay guard freezes dependency_verdict byte-stable with or without this.

All inputs are read from the `headline` dict (populated by run.py::_headline via get_card_field, so the
headline-fields drift guard covers every class the claims key on); the `cards` param is accepted for
contract-uniformity with presence_claims but unused here.
"""
from __future__ import annotations

from _skills_common.claim_vector_core import (ClaimSpec, build_claim_vector, build_key_signals,
                                              bump_corroboration, cap_corroboration, sig_ge,
                                              build_summary_atom)

# ── enum → tier maps (grounded in the target-contracts card summary_fields_vocabulary) ────────────
# CRISPR dependency_class: common_essential | common_essential_underpowered | strongly_selective |
#                          broadly_dependent | non_dependent | non_dependent_underpowered | data_unavailable
_DEP_SIGNAL = {
    "strongly_selective": "strong",
    "common_essential": "strong",            # strong dependency MAGNITUDE (broad-tox caveat, see conflict)
    "broadly_dependent": "moderate",
    "non_dependent": "absent",               # a MEASURED pooled floor
    # both underpowered classes are admissibility GAPS (tiny-panel / diluted-pooled), NOT trusted calls
    "non_dependent_underpowered": "unmeasured",
    "common_essential_underpowered": "unmeasured",
    "data_unavailable": "unmeasured",
}
_RNAI_DEP = {"strongly_selective", "broadly_dependent", "common_essential"}
_RNAI_NONDEP = {"non_dependent"}
# CRISPR×RNAi concordance_class → base corroboration
_CONCORDANCE_REL = {
    "strongly_concordant_dependent": "high",
    "moderately_concordant_dependent": "moderate",
    "strongly_concordant_non_dependent": "moderate",
    "moderately_concordant_non_dependent": "moderate",
    "discordant": "low",
    "partially_assayed": "low",
    "data_unavailable": "unmeasured",
}
# lineage enrichment_class: lineage_selective | broadly_lineage_dependent | no_lineage_enrichment | data_unavailable
_SEL_SIGNAL = {
    "lineage_selective": "strong",
    "broadly_lineage_dependent": "weak",     # dependent across lineages = NOT selective (low window value)
    "no_lineage_enrichment": "absent",
    "data_unavailable": "unmeasured",
}
# partner_stratification_class
_COND_SIGNAL = {
    "partner_conditional_strongly_dependent": "strong",
    "partner_conditional_moderately_dependent": "moderate",   # rescue-firing for the WRN×MSI family
    "partner_neutral_strongly_dependent": "absent",           # dependent, but NOT conditional → no SL signal
    "not_partner_stratified": "absent",
    "insufficient_partner_deficient_rate": "unmeasured",
    "no_partner_mapped": "unmeasured",                        # GAP: no curated partner (extend partner_map)
    "data_unavailable": "unmeasured",
}
# crispr_prism_concordance_class
_CHEM_SIGNAL = {
    "triangulated_target_engaged": "strong",     # CRISPR AND RNAi BOTH track compound kill
    "crispr_confirmed_engagement": "moderate",
    "rnai_confirmed_engagement": "moderate",
    "mixed_engagement": "weak",
    "discordant_off_target_likely": "negative",  # compound kills, but NOT via the target
    "thin_evidence": "unmeasured",
    "data_unavailable": "unmeasured",
}

_INFORMS = {
    "DEP": "genetic dependency — the core actionability signal (is loss of the target lethal?)",
    "SEL": "context-selectivity — therapeutic-window / patient-selection lens (which lineages)",
    "COND": "conditional / synthetic-lethal — biomarker-stratified patient selection (partner-deficient)",
    "CHEM": "chemical-genetic confirmation — small-molecule tractability (is the dependency drug-confirmable?)",
}


# ── the four claims (signal_fn -> (tier, evidence, conflict); corroboration_fn -> tier) ─────────────
def _dep_signal(h, c):
    cls = h.get("crispr_call")
    sig = _DEP_SIGNAL.get(cls, "unmeasured")
    rnai = h.get("rnai_call")
    ev = f"CRISPR {cls or 'data_unavailable'}" + (f"; RNAi {rnai}" if rnai else "")
    conflict = None
    if cls == "common_essential":
        conflict = ("pan-essential — strong dependency magnitude but a broad-toxicity liability "
                    "(low selective window; also routes to on-target-safety)")
    elif sig_ge(sig, "moderate") and rnai in _RNAI_NONDEP:
        conflict = "RNAi (orthogonal LoF) does not corroborate the CRISPR dependency"
    return sig, ev, conflict


def _dep_corroboration(h, c):
    base = _CONCORDANCE_REL.get(h.get("concordance_call"), "unmeasured")
    if base == "unmeasured" and h.get("crispr_call") not in (None, "data_unavailable"):
        base = "low"   # a single CRISPR arm with no concordance read is still weak evidence
    crispr_dep = sig_ge(_DEP_SIGNAL.get(h.get("crispr_call")), "moderate")
    rnai = h.get("rnai_call")
    # sub-additive: independent orthogonal-assay (RNAi) agreement lifts corroboration one step
    base = bump_corroboration(base, crispr_dep and rnai in _RNAI_DEP)
    # independent CONSORTIUM replication (Sanger Project Score vs Broad) — stronger than intra-Broad
    cc = h.get("cross_consortium_class")
    if cc == "concordant_dependent":
        base = bump_corroboration(base, True)
    elif cc == "discordant":
        base = cap_corroboration(base, "low")
    # a disagreeing orthogonal assay caps corroboration
    if crispr_dep and rnai in _RNAI_NONDEP:
        base = cap_corroboration(base, "moderate")
    # omics-predictability meta-signal: own-omics-driven is a biomarker handle → confidence
    if h.get("predictability_class") == "own_omics_driven":
        base = bump_corroboration(base, True)
    return base


def _sel_signal(h, c):
    cls = h.get("lineage_selectivity")
    ev = (f"lineage enrichment: {cls or 'data_unavailable'}"
          " (target-grain — selective to SOME lineage, not necessarily the queried indication)")
    return _SEL_SIGNAL.get(cls, "unmeasured"), ev, None


def _sel_corroboration(h, c):
    n = h.get("n_lineages_evaluated")
    if not isinstance(n, (int, float)):
        return "unmeasured"
    return "high" if n >= 20 else "moderate" if n >= 10 else "low"


def _cond_signal(h, c):
    cls = h.get("partner_conditional_class")
    ev = {
        "no_partner_mapped": "no curated partner in partner_map.yaml (a GAP, not evidence against SL)",
        "insufficient_partner_deficient_rate": "too few partner-deficient cell lines to test",
    }.get(cls, f"partner-conditional: {cls or 'data_unavailable'}")
    return _COND_SIGNAL.get(cls, "unmeasured"), ev, None


def _cond_corroboration(h, c):
    if _COND_SIGNAL.get(h.get("partner_conditional_class"), "unmeasured") == "unmeasured":
        return "unmeasured"
    q, n = h.get("partner_stratification_q"), h.get("n_partner_deficient")
    sig_ok = isinstance(q, (int, float)) and q < 0.1
    if isinstance(n, (int, float)) and n >= 15 and sig_ok:
        return "high"
    if isinstance(n, (int, float)) and n >= 5:
        return "moderate"
    return "low"


def _chem_signal(h, c):
    cls = h.get("prism_concordance_class")
    conflict = ("PRISM compound kill does not track the CRISPR/RNAi dependency — likely off-target"
                if cls == "discordant_off_target_likely" else None)
    return _CHEM_SIGNAL.get(cls, "unmeasured"), f"PRISM×CRISPR: {cls or 'data_unavailable'}", conflict


def _chem_corroboration(h, c):
    if _CHEM_SIGNAL.get(h.get("prism_concordance_class"), "unmeasured") == "unmeasured":
        return "unmeasured"
    n = h.get("n_compounds_evaluated")
    if not isinstance(n, (int, float)):
        return "low"
    return "high" if n >= 10 else "moderate" if n >= 3 else "low"


# ── citable evidence atoms (claim_vector_core atom_fn) ──────────────────────────────────────────────
# Each atom binds the axis's load-bearing NUMERIC values to their source {card_id, fields} + entity
# keys, so a downstream reasoner (e.g. cross-evidence-hypothesis) can cite the value by a discrete
# token — satisfying its traceability HARD RULE — and JOIN across axes on the entity. Verdict-inert
# provenance: the ordinal signal/corroboration tiers are untouched (the atom is never averaged). These
# read the raw card summaries from `c` (cards_by_id); returns None when the source card is absent, so
# the axis stays byte-stable (no evidence_atom key).
def _atom(card_id: str, summary: dict, keys: tuple, entity: dict, read) -> dict | None:
    return build_summary_atom(card_id=card_id, summary=summary, keys=keys, read=read, entity=entity)


def _dep_atom(h, c):
    cid = "pan-cancer-crispr-dependency-distribution"
    return _atom(cid, c.get(cid) or {},
                 ("bimodality_coefficient", "distribution_shape", "fraction_strongly_dependent",
                  "median_chronos_panel", "p5_chronos_panel", "n_cell_lines_evaluated",
                  "selectivity_index", "dep_control_position_class"),
                 {"measurement_type": "crispr_lof_dependency", "sample_context": "cell_line",
                  "stratum": "pan_cancer"},
                 h.get("crispr_call"))


def _sel_atom(h, c):
    cid = "dependency-lineage-selectivity"
    return _atom(cid, c.get(cid) or {},
                 ("enrichment_class", "lineage_variance_explained", "lineage_omnibus_kruskal_h",
                  "lineage_omnibus_effect_size_class", "n_enriched_lineages", "n_lineages_evaluated"),
                 {"measurement_type": "crispr_lof_dependency", "sample_context": "cell_line",
                  "grain": "target_lineage"},
                 h.get("lineage_selectivity"))


def _cond_atom(h, c):
    cid = "partner-conditional-dependency"
    return _atom(cid, c.get(cid) or {},
                 ("partner_stratification_class", "n_partner_deficient", "partner_stratification_q"),
                 {"sample_context": "cell_line", "stratum": "partner_deficient"},
                 h.get("partner_conditional_class"))


def _chem_atom(h, c):
    cid = "prism-crispr-concordance"
    return _atom(cid, c.get(cid) or {},
                 ("crispr_prism_concordance_class", "n_compounds_evaluated", "n_dual_responders",
                  "best_spearman_r_crispr", "best_spearman_r_rnai"),
                 {"sample_context": "cell_line", "stratum": "pan_cancer"},
                 h.get("prism_concordance_class"))


DEPENDENCY_CLAIM_SPEC = [
    ClaimSpec("DEP", "genetic dependency", _dep_signal, _dep_corroboration, _INFORMS["DEP"], _dep_atom),
    ClaimSpec("SEL", "context-selectivity", _sel_signal, _sel_corroboration, _INFORMS["SEL"], _sel_atom),
    ClaimSpec("COND", "conditional / synthetic-lethal", _cond_signal, _cond_corroboration, _INFORMS["COND"], _cond_atom),
    ClaimSpec("CHEM", "chemical-genetic confirmation", _chem_signal, _chem_corroboration, _INFORMS["CHEM"], _chem_atom),
]

_DISCLAIMER = (
    "Modality-blind, verdict-INERT projection of the dependency cards into orthogonal claims "
    "(DEP genetic-dependency / SEL context-selectivity / COND conditional-SL / CHEM chemical-genetic-"
    "confirmation), each signal×corroboration. Claims are NOT additive; a weak SEL does not degrade a "
    "strong DEP. Reliability carries the confidence annotations functional-requirement already separates "
    "from its verdict (CRISPR×RNAi concordance, Broad↔Sanger cross-consortium replication, omics-"
    "predictability). Never feeds the dependency_verdict.")


def dependency_claim_vector(headline: dict, cards: list) -> dict:
    """The modality-blind claim vector {DEP,SEL,COND,CHEM: {signal, corroboration, evidence, conflict,
    informs}, _disclaimer}. Verdict-inert projection over the computed headline."""
    return build_claim_vector(DEPENDENCY_CLAIM_SPEC, headline, cards, _DISCLAIMER)


def dependency_key_signals(headline: dict, cards: list) -> dict:
    """A brief, direct, CITED read (deterministic; available without the LLM)."""
    vec = dependency_claim_vector(headline, cards)
    h = headline

    def sup_dep(claim):
        cc = h.get("cross_consortium_class")
        bits = [f"CRISPR {h.get('crispr_call')}"]
        if h.get("rnai_call"):
            bits.append(f"RNAi {h['rnai_call']}")
        cite = "[CRISPR + RNAi distributions" + ("; Broad↔Sanger cross-consortium]" if cc == "concordant_dependent" else "]")
        tail = " — independently corroborated across consortia" if cc == "concordant_dependent" else ""
        return f"Genetic dependency — {', '.join(bits)}{tail} {cite}"

    def sup_sel(claim):
        return (f"Lineage-selective dependency ({h.get('lineage_selectivity')}, "
                f"{h.get('n_lineages_evaluated')} lineages) [dependency-lineage-selectivity]")

    def sup_cond(claim):
        return (f"Partner-conditional (synthetic-lethal) dependency — {h.get('partner_conditional_class')} "
                f"[partner-conditional-dependency]")

    def sup_chem(claim):
        return (f"Chemical-genetic confirmation — {h.get('prism_concordance_class')} across "
                f"{h.get('n_compounds_evaluated')} PRISM compounds [prism-crispr-concordance]")

    def cav_dep(claim):
        return f"Weak/absent genetic dependency — CRISPR {h.get('crispr_call')} [CRISPR + RNAi distributions]"

    def cav_sel(claim):
        return (f"Not lineage-selective — {h.get('lineage_selectivity')}; the dependency (if any) is not "
                f"lineage-concentrated [dependency-lineage-selectivity]")

    def cav_chem(claim):
        if h.get("prism_concordance_class") == "discordant_off_target_likely":
            return "PRISM compound kill does not track the genetic dependency — likely off-target [prism-crispr-concordance]"
        return f"Chemical-genetic confirmation thin/absent — {h.get('prism_concordance_class')} [prism-crispr-concordance]"

    def head(v, supports):
        dep, sel, chem, cond = (v["DEP"]["signal"], v["SEL"]["signal"],
                                v["CHEM"]["signal"], v["COND"]["signal"])
        if sig_ge(dep, "moderate") and sig_ge(sel, "strong"):
            base = "Selective genetic dependency."
        elif sig_ge(dep, "strong"):
            base = "Strong genetic dependency."
        elif sig_ge(dep, "moderate"):
            base = "Genetic dependency, with caveats."
        elif sig_ge(cond, "moderate"):
            base = "Conditional (synthetic-lethal) dependency."
        elif dep == "absent":
            base = "Not a genetic dependency in the pooled panel."
        else:
            base = "Dependency largely unmeasured or not distinguishing."
        if sig_ge(chem, "moderate") and sig_ge(dep, "moderate"):
            base = base.rstrip(".") + ", chemically confirmed."
        return base

    return build_key_signals(
        vec,
        rank_keys=("DEP", "SEL", "COND", "CHEM"),
        support_fns={"DEP": sup_dep, "SEL": sup_sel, "COND": sup_cond, "CHEM": sup_chem},
        critical_keys=("DEP", "SEL", "CHEM"),   # COND is a positive-only rescue; not a critical caveat axis
        caveat_fns={"DEP": cav_dep, "SEL": cav_sel, "CHEM": cav_chem},
        headline_fn=head,
    )


__all__ = ["dependency_claim_vector", "dependency_key_signals", "DEPENDENCY_CLAIM_SPEC"]
