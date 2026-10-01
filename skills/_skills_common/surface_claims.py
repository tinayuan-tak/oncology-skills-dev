"""surface_claims — surface-modality-fit's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT projection of the
surface / ADC-TCE cards into (signal × corroboration) per orthogonal claim.

A concrete claim_vector_core instance. Five surface axes as a ClaimSpec list:

  FIT       ADC/TCE modality fit    — the composed surface-modality call (adc-tce-modality-fit).
  TOPOLOGY  surface topology / ECD  — extracellular-domain engineerability (surface-topology-and-ptm).
  DENSITY   antigen abundance       — surface copies/cell density class (surface-abundance-density).
  SAFETY    normal-tissue window    — normal-tissue breadth (normal-tissue-liability).
  SHED      ectodomain shedding     — membrane-retained vs shed (shed-ectodomain-liability).

UNIFORM valence: a STRONG signal is a BETTER surface-modality substrate (viable modality / large
engineerable ECD / high antigen density / clean normal-tissue window / membrane-retained). A MEASURED
adverse read is `negative` — a real LIABILITY the reasoner must weigh: broad normal-tissue expression
(SAFETY) or clinically-shed ectodomain (SHED). A MEASURED no-substrate read (neither_viable /
no_extracellular_domain / very_low density) is `absent`. `unmeasured` is a data GAP, never a substrate.

Verdict-INERT: reads the ALREADY-computed surface cards; the surface verdict is owned by the shared
resolver and stays byte-stable with or without this projection.

Axis signals/corroboration are read from `headline` (populated by run.py::_headline via
card_summary/get_card_field); the `cards` param ADDITIONALLY feeds the L2a `source_properties` map
(PR-1e, SK#2210 Wave-1e, #2214) via `_source_properties(cards_by_id(cards))` — a pure projection that
reads card summaries directly (never the headline), still verdict-inert and read by no rule/ladder.
"""

from __future__ import annotations

from _skills_common.claim_vector_core import (
    ClaimSpec,
    build_claim_vector,
    build_key_signals,
    bump_corroboration,
    cap_corroboration,
    cards_by_id,
    sig_ge,
)
from _skills_common.claim_vector_core import (
    corr as _corr,
)
from _skills_common.claim_vector_core import (
    signal_from_class as _sig,
)
from _skills_common.reliability import _derive_reliability

# ── enum → substrate-strength tier maps (grounded in the target-contracts summary vocabularies) ──────
_FIT_SIGNAL = {
    "ADC_preferred": "strong",
    "TCE_preferred": "strong",
    "both_viable": "strong",
    "modality_ambiguous": "moderate",
    "isoform_dependent_undefined": "weak",
    "neither_viable": "absent",
    "data_unavailable": "unmeasured",
}
_TOPOLOGY_SIGNAL = {  # ecd_engineerability_class — accessible ECD to engineer a binder against
    "large_ecd": "strong",
    "moderate_ecd": "moderate",
    "minimal_ecd": "weak",
    "no_extracellular_domain": "absent",
    "data_unavailable": "unmeasured",
}
_DENSITY_SIGNAL = {  # surface_density_class — antigen copies/cell
    "high": "strong",
    "moderate": "moderate",
    "low": "weak",
    "very_low": "absent",
    "unmeasured": "unmeasured",
}
_SAFETY_SIGNAL = {  # normal_tissue_breadth_class — clean window = strong; broad = measured LIABILITY
    "not_detected_in_normal": "strong",
    "restricted_normal_expression": "moderate",
    "moderate_normal_expression": "weak",
    "broad_normal_expression": "negative",
    "data_unavailable": "unmeasured",
}
_SHED_SIGNAL = {  # shed_liability_class — membrane-retained = strong; clinically-shed = measured LIABILITY
    "not_shed_membrane_retained": "strong",
    "secretome_proxy_shed": "weak",
    "clinically_shed": "negative",
    "indeterminate": "unmeasured",
}

_INFORMS = {
    "FIT": "ADC/TCE modality fit — the composed surface-modality call (viable modality vs neither)",
    "TOPOLOGY": "surface topology / ECD engineerability — is there an accessible extracellular domain to bind",
    "DENSITY": "antigen abundance — surface copies/cell density (ADC/TCE payload-floor viability)",
    "SAFETY": "normal-tissue window — restricted normal expression is favourable; broad is a LIABILITY",
    "SHED": "ectodomain shedding — membrane-retained is favourable; clinically-shed is a LIABILITY (sink / decoy)",
    "PMHC": "pMHC-TCE route — peptide-MHC epitope evidence (IEDB) for a TCR-mimetic engager the folded-surface ladder cannot see (an INTRACELLULAR target can still be a TCE target)",
}


from _skills_common.claim_vector_core import build_summary_atom  # shared atom builder (Group D)


def _atom(card_id, summary, keys, entity, read):
    return build_summary_atom(card_id=card_id, summary=summary, keys=keys, read=read, entity=entity)


def _mk_atom(card, field, keys, entity):
    def fn(h, c):
        return _atom(card, c.get(card) or {}, keys, entity, (c.get(card) or {}).get(field))

    return fn


_C_FIT, _C_TOP = "adc-tce-modality-fit", "surface-topology-and-ptm"
_C_DEN, _C_SAFE, _C_SHED = "surface-abundance-density", "normal-tissue-liability", "shed-ectodomain-liability"

_E_TI = {"measurement_type": "surface_modality_fit", "grain": "target_indication"}
_E_T = {"measurement_type": "surface_protein_biophysics", "grain": "target"}
_E_SAFE = {"measurement_type": "normal_tissue_surface_liability", "grain": "target", "valence": "liability"}
_E_SHED = {"measurement_type": "ectodomain_shedding_liability", "grain": "target", "valence": "liability"}

# single-cell within-tumour antigen-escape classes (tce_antigen_escape_class) that CORROBORATE a viable
# surface-modality call (homogeneous antigen) vs CONTRADICT it (escape reservoir / patient-variable).
_ESCAPE_HOMOGENEOUS = {"escape_risk_low"}
_ESCAPE_HETEROGENEOUS = {"escape_risk_high", "escape_risk_patient_variable"}


def _fit_corr(h, c):
    """FIT corroboration: the composed adc-tce-modality-fit call (topology+family, the signal source) is the
    base; single-cell within-tumour antigen homogeneity (tce_antigen_escape_class, from
    tumor-scrna-celltype-expression, already in the headline) is a genuinely INDEPENDENT second arm that
    qualifies a VIABLE modality call — a homogeneous antigen (escape_risk_low) bumps corroboration, an escape
    reservoir / patient-variable antigen caps it. Only qualifies a viable (>= moderate) fit; a neither_viable
    call is not corroborated by homogeneity. Was the single-source _corr proxy (dead-constant). Verdict-INERT."""
    fit_tier = _FIT_SIGNAL.get((c.get(_C_FIT) or {}).get("fit_class"), "unmeasured")
    if fit_tier == "unmeasured":
        return "unmeasured"
    base = "single_arm"  # the composed fit call alone — one arm
    if sig_ge(fit_tier, "moderate"):  # only a VIABLE fit call is qualified by antigen homogeneity
        escape = h.get("tce_antigen_escape_class")
        if escape in _ESCAPE_HOMOGENEOUS:
            return bump_corroboration(base, True)
        if escape in _ESCAPE_HETEROGENEOUS:
            return cap_corroboration(base, "low")
    return base


# pMHC-TCE route (peptide-MHC): the FIT/TOPOLOGY claims read the FOLDED-surface ladder (adc-tce-modality-fit
# reads neither_viable for an intracellular target), so an intracellular target with validated pMHC epitopes
# — a real TCR-mimetic TCE route (ERBB2/NY-ESO-1/MAGE archetype) — was invisible to the claim vector (the
# route lived only in the skill's verdict SNAPSHOT). This claim reads the RAW IEDB epitope evidence
# (pmhc_epitope_evidence_class, in the headline — NOT the snapshot/verdict), corroborated by the independent
# HLA-ligand-atlas presentation (pmhc_presentation_class). Verdict-INERT.
_PMHC_SIGNAL = {
    "tcell_validated": "strong",
    "presented_not_tcell_confirmed": "moderate",
    "no_positive_epitopes": "absent",
    "not_observed": "absent",
    "data_unavailable": "unmeasured",
}
_PMHC_PRESENTED = {"restricted_presentation", "intermediate_presentation", "broadly_presented_normal"}


def _pmhc_signal(h, c):
    cls = h.get("pmhc_epitope_evidence_class")
    sig = _PMHC_SIGNAL.get(cls, "unmeasured")
    n = h.get("pmhc_epitope_n_epitopes")
    ev = f"pMHC epitope evidence: {cls or 'data_unavailable'}" + (f", {n} epitopes" if n else "")
    return sig, ev, None


def _pmhc_corr(h, c):
    # only a POSITIVE epitope signal carries corroboration. Independent HLA-ligand-atlas PRESENTATION
    # (pmhc-presentation, a distinct product from the IEDB epitope evidence) confirms the peptide is
    # actually presented on MHC → bumps to high; else single-source moderate.
    if _PMHC_SIGNAL.get(h.get("pmhc_epitope_evidence_class"), "unmeasured") in ("unmeasured", "absent"):
        return "unmeasured"
    return "high" if h.get("pmhc_presentation_class") in _PMHC_PRESENTED else "single_arm"


# ── L2a: NAMED typed source_properties map (PR-1e of epic SK#2210 / #1507, replicating the safety/ ──
# dependency/genomic/selectivity seeds for the SURFACE domain). See surface.yaml
# (contracts/vocabularies/property_catalog/) for the governance record this projection must stay
# coherent with. Property table is AUTHORITATIVE per issue #2214 — implemented verbatim, not re-derived.
#
# The scale/unit slot for each retained quantitative anchor (envelope-v0: a raw value + its declared
# scale, never a `decision_weight`/`modality_relevance`). Absent → "raw".
_SURFACE_ANCHOR_SCALE = {
    # surface-topology-and-ptm (TMbed sequence-based ECD prediction).
    "extracellular_residue_count": "residue_count",
    "tm_pass_count": "segment_count",
    # surface-abundance-density (CPTAC/HPA-anchored copies-per-cell estimate).
    "estimated_copies_per_cell_median": "copies_per_cell",
    "estimated_copies_per_cell_lower": "copies_per_cell",
    "estimated_copies_per_cell_upper": "copies_per_cell",
    # normal-tissue-liability (HPA IHC breadth).
    "n_essential_tissues_with_expression": "tissue_count",
    "n_specific_tissues": "tissue_count",
    # shed-ectodomain-liability (Olink conditioned-media proteomics).
    "media_mean_npx": "olink_npx",
    # pmhc-epitope-evidence-iedb (IEDB positive-assay count).
    "n_epitopes": "epitope_count",
}

# Data-driven recipe (keyed by the L2a property name from the architecture's source_properties shape).
# `property_field` is the resolved observational class of that source; `anchors` are its retained
# quantitative anchors, in reading order; `context` fields are retained categorical/label qualifiers.
# Every `card_id`/`property_field`/anchor/context name below is taken VERBATIM from issue #2214's
# authoritative property table and verified against `contracts/cards/<card_id>.card.yaml`
# `outputs.summary_fields`.
#
# `fit_class` (adc-tce-modality-fit) is DELIBERATELY EXCLUDED — #1630 (closed-adjudicated) classifies it
# as L3 CONTEXT (the composed modality call), not an L2a observational property. No entry for it here;
# the FIT claim axis stays `resolves: []` in claim_axis.enum.yaml with a note explaining why it will
# never resolve a surface l2a property.
#
# `normal_tissue_surface_breadth` reads `normal-tissue-liability`, a card SHARED with the safety domain
# (safety.yaml's `normal_tissue_protein_liability`, PR-1a). Both entries declare the SAME
# `dependence_group` (`hpa_normal_tissue_ihc`) so a downstream integration never double-counts the two
# domains' reads of this one HPA-IHC card as independent arms — the two properties differ in WHICH field
# is primary (safety reads `essential_tissue_flag`, surface reads `normal_tissue_breadth_class`) but
# share the same underlying measurement.
#
# NO `comparability.valence` marker anywhere: surface topology/density/shedding/epitope-evidence are the
# SIGNAL this domain is looking for (is there a viable surface-modality substrate), not a liability —
# mirrors dependency/genomic/selectivity's default-frame call. NO `interpretation` provenance object
# either: every property_field below is a VERBATIM card read (no skills-layer disjunction decides any of
# these five classes).
#
# RELIABILITY (#2306): surface is the MOST detection/abundance-kind domain in the arc.
# `surface_antigen_density` is a detection/abundance-kind property — its `detection_strength_scheme`
# names the CALIBRATED `surface_absolute_density` scheme (#2329), which classifies a copies-per-cell
# value via the surface_antigen_density_ladder method's OWN `_classify` boundaries (100/1,000/10,000),
# imported never re-declared. `estimated_copies_per_cell_median` is the issue's authoritative anchor and
# shares those exact boundaries with the calibrated absolute-density tier, so projecting it through the
# scheme is honest (same cuts, not a second copy). No OTHER property in this table is detection/
# abundance-kind, so no other entry names a scheme — `detection_strength` stays OMITTED on the other
# four. `n_effective_anchor` is wired ONLY where the authoritative anchor list names a genuine
# sample/measurement-count field; `surface_topology_engineerability` (a sequence-based structural
# prediction), `normal_tissue_surface_breadth` (a tissue-BREADTH count, not a sample size) and
# `surface_antigen_density` (a per-gene point/interval estimate, not a cohort size) all honestly OMIT it.
# No anchor in this table carries a purity-confound r (the `expression-purity-confound` card is not
# among the five source cards), so NO entry names a `purity_confound_anchor` and `confound_flags` stays
# `[]` uniformly. No anchor in this table resolves from `allgene_percentile`, so NO entry names a
# `floor_tie_anchor` and `artifact_flags` stays `[]` uniformly. `powered` reads 'unmeasured' uniformly —
# no surface property-kind has a calibrated admissibility floor in
# `onc_methods.reliability_calibration.powered_floors` yet.
_SOURCE_PROPERTY_RECIPES_SURFACE = (
    {
        "name": "surface_topology_engineerability",
        "card_id": "surface-topology-and-ptm",
        "property_field": "ecd_engineerability_class",
        "anchors": ("extracellular_residue_count", "tm_pass_count"),
        "context": ("topology_class", "ecd_orientation"),
        "comparability": {
            "measurement_type": "surface_protein_biophysics",
            "sample_context": "sequence_based_tmbed_topology_prediction",
            "grain": "target",
        },
        # No genuine sample-N anchor: the ECD residue count and TM-pass count are sequence-prediction
        # outputs for ONE protein, not a cohort/sample size — n_effective honestly OMITTED.
        "reliability": {},
    },
    {
        "name": "surface_antigen_density",
        "card_id": "surface-abundance-density",
        "property_field": "surface_density_class",
        "anchors": (
            "estimated_copies_per_cell_median",
            "estimated_copies_per_cell_lower",
            "estimated_copies_per_cell_upper",
        ),
        # NO `density_evidence_level` context field: although emitted at runtime (the method / summary
        # schema carry it), the card's own `outputs.summary_fields:` list does NOT declare it — citing it
        # as a catalog observable would fail the referential-integrity clause (the field cannot be
        # traced to a DECLARED measurement). Honest omission rather than a fabricated citation; a card-doc
        # fix (adding it to summary_fields) is a separate, out-of-scope follow-up.
        "context": (),
        "comparability": {
            "measurement_type": "surface_antigen_density_estimate",
            "sample_context": "cptac_protein_hpa_ihc_anchored",
            "grain": "target",
        },
        # No genuine sample-N anchor in the authoritative table: the median/lower/upper copies-per-cell
        # values are a per-gene point estimate + uncertainty band, not a cohort size — n_effective
        # honestly OMITTED. detection_strength (#2329): the ONE detection/abundance-kind property in this
        # catalog — the calibrated `surface_absolute_density` scheme classifies the SAME copies-per-cell
        # boundaries (100/1,000/10,000) the median estimate is drawn on, so projecting
        # estimated_copies_per_cell_median through it is honest. The RICH field this domain fires.
        "reliability": {
            "detection_strength_scheme": "surface_absolute_density",
            "detection_strength_anchor": "estimated_copies_per_cell_median",
        },
    },
    {
        "name": "normal_tissue_surface_breadth",
        "card_id": "normal-tissue-liability",
        "property_field": "normal_tissue_breadth_class",
        "anchors": ("n_essential_tissues_with_expression", "n_specific_tissues"),
        "context": (),
        "comparability": {
            "measurement_type": "normal_tissue_protein_breadth",
            "sample_context": "normal_tissue",
            "grain": "target",
        },
        # No genuine sample-N anchor: n_essential_tissues_with_expression / n_specific_tissues are
        # tissue-BREADTH counts (how many tissues stained), not a sample size — n_effective honestly
        # OMITTED, mirroring safety.yaml's `normal_tissue_protein_liability` entry on this SAME card.
        "reliability": {},
    },
    {
        "name": "ectodomain_shedding",
        "card_id": "shed-ectodomain-liability",
        "property_field": "shed_liability_class",
        "anchors": ("media_mean_npx",),
        "context": ("shed_evidence_tier", "serum_marker", "shedding_protease"),
        "comparability": {
            "measurement_type": "ectodomain_shedding_liability",
            "sample_context": "depmap_conditioned_media_olink",
            "grain": "target",
        },
        # No genuine sample-N anchor in the authoritative table: media_mean_npx is a mean NPX level, not
        # a sample count (media_n_lines_detected exists on the card but is NOT in issue #2214's
        # authoritative anchor list for this property) — n_effective honestly OMITTED rather than adding
        # an anchor the table does not name.
        "reliability": {},
    },
    {
        "name": "pmhc_epitope_evidence",
        "card_id": "pmhc-epitope-evidence-iedb",
        "property_field": "epitope_evidence_class",
        "anchors": ("n_epitopes",),
        "context": (),
        "comparability": {
            "measurement_type": "iedb_positive_assay_epitope_evidence",
            "sample_context": "iedb_curated_assay_corpus",
            "grain": "target",
        },
        # n_effective = n_epitopes — the positive-assay peptide count IS the sample size behind the
        # epitope-evidence class (more epitopes = a better-powered read of this antigen's pMHC evidence).
        "reliability": {"n_effective_anchor": "n_epitopes"},
    },
)


def _typed_surface_anchor(field, value):
    """One retained quantitative anchor: {field, value, scale}. surface carries no field-disposition
    semantic_role / interpretation_reach source to project yet (unlike safety's `field_disposition.yaml`)
    — the minimal envelope-v0 shape is the honest one."""
    return {"field": field, "value": value, "scale": _SURFACE_ANCHOR_SCALE.get(field, "raw")}


def _source_properties(c: dict) -> "dict | None":
    """The NAMED, typed L2a source_properties map for the SURFACE domain (PR-1e, #2210/#2214): one
    entry per source/grain, lifting the per-source observational properties out of the claim signal
    blocks into an explicit, recoverable object. Returns None when no source resolves (whole key omitted
    → byte-stable), matching the safety/dependency/genomic/selectivity atom discipline on this vector.
    Pure projection, verdict-inert, carries no signal tier. Takes the cards-by-id map only: every
    surface class below is a verbatim card read, so unlike presence/safety there is no headline-evaluated
    disjunction to report."""
    out = {}
    for recipe in _SOURCE_PROPERTY_RECIPES_SURFACE:
        summ = c.get(recipe["card_id"], {}) or {}
        prop = summ.get(recipe["property_field"])
        # A source with no card / no resolved observational class emits no entry (byte-stable).
        if not prop or prop == "data_unavailable":
            continue
        entry = {
            "card_id": recipe["card_id"],
            # The L1 card field the class token was read from — NAMED on the entry (following the
            # safety/dependency/genomic/selectivity seeds) so every entry reconstructs to L1 as
            # {card_id, property_field, property}.
            "property_field": recipe["property_field"],
            "property": prop,
            "anchors": [_typed_surface_anchor(f, summ[f]) for f in recipe["anchors"] if summ.get(f) is not None],
            "comparability": dict(recipe["comparability"]),
        }
        # Retained categorical qualifiers that orient the anchors without being quantities themselves.
        # OMITTED entirely when the card supplies none, keeping a partial-card run byte-stable.
        context = {f: summ[f] for f in recipe["context"] if summ.get(f) is not None}
        if context:
            entry["context"] = context
        # The typed `reliability` facet (#2306 rollout step 4): a PURE projection over the entry's OWN
        # retained anchors + this recipe's n-anchor/detection-scheme spec. Verdict-inert (SK#2091).
        # Always present (powered is required); every OTHER field on the entry stays byte-identical.
        entry["reliability"] = _derive_reliability(entry["anchors"], recipe["reliability"])
        out[recipe["name"]] = entry
    return out or None


SURFACE_CLAIM_SPEC = [
    ClaimSpec(
        "FIT",
        "ADC/TCE modality fit",
        _sig(_C_FIT, "fit_class", _FIT_SIGNAL),
        _fit_corr,
        _INFORMS["FIT"],
        _mk_atom(
            _C_FIT,
            "fit_class",
            (
                "fit_class",
                "fit_rationale",
                "endocytosis_confidence",
                "surface_family_class",
                "is_adc_topology_favorable",
                "is_tce_topology_favorable",
            ),
            _E_TI,
        ),
    ),
    ClaimSpec(
        "TOPOLOGY",
        "surface topology / ECD",
        _sig(_C_TOP, "ecd_engineerability_class", _TOPOLOGY_SIGNAL),
        _corr(_C_TOP, "ecd_engineerability_class", _TOPOLOGY_SIGNAL),
        _INFORMS["TOPOLOGY"],
        _mk_atom(
            _C_TOP,
            "ecd_engineerability_class",
            (
                "topology_class",
                "ecd_engineerability_class",
                "tm_pass_count",
                "extracellular_residue_count",
                "ecd_orientation",
                "signal_peptide_present",
            ),
            _E_T,
        ),
    ),
    ClaimSpec(
        "DENSITY",
        "antigen abundance",
        _sig(_C_DEN, "surface_density_class", _DENSITY_SIGNAL),
        _corr(_C_DEN, "surface_density_class", _DENSITY_SIGNAL),
        _INFORMS["DENSITY"],
        _mk_atom(
            _C_DEN,
            "surface_density_class",
            (
                "surface_density_class",
                "density_evidence_level",
                "estimated_copies_per_cell_median",
                "estimated_copies_per_cell_lower",
                "estimated_copies_per_cell_upper",
                "hpa_ihc_intensity_class",
                "is_tce_viable",
                "is_adc_high_payload_viable",
            ),
            _E_TI,
        ),
    ),
    ClaimSpec(
        "SAFETY",
        "normal-tissue window",
        _sig(_C_SAFE, "normal_tissue_breadth_class", _SAFETY_SIGNAL),
        _corr(_C_SAFE, "normal_tissue_breadth_class", _SAFETY_SIGNAL),
        _INFORMS["SAFETY"],
        _mk_atom(
            _C_SAFE,
            "normal_tissue_breadth_class",
            (
                "normal_tissue_breadth_class",
                "essential_tissue_flag",
                "hpa_tissue_specificity",
                "n_essential_tissues_with_expression",
                "essential_tissues_flagged",
                "n_specific_tissues",
            ),
            _E_SAFE,
        ),
    ),
    ClaimSpec(
        "SHED",
        "ectodomain shedding",
        _sig(_C_SHED, "shed_liability_class", _SHED_SIGNAL),
        _corr(_C_SHED, "shed_liability_class", _SHED_SIGNAL),
        _INFORMS["SHED"],
        _mk_atom(
            _C_SHED,
            "shed_liability_class",
            (
                "shed_liability_class",
                "shed_evidence_tier",
                "serum_marker",
                "shed_product",
                "shedding_protease",
                "measured_shed_class",
                "media_mean_npx",
            ),
            _E_SHED,
        ),
    ),
    # pMHC-TCE route — reads the headline pmhc fields directly (custom fn, not the _sig card factory).
    ClaimSpec("PMHC", "pMHC-TCE route", _pmhc_signal, _pmhc_corr, _INFORMS["PMHC"]),
]

_DISCLAIMER = (
    "Modality-blind, verdict-INERT projection of the surface-modality-fit cards into orthogonal claims "
    "(FIT / TOPOLOGY / DENSITY / SAFETY / SHED / PMHC), each signal×corroboration. UNIFORM valence: a strong "
    "signal is a BETTER surface-modality substrate; a MEASURED adverse read (broad normal expression, "
    "clinically-shed ectodomain) is `negative` (a real liability); a measured no-substrate read is "
    "`absent`; `unmeasured` is a data gap. Claims are NOT averaged; never feeds the surface verdict."
)


def surface_claim_vector(headline: dict, cards: list) -> dict:
    """The verdict-INERT surface claim vector {FIT,TOPOLOGY,DENSITY,SAFETY,SHED,PMHC:
    {signal, corroboration, evidence, conflict, informs, evidence_atom?}, _disclaimer}."""
    vec = build_claim_vector(SURFACE_CLAIM_SPEC, headline, cards, _DISCLAIMER)
    # L2a NAMED source_properties map (PR-1e, #2210/#2214): the per-source observational properties
    # lifted out of the six claim signal blocks into a named, typed, L1-reconstructable object. Carries
    # NO `signal` key on any entry → not a chip, not a tier, read by no rule/verdict/ladder. OMITTED
    # entirely (byte-stable) when no source resolves, matching the concordance-claim discipline above.
    _props = _source_properties(cards_by_id(cards))
    if _props is not None:
        vec["source_properties"] = _props
    return vec


def surface_key_signals(headline: dict, cards: list) -> dict:
    """A brief, deterministic, CITED read over the surface claim vector (available without the LLM).
    SAFETY / SHED emit an explicit caveat when their MEASURED read is an adverse `negative` liability."""
    vec = surface_claim_vector(headline, cards)

    def _liability_caveat(label):
        def fn(claim):
            return (
                f"{label} is a MEASURED liability ({claim['evidence']})" if claim.get("signal") == "negative" else None
            )

        return fn

    return build_key_signals(
        vec,
        rank_keys=("FIT", "DENSITY", "TOPOLOGY", "SAFETY", "SHED"),
        support_fns={
            k: (lambda cl, _k=k: f"{_k}: {cl['signal']} ({cl['evidence']})")
            for k in ("FIT", "DENSITY", "TOPOLOGY", "SAFETY", "SHED")
        },
        critical_keys=("FIT", "DENSITY", "SAFETY", "SHED"),
        caveat_fns={
            "SAFETY": _liability_caveat("normal-tissue breadth"),
            "SHED": _liability_caveat("ectodomain shedding"),
        },
        headline_fn=lambda v, s: (
            "Surface / modality-fit substrate present."
            if s
            else "Limited surface / modality-fit substrate (or largely unmeasured)."
        ),
        fallback_caveat_fn=lambda: None,
    )


__all__ = ["surface_claim_vector", "surface_key_signals", "SURFACE_CLAIM_SPEC"]
