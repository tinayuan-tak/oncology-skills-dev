#!/usr/bin/env python3
"""tumor-selectivity — tumor-vs-normal selectivity for a single (target, indication).

A thin orchestration shell: it declares the cards it consumes, the verdict logic, and the
headline projection, then hands off to the shared ``run_wired_skill`` dispatcher (the same
live-read path the compose-dashboard engine uses, so the two never drift). The verdict itself
is delegated to the shared declarative resolver plus a shared normal-breadth veto clamp.

See CHANGELOG.md for the version history.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import card_summary, resolve_cards
from _skills_common.dispatcher import run_wired_skill
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import TUMOR_SELECTIVITY as _LENS
# OPTIONAL --literature lane (shared, verdict-INERT): the published-literature read + live Europe-PMC
# grounding + PMID verification. Reused read-only from _skills_common (landed via the tumor-presence
# literature arc); NOT re-implemented here.
from _skills_common.literature_synthesis import make_literature_fn
from _skills_common.literature_retrieval import default_retrieve, verify_citations
from _skills_common.resolver import resolve_or_raise
from _skills_common.claim_record import assemble_claim_record
from _skills_common.selectivity_claims import selectivity_claim_vector, selectivity_key_signals
from _skills_common.selectivity_question_table import selectivity_question_table
from _skills_common.selectivity_hero import emit_selectivity_hero
# The SHARED canonical HEADLINE layer (verdict + confidence + top-tension), mirroring the merged
# tumor-presence / functional-requirement exemplars. build_headline is a verdict-INERT projection over
# the already-computed selectivity_class + claim_vector / key_signals; emit_headline_hero renders the
# offline figure_headline_hero.* twin (COMPLEMENTS emit_selectivity_hero — both fire under --figures).
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.skill_report import build_skill_report, ROLE_GATING
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.subgroup_derivation import make_value_classifier

# ─── Signals-first sub-group reader (verdict-INERT) ──────────────────────────────────────────────
# The fleet-default token heuristic is lens-blind — it tags this lens's POSITIVE selectivity signals
# (strongly_tumor_enriched, tumour_enriched_rna, malignant_broadly_detected, high density) as `absent`.
# _SELECTIVITY_VALUE_TIERS states the tier for the selectivity vocabulary (signal = strength of evidence
# FOR tumour-selectivity); normal-tissue liability / breadth are NEGATIVE evidence → `absent` (they lend
# no positive selectivity signal; the value string + narrator carry the caveat). default_classify remains
# the fallback for any unmapped value. VERDICT-INERT — the selectivity spine is untouched.
_SELECTIVITY_VALUE_TIERS = {
    "strongly_tumor_enriched": "strong", "moderately_tumor_enriched": "moderate",
    "weakly_tumor_enriched": "weak", "not_tumor_enriched": "absent", "tumor_depleted": "absent",
    "tumour_enriched_rna": "strong",
    "strongly_up": "strong", "modest_up": "weak", "unchanged": "absent", "down": "absent",
    "malignant_broadly_detected": "strong", "malignant_focally_detected": "moderate", "sparse": "weak",
    "high": "strong", "moderate": "moderate", "low": "weak",
    # normal-tissue liability / breadth = NEGATIVE evidence for a tumour-selectivity thesis
    "essential_tissue_liability": "absent", "high_liability": "absent",
    "broad_normal_protein": "absent", "broad_normal_expression": "absent", "immune_excluded": "absent",
}
# The normal-breadth VETO clamp is single-sourced in _skills_common.selectivity_veto so that BOTH
# this standalone skill AND the compose-dashboard engine (compose_core.resolve_gate_spine) apply the
# identical clamp. The names are re-exported here for this skill's own tests + local readability.
from _skills_common.selectivity_veto import (  # noqa: F401
    _AXIS_A_SELECTIVE, _NORMAL_BREADTH_VETO_RULES, _SELECTIVITY_VETO_PRECEDENCE, _WINDOW_VETO_RULE,
    _FULL_NORMAL_VETO_RULE, _SC_NORMAL_VETO_RULE, _STROMAL_CONFOUND_VETO_RULE,
    _STROMAL_CONFOUND_VERDICT, apply_normal_breadth_veto,
)


SKILL_NAME = "tumor-selectivity"
# This constant is stamped into provenance.yaml and MUST equal SKILL.md metadata.version
# (tests/test_version_parity.py guards the equality). Bump both together; log the change in CHANGELOG.md.
SKILL_VERSION = "1.21.0"   # 1.21.0 (2026-09-03): VERDICT-INERT measurement_caveat — a coverage-gap class token (not_informative/insufficient/data_unavailable) that actually rests on a decisive MEASURED signal (e.g. FAP/PDAC stroma-driven false window) is named so the composed profile need not treat it as an unmeasured gap. Additive headline field + synthesis-facet key; resolver/veto spine byte-stable.   # 1.20.0 (2026-09-03): --literature retriever -> default_retrieve (Europe PMC -> PubTator3 fallback chain; lens-specific query variations) so a transient single-source outage no longer collapses grounding to unverified. Shared _skills_common change.   # 1.19.0 (2026-09-03): OPTIONAL verdict-INERT LLM --literature lane (Europe-PMC-grounded + PMID-verified; decision['literature_synthesis'] fed to the --synthesize narrator), scoped to the WIN/DIST/INT/SAFE axes; reuses the shared _skills_common literature lane. Spine byte-stable.   # 1.18.0 (2026-09-03): multi-platform corroboration folded into the claim vector (VERDICT-INERT): WIN protein quorum (CPTAC+TPHP caps an un-corroborated RNA window) + INT in-situ-spatial quorum + WIN field-effect signature; LensConfig thesis + narrator rule lead with cross-platform corroboration.   # 1.17.0 (2026-08-31): INT-axis stromal-confound veto (verdict-MOVING, backtest-gated): stromal_confound_class == stromal_confounded → selective_but_stromal_confound (Option B: outranks the window KILL).   # 1.16.0 (2026-08-28): capsule-driven narrator via generic engine. Verdict-INERT.

# ── Cards consumed, grouped by the role each plays in the answer ──────────────────────────────────
# The selectivity RESOLVER is keyed only to the aggregate tumor-vs-normal-selectivity card (the
# verdict spine is byte-stable); every other card either feeds the normal-breadth veto clamp or is a
# verdict-inert display facet, as noted per card below.
CARDS = [
    # ── VERDICT-DRIVING ──
    "tumor-vs-normal-selectivity",           # The aggregate axis-A verdict: tumor-vs-tissue-of-origin
                                             # over-expression from the four-cell DESeq2 sensitivity
                                             # design (TCGA-adjacent raw + ComBat, GTEx-population).
    "tumor-vs-normal-percentile-crossing",   # Per-sample corroboration — fraction of tumors above the
                                             # matched-normal p95 (corroborates the aggregate log2FC at
                                             # per-sample resolution). Its crossing rules emit SM/degrader
                                             # signals; the resolver stays keyed to the aggregate card, so
                                             # this is additive signal/rationale (verdict byte-stable).
    "modality-therapeutic-window",           # NORMAL-BREADTH VETO instrument. therapeutic_window_class ==
                                             # no_therapeutic_window (tumor below the worst critical normal)
                                             # fires a veto that DOWNGRADES a selective axis-A call to
                                             # selective_but_broadly_normal: over-expression vs the tissue
                                             # of origin is necessary but NOT sufficient — the real window
                                             # is tumor-to-WORST-normal (the housekeeping GAPDH/TROP2 fix).
    "sc-normal-celltype-expression",         # NORMAL-BREADTH VETO instrument (cell-type-resolved normal
                                             # safety). sc_normal_safety_essential_class ==
                                             # critical_organ_liability — target highly detected in an
                                             # essential cell type of a NON-origin critical organ
                                             # (cardiomyocyte/hepatocyte/renal-tubule/HSC/neuron) that bulk
                                             # tissue medians dilute — fires a veto → downgrade.
                                             # origin_tissue_liability does NOT veto.
    # ── ADDITIVE FACETS (verdict-inert; feed no resolver rung / no clamp) ──
    "expression-purity-confound",            # Is the selectivity signal tumor-cell-intrinsic or driven by
                                             # stromal/immune (microenvironment) content? The four-cell
                                             # DESeq2 design has no purity covariate, so a CAF/stromal gene
                                             # high in bulk tumor can read tumor_selective. Display-only
                                             # caveat; microenvironment_confounded flags a possible false
                                             # ADC/degrader window from stromal expression.
    "surface-abundance-density",             # Absolute surface DENSITY (copies/cell): the Tier-1 calibrated
                                             # anchor (grade A/B curated corpus) + its floor standing
                                             # (soluble-TCE 1000/cell, ADC 10000/cell). Below-floor is a
                                             # MODALITY caveat, NOT a target killer (CD19 ~110/cell is a
                                             # validated CAR-T antigen). Un-anchored targets → unmeasured
                                             # (abstain; absence != low density).
    "tumor-protein-abundance-cptac",         # RNA→PROTEIN CORROBORATION (verdict-inert): does the
                                             # tumor-vs-normal signal hold at the PROTEIN layer? Emits
                                             # protein_effect_size (median_log2_tumor - median_log2_normal)
                                             # + protein_bh_q_value from CPTAC per-cohort TMT-MS
                                             # (cptac-protein-tumor-vs-normal-per-cohort-v1). Closes the
                                             # aggregate card's caveat #5 (RNA selectivity != protein
                                             # selectivity — the RNA-up/protein-flat false-positive). Feeds
                                             # no resolver rung / no clamp; data_unavailable off the ~10
                                             # CPTAC cohorts (honest abstain).
    "normal-tissue-protein-abundance-tphp",  # QUANTITATIVE NORMAL-tissue PROTEIN comparator (verdict-inert):
                                             # per-tissue DIA-MS protein abundance across 70 adult tissues + 4
                                             # fetal germ-layer groups (TPHP; Xu et al. Nature 2026). The normal-
                                             # PROTEIN baseline the skill lacked — it had GTEx-RNA + HPA-IHC
                                             # categorical breadth, but no quantitative normal protein. Surfaces
                                             # normal_protein_breadth_class + highest-abundance normal tissue as an
                                             # additive normal-comparator facet (a target RNA-restricted in normal
                                             # tissue can still be broadly normal-PROTEIN-expressed). Its
                                             # tphp_normal_protein_liability_class is VERDICT-BEARING (4th normal-breadth
                                             # veto arm): broad_and_abundant -> tvn-tphp-broad-abundant-normal-protein-veto
                                             # -> _verdict clamp -> selective_with_normal_liability. data_unavailable off
                                             # the TPHP proteome (e.g. DLL3).
    "tumor-vs-normal-protein-abundance-tphp", # RNA→PROTEIN CORROBORATION (verdict-inert), PARALLEL to
                                             # tumor-protein-abundance-cptac. Does the tumor-vs-normal signal
                                             # hold at the PROTEIN layer in the TPHP DIA-MS proteome (Xu et al.
                                             # Nature 2026; tphp-tumor-vs-normal-protein-per-cohort-v1) — 22
                                             # carcinoma cohorts, several OUTSIDE CPTAC coverage (gallbladder,
                                             # laryngeal, GIST, testis, thymoma, ...). Emits CPTAC-ALIGNED
                                             # protein_effect_size + protein_bh_q_value, so the SAME derived
                                             # _rna_protein_tvn_concordance projection consumes it unchanged.
                                             # Feeds no resolver rung / no clamp; data_unavailable off the TPHP
                                             # carcinoma cohorts (honest abstain).
    # ── SINGLE-CELL + IN-SITU SPATIAL (tumor side) ──
    # The bulk four-cell DESeq2 axis-A signal cannot tell whether a "tumor_selective" call is
    # MALIGNANT-cell-intrinsic or driven by CAF/stromal/immune microenvironment content (the purity
    # confound expression-purity-confound only PROXIES via bulk deconvolution). These cards MEASURE the
    # tumor compartment directly, at single-cell and in-situ resolution. tumor-scrna-celltype-expression
    # is now VERDICT-DRIVING (the stromal-confound veto, INT axis); the spatial cards remain verdict-inert.
    "tumor-scrna-celltype-expression",       # Tumor single-cell per-compartment expression. VERDICT-DRIVING
                                             # via the INT-axis stromal-confound veto: its stromal_confound_class
                                             # == stromal_confounded fires tvn-stromal-confound-veto → the
                                             # _verdict clamp downgrades a selective axis-A call to
                                             # selective_but_stromal_confound (the bulk signal is CAF/stroma-
                                             # driven, not malignant-cell-intrinsic — a false window for
                                             # tumor-cell-targeted modalities). Provenance-gated (only a
                                             # trustworthy curated/inferCNV entity-specific cube fires).
                                             # malignant_detection_fraction + caf_vs_malignant_class are the
                                             # underlying signals. Measured for COADREAD/NSCLC/LUSC/PAAD/HNSC/
                                             # KIRC/OV/STAD/BRCA cubes, else data_unavailable (abstain).
    "spatial-region-rna-expression",         # In-situ spatial (GeoMx WTA) tumour-vs-microenvironment RNA
                                             # enrichment — a deconvolution-free, orthogonal confirmation of
                                             # tumour-compartment selectivity (spatial_rna_class).
    "spatial-tumor-normal-colocalization",   # In-situ spatial colocalization — is target-high tumour
                                             # immune-excluded / adjacent to NORMAL EPITHELIUM
                                             # (normal_epithelium_adjacency_fraction = bystander/off-tumour
                                             # risk bulk cannot see)? A spatial selectivity/safety dimension.
    "spatial-surface-protein-abundance",     # In-situ spatial PROTEIN (GeoMx DSP) tumour-vs-microenvironment
                                             # enrichment — protein-layer selectivity for biologics. GeoMx
                                             # protein panels are sparse, so spatial_protein_class ==
                                             # data_unavailable for most indications (honest abstain).
]

QUESTION = ("How selectively is {target} expressed in {indication} tumor "
            "tissue, and how robust is that call across independent tumor-vs-"
            "normal comparators (TCGA-adjacent raw + ComBat, GTEx-population "
            "raw)?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Tumor-vs-normal selectivity verdict.

    Delegates to the shared declarative resolver (resolvers/selectivity.resolver.yaml in
    target-contracts, evaluated by the one interpreter both engines call), then applies the shared
    normal-breadth veto clamp. A missing resolver spec raises — the resolver is the single source of
    truth, with no silent fallback to a stale copy. Guarded by tests/test_verdict.py (resolver mapping
    + all three veto arms) and _skills_common/tests/test_compose_core.py (the engine applies the same
    clamp)."""
    verdict, driving = resolve_or_raise(fired, "selectivity")
    # NORMAL-BREADTH VETO: the resolver verdict (axis-A tumor-vs-origin over-expression) is NECESSARY
    # but NOT SUFFICIENT — a gene with no therapeutic window vs the worst critical normal (housekeeping
    # GAPDH/ACTB, or the TROP2/TACSTD2 broadly-normal surface archetype) is not a target regardless of
    # fold-change. This one-directional clamp downgrades a selective axis-A call to
    # selective_but_broadly_normal when any normal-breadth veto rule fired.
    return apply_normal_breadth_veto(verdict, driving, fired)


def _rna_protein_tvn_concordance(rna_direction, protein_effect_size, protein_q):
    """DERIVED, verdict-INERT: does the CPTAC tumor-vs-normal PROTEIN signal agree with the RNA call?

    Surfaces the RNA-up / protein-flat false-positive the aggregate RNA card explicitly flags as its
    own caveat (#5). Returns one of:
      rna_protein_concordant     — protein significant (BH q<0.05) in the SAME direction as RNA
      rna_protein_discordant     — protein significant but the OPPOSITE direction (RNA-up/protein-down)
      protein_not_significant    — protein measured but BH q>=0.05 (no protein-layer confirmation)
      protein_unmeasured         — no CPTAC tumor-vs-normal protein value for this cohort (abstain)
    Never feeds a rule/clamp; a projection over the two card summaries the headline already carries."""
    if protein_effect_size is None or protein_effect_size != protein_effect_size:   # None or NaN
        return "protein_unmeasured"
    if protein_q is None or protein_q != protein_q or protein_q >= 0.05:
        return "protein_not_significant"
    rna_up = rna_direction == "up"
    protein_up = protein_effect_size > 0
    return "rna_protein_concordant" if protein_up == rna_up else "rna_protein_discordant"


# Coverage-GAP verdict tokens: the resolver returned NO measured selectivity CALL (distinct from a
# measured negative like not_selective / discordant_across_comparators). A downstream consumer that
# treats these as "unmeasured" would miss a target that IS decisively measured but simply not
# tumor-cell-selective — most sharply the FAP/PDAC archetype (strongly present tumor-side but the
# single-cell/spatial attribution is stroma/CAF; the aggregate axis-A card abstains on the single-
# comparator field effect, so the stromal-confound veto is armed-but-moot and the class reads
# not_informative). The verdict-inert caveat below names that so the class token is not mistaken for a gap.
_COVERAGE_GAP_VERDICTS = {"not_informative", "insufficient", "data_unavailable", None}
_PRESENT_TIERS = {"strong", "moderate"}


def _measurement_caveat(hl: dict) -> dict | None:
    """VERDICT-INERT projection: flag the case where the RESOLVED selectivity_class is a coverage-GAP
    token yet the claim vector carries a DECISIVE measured signal — so the composed layer need not treat
    it as an unmeasured gap. Returns None for a measured call (nothing to disambiguate) or a genuine gap
    (no decisive signal). Never touches the verdict / normal-breadth / stromal-confound veto spine — a
    read over the already-built claim_vector + headline (the same discipline as the other _headline
    projections; byte-stable resolver)."""
    if hl.get("selectivity_class") not in _COVERAGE_GAP_VERDICTS:
        return None
    cv = hl.get("claim_vector") or {}
    dist = (cv.get("DIST") or {}).get("signal")
    win = (cv.get("WIN") or {}).get("signal")
    stromal = (hl.get("sc_stromal_confound_class") == "stromal_confounded"
               or (cv.get("INT") or {}).get("signal") == "negative")
    present = dist in _PRESENT_TIERS or win in _PRESENT_TIERS
    if not (present or stromal):
        return None                                  # a genuine coverage gap — nothing to disambiguate
    reason = ("stromal_confounded_false_window" if (stromal and present)
              else "stroma_dominant_signal" if stromal
              else "present_but_not_tumor_selective")
    note = {
        "stromal_confounded_false_window":
            "Verdict is a coverage-gap token, but the target IS strongly present tumor-side while single-"
            "cell/spatial attribute the signal to stroma/CAF — a MEASURED false window for a tumor-cell-"
            "targeted modality, NOT an unmeasured gap.",
        "stroma_dominant_signal":
            "Verdict is a coverage-gap token, but single-cell/spatial show the signal is stroma/CAF-"
            "driven — a MEASURED stromal read, NOT an unmeasured gap.",
        "present_but_not_tumor_selective":
            "Verdict is a coverage-gap token, but per-sample / effect-size signals show the target IS "
            "present tumor-side — the aggregate axis-A call abstained (e.g. single-comparator field "
            "effect), NOT an unmeasured gap.",
    }[reason]
    return {"verdict_is_coverage_gap": True, "measured_signal_present": True, "reason": reason, "note": note}


# ── The canonical HEADLINE layer (verdict + confidence + top-tension) ─────────────────────────────
# The shared headline_core declaration for tumor-selectivity: the WIN/DIST/INT/SAFE claim axes (the
# decision-critical axis = WIN, the tumor-vs-normal window), the selectivity resolver vocabulary → human
# phrase, and a skill-specific tension surfacing the normal-breadth VETO downgrade. Verdict-INERT — a
# one-way projection over the already-computed _headline (selectivity_class + the veto spine stay
# byte-stable, frozen by the CEACAM5/TACSTD2 replay guard). No CERTAINTY_MODEL sidecar exists for this
# skill, so confidence is the derived weakest-link over the claim vector (headline_core.derive_confidence).

# The selectivity verdict vocabulary → human phrase. Covers the axis-A over-expression classes, the two
# normal-breadth veto DOWNGRADE outcomes (the KILL vs the selectivity-preserving named-organ flag), and
# the measured-negative / coverage-gap tokens; prettify fallback for any future addition.
_SELECTIVITY_VERDICT_PHRASE = {
    # positive axis-A tumor-selective calls
    "strong_tumor_selective":          "Strongly tumor-selective",
    "modest_tumor_selective":          "Modestly tumor-selective",
    "field_effect_tumor_selective":    "Field-effect tumor-selective (vs distant normal)",
    # normal-breadth veto outcomes
    "selective_but_broadly_normal":    "Not selective — broadly normal (no therapeutic window)",  # the KILL
    "selective_with_normal_liability": "Tumor-selective, with a critical-organ normal liability",  # preserving
    # INT-axis stromal-confound veto outcome (the signal is in the WRONG cells)
    "selective_but_stromal_confound":  "Not tumor-cell-intrinsic — signal is stroma-driven (false window)",  # the INT KILL
    # measured negatives / conflict
    "not_selective":                   "Not tumor-selective",
    "discordant_across_comparators":   "Discordant across normal comparators",
    # coverage gaps
    "not_informative":                 "Not informative",
    "insufficient":                    "Insufficient evidence",
    "data_unavailable":                "Data unavailable",
}


def _selectivity_verdict_polarity(v) -> str:
    """The skill's OWN reading of the resolved selectivity verdict (colours the hero badge; never a gate).
    A clean axis-A tumor-selective call = positive; the broadly-normal KILL veto + a measured
    not_selective = negative; everything else (gaps, discordant, and the selectivity-PRESERVING
    `selective_with_normal_liability` — a real window but a named-organ liability, so neither a clean
    actionable positive nor a measured negative) = neutral, mirroring functional-requirement's treatment
    of `pan_essential_killer` (a real dependency carrying a liability)."""
    if v in _AXIS_A_SELECTIVE:                       # strong / modest / field_effect_tumor_selective
        return "positive"
    if v in ("selective_but_broadly_normal", "selective_but_stromal_confound", "not_selective"):
        return "negative"
    return "neutral"


# The two normal-breadth / stromal-confound VETO outcomes are KILLs — no therapeutic window
# (broadly_normal) / a false window (stromal_confound). They are canonical `killer` (a veto), NOT merely
# `opposing`. The 3-band headline polarity above collapses both to `negative` (→ the skill_report helper
# floors them to `opposing`), so we pass an explicit canonical_polarity_override="killer" for exactly
# these to keep the killer distinction in skill_report.polarity. `not_selective` is a plain measured
# negative (opposing), not a veto.
_SELECTIVITY_KILLER_VERDICTS = frozenset({"selective_but_broadly_normal", "selective_but_stromal_confound"})


def _sc_normal_liability_detail(sc_normal: dict):
    """Human-readable named-organ liability from the sc-normal essential-cell driver, or None.

    Names the organ + cell type + (when present) the independent-atlas replication count the
    safety-essential class keyed on — e.g. "kidney proximal tubule cell (3 atlases)". Populated
    whenever an essential hit fired (critical_organ_liability OR origin_tissue_liability), so the
    named liability is preserved even when a coarser veto arm wins the verdict LABEL (the masking fix)."""
    cls = (sc_normal or {}).get("sc_normal_safety_essential_class")
    if cls not in ("critical_organ_liability", "origin_tissue_liability"):
        return None
    cell = sc_normal.get("sc_normal_essential_max_cell_type")
    if not cell:
        return None
    tissue = sc_normal.get("sc_normal_essential_max_tissue")
    n_atlas = sc_normal.get("sc_normal_essential_n_datasets_reliable")
    where = f"{tissue} {cell}" if tissue else str(cell)
    detail = where
    if isinstance(n_atlas, int) and n_atlas > 0:
        detail += f" ({n_atlas} atlas{'es' if n_atlas != 1 else ''})"
    return detail


def _selectivity_tension_extra(headline: dict):
    """The sharpest cross-cutting selectivity caveat the per-axis claim conflicts don't already carry:
    the normal-breadth VETO downgrade. The resolved selectivity_class (post-veto) differs from the raw
    axis-A class ONLY when a veto fired — the per-axis WIN conflict keys on the RAW axis-A class (still
    'strong_tumor_selective' for a TROP2-style gene), so the downgrade itself would otherwise be
    invisible to rank_tension. Severity 4 (> the max signal tier 3) makes the KILL veto win the single
    tension slot; the selectivity-preserving named-organ flag rides at severity 3."""
    resolved = headline.get("selectivity_class")
    liability = headline.get("sc_normal_liability_detail")   # named organ+cell, or None (masking-safe)
    if resolved == "selective_but_stromal_confound":
        return {"text": ("axis-A selective in bulk but single-cell attribution shows the signal is "
                         "CAF/stroma-driven, NOT malignant-cell-intrinsic — a false window for "
                         "tumor-cell-targeted modalities (stromal-confound veto)"),
                "source": "stromal_confound_veto", "severity": 4}
    if resolved == "selective_but_broadly_normal":
        # The window KILL won the LABEL, but if the sc-normal arm ALSO flagged a named critical organ,
        # surface it here so the masked liability is not discarded (the de-anonymization masking fix).
        extra = f"; also flags a critical-organ single-cell liability ({liability})" if liability else ""
        return {"text": ("selective vs tissue-of-origin but no therapeutic window vs the worst critical "
                         f"normal — broadly-normal liability (normal-breadth veto){extra}"),
                "source": "normal_breadth_veto", "severity": 4}
    if resolved == "selective_with_normal_liability":
        named = f" in {liability}" if liability else ""
        return {"text": (f"tumor-selective but with a critical-organ normal-tissue liability{named} — "
                         "named-organ safety flag (severity owned by on-target-safety-liability + "
                         "modality-fit)"),
                "source": "normal_liability_flag", "severity": 3}
    return None


_SELECTIVITY_HEADLINE_SPEC = HeadlineSpec(
    gate="selectivity",
    axis_labels={"WIN": "tumor-vs-normal window", "DIST": "distributional separation",
                 "INT": "tumor-cell-intrinsic", "SAFE": "normal-tissue window"},
    axis_keys=("WIN", "DIST", "INT", "SAFE"),
    critical_axes=("WIN",),   # WIN (the tumor-vs-normal window) is THE decision-critical selectivity axis
    verdict_label=lambda v: _SELECTIVITY_VERDICT_PHRASE.get(
        v, str(v).replace("_", " ").strip().capitalize()),
    tension_extra=_selectivity_tension_extra,
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed selectivity headline. Reads the
    RESOLVED selectivity_class (post-veto — the audit spine) + the verdict-inert claim_vector /
    key_signals. No CERTAINTY_MODEL sidecar exists, so confidence is derived weakest-link. Never moves
    the spine."""
    v = headline.get("selectivity_class")
    return build_headline(headline, headline.get("claim_vector"), headline.get("key_signals"),
                          spec=_SELECTIVITY_HEADLINE_SPEC, verdict_token=v,
                          driving_rule_id=headline.get("driving_rule_id"),
                          verdict_polarity=_selectivity_verdict_polarity(v))


# ── (strength, certainty) SIDECAR — 2nd axis after the dependency reference (CERTAINTY_MODEL.md).
#    ADDITIVE + verdict-INERT: computed beside the selectivity verdict from the tvn card's numeric
#    provenance + the VERDICT-DISJOINT CPTAC-protein corroboration; never alters selectivity_class,
#    the veto, or the gate. Reviewed per-axis design (4-agent certainty panel 2026-08-24) — NOT a
#    mechanical port (percentile-crossing was REJECTED as corroboration: it re-stats the SAME recount3
#    RNA the verdict uses = pseudo-replication; the CPTAC protein card is an independent assay+cohort).
_ORD = {"low": 0, "medium": 1, "high": 2}
# The verdict-DISJOINT corroboration card this axis reads (cross-checked against
# target-contracts vocabularies/certainty_corroboration.yaml by test_certainty_corroboration_matches_manifest,
# so the manifest and the Python source cannot drift — the check the disjointness validator can't make).
_CERTAINTY_CORROBORATION_CARDS = frozenset({"tumor-protein-abundance-cptac"})
_SEL_STRONG_POS = {"strong_tumor_selective"}
_SEL_MOD_POS = {"modest_tumor_selective"}
_SEL_WEAK_POS = {"field_effect_tumor_selective", "selective_with_normal_liability"}
_SEL_NEG = {"not_selective", "selective_but_broadly_normal", "selective_but_stromal_confound"}  # measured negative / veto KILL (SAFE or INT)
_SEL_NONE = {"discordant_across_comparators", "not_informative", "insufficient", "data_unavailable", None}
# decision-relevant (verdict-bearing) cards — the veto instruments are Python-applied, not resolver rungs,
# but they ARE verdict-precedence, so unknown_mass counts them (CERTAINTY_MODEL: measured coverage-gap).
_SEL_DECISION_CARDS = ("tumor-vs-normal-selectivity", "modality-therapeutic-window",
                       "sc-normal-celltype-expression")


def _selectivity_strength(v) -> str:
    if v in _SEL_STRONG_POS:
        return "strong_positive"
    if v in _SEL_MOD_POS:
        return "moderate_positive"
    if v in _SEL_WEAK_POS:
        return "weak_positive"
    if v in _SEL_NEG:
        return "negative"
    return "none"


def _sel_coverage(cells_ran, n_tumor, comparator_concordance=None) -> str:
    """Comparator-breadth power keyed on GENUINE independent comparator families. cells_ran counts cells
    A (TCGA-adjacent raw) + B (its ComBat re-run) + C (GTEx), but A and B are the SAME tumor-vs-adjacent
    comparison, so a 3-cell run spans at most TWO independent comparator families (adjacent, GTEx). Base
    the tier on comparator_concordance (adjacent-family vs GTEx-family agreement) so an adjacent-only 3/3
    is `medium`, not `high`:
      concordant (both families agree) & n_tumor>=10 -> high ; single_comparator (one family) -> medium ;
      discordant -> low. Falls back to the cell-count tier only when concordance is unknown (older
      summaries). cells_ran in {0,None} feeds unknown_mass, not a tier. Verdict-inert (a certainty tier)."""
    if comparator_concordance == "concordant":
        return "high" if (not isinstance(n_tumor, (int, float)) or n_tumor >= 10) else "medium"
    if comparator_concordance == "single_comparator":
        return "medium"          # only one INDEPENDENT comparator family reached significance
    if comparator_concordance == "discordant":
        return "low"
    # concordance unknown → fall back to the legacy cell-count breadth
    if not isinstance(cells_ran, (int, float)) or cells_ran < 1:
        return "low"
    if cells_ran >= 3 and (not isinstance(n_tumor, (int, float)) or n_tumor >= 10):
        return "high"
    if cells_ran >= 2:
        return "medium"
    return "low"


def _sel_corroboration(concordance) -> str:
    """VERDICT-DISJOINT CPTAC-protein corroboration (independent assay+cohort). concordant -> high;
    protein measured-but-not-significant -> medium; discordant -> low; protein unmeasured -> `unmeasured`
    (drops out of the level min — absence is ignorance, carried in unknown_mass, not disagreement)."""
    c = str(concordance or "")
    if c == "rna_protein_concordant":
        return "high"
    if c == "protein_not_significant":
        return "medium"
    if c == "rna_protein_discordant":
        return "low"
    return "unmeasured"


def _sel_unknown_mass(cards) -> float:
    blind = 0
    for cid in _SEL_DECISION_CARDS:
        s = card_summary(cards, cid)
        primary = (s or {}).get("selectivity_class") or (s or {}).get("therapeutic_window_class") \
            or (s or {}).get("sc_normal_safety_essential_class")
        if not s or (s.get("_missing")) or primary in ("data_unavailable", None):
            blind += 1
    return round(blind / len(_SEL_DECISION_CARDS), 4)


def _strength_certainty(cards, fired=None, verdict_pair=None) -> dict:
    """Fan-out SIDECAR hook (CERTAINTY_MODEL) — mirrors functional-requirement's. Standalone-callable."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    tvn = card_summary(cards, "tumor-vs-normal-selectivity") or {}
    protein = card_summary(cards, "tumor-protein-abundance-cptac") or {}
    concordance = _rna_protein_tvn_concordance(
        tvn.get("dominant_direction"), protein.get("protein_effect_size"), protein.get("protein_bh_q_value"))
    cells_ran, n_tumor = tvn.get("cells_ran"), tvn.get("n_tumor")
    coverage = _sel_coverage(cells_ran, n_tumor, tvn.get("comparator_concordance"))
    corroboration = _sel_corroboration(concordance)
    components = [coverage] + ([corroboration] if corroboration != "unmeasured" else [])
    level = min(components, key=lambda c: _ORD[c]) if components else "low"
    if v in _SEL_NONE:
        level = "low"
    from _skills_common.signals_first import certainty_composite
    strength = _selectivity_strength(v)
    return {
        "strength": strength,
        "certainty": {"level": level, "coverage": coverage, "corroboration": corroboration,
                      "unknown_mass": _sel_unknown_mass(cards)},
        # continuous portfolio-ranking primitive (verdict-inert; a NAMED projection, not canonical)
        "composite": certainty_composite(strength, level),
        "composite_basis": ("certainty-discounted selectivity strength = peak signal tier × weakest-link "
                            "certainty; a NAMED [0,1] portfolio-ranking projection, not a canonical verdict"),
        "provenance": {"cells_ran": cells_ran, "n_tumor": n_tumor, "rna_protein_tvn_concordance": concordance,
                       "comparator_concordance": tvn.get("comparator_concordance")},
        "_model_ref": "CERTAINTY_MODEL.md#selectivity",
    }


# ── FACTORED-RECORD SHADOW (M1) — the selectivity per-axis builder. VERDICT-INERT: surfaced by the
#    fan-out into decision.claim_record_shadow.selectivity, consumed by NOTHING. Maps the selectivity
#    verdict (post normal-breadth veto) onto the factored record, carrying the REAL magnitude
#    (max_abs_log2fc — the tumor-vs-normal window is a genuine continuous measure). Mirrors
#    _strength_certainty. NOTE: state may be a Python-veto verdict outside the resolver enum
#    (selective_but_broadly_normal / selective_with_normal_liability) — fine at M1 (the record schema
#    checks a token pattern, not the per-axis enum; contracts invariant C's augmented set is an M3 item).
_SEL_STRENGTH_TO_LEVEL = {
    "strong_positive": "strong", "moderate_positive": "moderate",
    "weak_positive": "weak", "negative": "moderate", "none": "none",
}
_SEL_OPEN_WORLD = {"data_unavailable", None}
_SEL_MEASURED_INCONCLUSIVE = {"discordant_across_comparators", "not_informative", "insufficient"}
# boundary-aligned max|log2FC| cutpoints each positive verdict is DEFINED on (card thresholds).
_SEL_LOG2FC_CUT = {"strong_tumor_selective": 1.5, "modest_tumor_selective": 0.5}


def _sel_availability(v) -> str:
    if v in _SEL_OPEN_WORLD:
        return "not_wired"                       # open-world → assembler forces unknown/neutral
    if v in _SEL_MEASURED_INCONCLUSIVE:
        return "insufficient"                    # measured but underpowered / inconclusive
    if v in _SEL_NEG:
        return "measured_negative"               # measured non-selective / broad-normal (veto KILL)
    return "measured_positive"


def _sel_direction(v) -> str:
    if v in _SEL_STRONG_POS or v in _SEL_MOD_POS or v in _SEL_WEAK_POS:
        return "supports"
    if v in _SEL_NEG:
        return "opposes"
    return "neutral"


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — standalone, mirrors _strength_certainty's call shape."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    sc = _strength_certainty(cards, fired=fired, verdict_pair=verdict_pair)
    level = _SEL_STRENGTH_TO_LEVEL.get(_selectivity_strength(v), "none")
    # carry the continuous tumor-vs-normal window as the magnitude value when we made a real call, PLUS
    # distance_to_cut = how far max|log2FC| cleared the boundary the verdict is defined on (strong>=1.5,
    # modest>=0.5; see cards/tumor-vs-normal-selectivity.card.yaml). A small distance = a knife-edge call
    # (the borderline consumer reads this to flag over-precision — a token that hard-cuts a near-boundary
    # continuous value). Late, non-destructive: the raw value + its distance are retained on the record.
    magnitude = {"level": level}
    max_log2fc = (card_summary(cards, "tumor-vs-normal-selectivity") or {}).get("max_abs_log2fc")
    if level != "none" and isinstance(max_log2fc, (int, float)):
        magnitude = {"level": level, "value": float(max_log2fc), "scale": "log2fc"}
        cut = _SEL_LOG2FC_CUT.get(v)
        if cut is not None:
            magnitude["distance_to_cut"] = round(float(max_log2fc) - cut, 4)
    return assemble_claim_record(
        axis="selectivity",
        state=(v or "insufficient"),
        direction=_sel_direction(v),
        availability=_sel_availability(v),
        magnitude=magnitude,
        certainty=sc["certainty"],
        fired=fired,
        cards=cards,
    )


def _headline(cards, fired, verdict_pair):
    # Fetch each card summary once (card_summary scans the card list, so look up by id, not position —
    # robust to card order — and reuse the result rather than re-scanning per field).
    def _summary(cid):
        return card_summary(cards, cid)
    tvn = _summary("tumor-vs-normal-selectivity")             # aggregate axis-A verdict
    pcx = _summary("tumor-vs-normal-percentile-crossing")     # per-sample corroboration
    purity = _summary("expression-purity-confound")
    density = _summary("surface-abundance-density")
    protein_tvn = _summary("tumor-protein-abundance-cptac")   # RNA→protein corroboration (verdict-inert)
    protein_tvn_tphp = _summary("tumor-vs-normal-protein-abundance-tphp")  # RNA→protein corrob, TPHP DIA-MS (verdict-inert)
    window = _summary("modality-therapeutic-window")         # NORMAL-BREADTH VETO instrument (window arms)
    sc_normal = _summary("sc-normal-celltype-expression")     # veto instrument (normal side)
    sc_tumor = _summary("tumor-scrna-celltype-expression")    # tumor side, single-cell
    spatial_rna = _summary("spatial-region-rna-expression")
    spatial_coloc = _summary("spatial-tumor-normal-colocalization")
    spatial_protein = _summary("spatial-surface-protein-abundance")

    # RESOLVED verdict from _verdict (includes any normal-breadth veto downgrade). The headline
    # selectivity_class is the resolved value — a veto-downgraded target reads
    # selective_but_broadly_normal — while the raw pre-veto axis-A class is preserved separately for
    # transparency/audit (and so the synthesis narrator cannot over-claim off the pre-veto class).
    resolved_verdict, resolved_driving = (verdict_pair or (tvn.get("selectivity_class"), None))
    hl = {
        "selectivity_class":  resolved_verdict,               # RESOLVED (post-veto) — the audit spine
        "driving_rule_id":    resolved_driving,               # the rule that set it (e.g. the veto rule)
        "axis_a_selectivity_class": tvn.get("selectivity_class"),  # raw tumor-vs-origin class (pre-veto)
        "cells_supporting":   tvn.get("cells_supporting"),
        "cells_ran":          tvn.get("cells_ran"),
        "dominant_direction": tvn.get("dominant_direction"),
        "discordant":         tvn.get("discordant"),
        "sig_all_cells":      tvn.get("sig_all_cells"),
        # Genuine cross-comparator agreement (TCGA-adjacent family A+B vs GTEx family C): concordant /
        # discordant / single_comparator. cells_supporting counts cells A (raw) + B (ComBat re-run of A)
        # as TWO votes of the SAME tumor-vs-adjacent comparison, so a 3/3 support count can rest on ONE
        # independent comparator family. This field is the honest breadth signal; the claim_vector WIN
        # corroboration + the certainty coverage cap on it (verdict-inert — the resolver keys on
        # selectivity_class, never on comparator_concordance).
        "comparator_concordance": tvn.get("comparator_concordance"),
        "max_abs_log2fc":     tvn.get("max_abs_log2fc"),
        "data_schema":        tvn.get("_schema"),
        # Relative-selectivity context: where this gene's fold-change ranks among ALL genes in the
        # indication. Display facet, verdict-inert (also read by the synthesis prompt).
        "selectivity_allgene_percentile":       tvn.get("selectivity_allgene_percentile"),
        "selectivity_allgene_percentile_class": tvn.get("selectivity_allgene_percentile_class"),
        # Per-sample percentile-crossing (namespaced to avoid the selectivity_class collision):
        "percentile_crossing_class":       pcx.get("selectivity_class"),
        "fraction_tumor_above_normal_p95": pcx.get("fraction_tumor_above_normal_p95"),
        "distribution_overlap_tumor_normal": pcx.get("distribution_overlap_tumor_normal"),
        # Purity-confound facet (verdict-inert): is the selectivity signal tumor-cell-intrinsic or
        # driven by stromal/immune microenvironment content the bulk DESeq2 design can't separate?
        "purity_confound_class":       purity.get("purity_confound_class"),
        "expression_purity_pearson_r": purity.get("expression_purity_pearson_r"),
        # Absolute-density facet (verdict-inert): Tier-1 calibrated copies/cell + floor standing +
        # modality-viability flags. below_tce_floor is a MODALITY caveat, not a downgrade (CD19
        # counterexample). density_floor_verdict == 'unmeasured' for un-anchored targets.
        "absolute_surface_density_class":   density.get("absolute_density_class"),
        "absolute_copies_per_cell":         density.get("absolute_copies_per_cell"),
        "absolute_density_grade":           density.get("absolute_density_grade"),
        "density_floor_verdict":            density.get("density_floor_verdict"),
        "is_tce_viable":                    density.get("is_tce_viable"),
        "is_adc_high_payload_viable":       density.get("is_adc_high_payload_viable"),
        # RNA→PROTEIN corroboration facet (verdict-inert): does the tumor-vs-normal signal hold at the
        # protein layer? protein_effect_size = median_log2_tumor - median_log2_normal (CPTAC per-cohort
        # TMT-MS). rna_protein_tvn_concordance is a DERIVED, spine-inert read (does the protein direction
        # agree with the RNA dominant_direction at BH q<0.05?) — surfaces the RNA-up/protein-flat
        # false-positive the aggregate RNA card cannot see (its own caveat #5).
        "protein_tumor_vs_normal_effect_size": protein_tvn.get("protein_effect_size"),
        "protein_tumor_vs_normal_q_value":     protein_tvn.get("protein_bh_q_value"),
        "rna_protein_tvn_concordance":         _rna_protein_tvn_concordance(
            tvn.get("dominant_direction"),
            protein_tvn.get("protein_effect_size"),
            protein_tvn.get("protein_bh_q_value")),
        # TPHP DIA-MS RNA→PROTEIN corroboration facet (verdict-inert), PARALLEL to the CPTAC block above.
        # Same CPTAC-aligned field names → the SAME _rna_protein_tvn_concordance projection is reused,
        # unchanged, over the TPHP card summary. Broadens protein corroboration to 22 carcinoma cohorts
        # (several outside CPTAC). Namespaced (_tphp) so it never collides with the CPTAC facet; spine byte-stable.
        "protein_tumor_vs_normal_tphp_effect_size": protein_tvn_tphp.get("protein_effect_size"),
        "protein_tumor_vs_normal_tphp_q_value":     protein_tvn_tphp.get("protein_bh_q_value"),
        "protein_tumor_vs_normal_tphp_cohort":      protein_tvn_tphp.get("cohort"),
        "rna_protein_tvn_concordance_tphp":         _rna_protein_tvn_concordance(
            tvn.get("dominant_direction"),
            protein_tvn_tphp.get("protein_effect_size"),
            protein_tvn_tphp.get("protein_bh_q_value")),
        # Modality-therapeutic-window facet — the NORMAL-BREADTH WINDOW veto's own inputs, surfaced for
        # transparency (the card is verdict-DRIVING via the window arms: therapeutic_window_class ==
        # no_therapeutic_window / full_normal_window_class == no_full_normal_window each fire a KILL
        # downgrade to selective_but_broadly_normal — the housekeeping GAPDH / TROP2 broadly-normal
        # archetype). Without this fetch therapeutic_window_class was NULL in every headline, so the Q5
        # "gate" leading-graphic row read "therapeutic window n/a" and the SAFE claim axis + synthesis
        # facet could not see the window KILL. Display + feeds the SAFE claim axis; the resolver spine
        # (set by _verdict via the shared clamp over `fired`) is unchanged.
        "therapeutic_window_class":         window.get("therapeutic_window_class"),
        "full_normal_window_class":         window.get("full_normal_window_class"),
        "window_class":                     window.get("window_class"),
        "max_essential_normal_organ":       window.get("max_essential_normal_organ"),
        "window_ratio_essential":           window.get("window_ratio_essential"),
        # Single-cell (NORMAL side) facet — the sc-normal veto's own inputs, surfaced for transparency.
        # This card is verdict-DRIVING via the veto (sc_normal_safety_essential_class ==
        # critical_organ_liability), but a reader of decision['headline'] alone could not otherwise see
        # WHICH normal cell type / organ drove (or nearly drove) a veto. Display; the spine is byte-stable.
        "sc_normal_expression_class":       sc_normal.get("sc_normal_expression_class"),
        "sc_normal_safety_essential_class": sc_normal.get("sc_normal_safety_essential_class"),
        "sc_normal_max_detection_cell_type": sc_normal.get("max_detection_cell_type"),
        "sc_normal_max_detection_fraction": sc_normal.get("max_detection_fraction"),
        # NAMED essential-cell driver of the veto (analysis-methods #572): the organ + cell type the
        # safety-essential class actually keyed on — NOT the pooled max_detection_cell_type above (which
        # can name a non-essential epithelial cell). This de-anonymizes the clamp: the headline/narrator
        # can now say "kidney proximal tubule (3 atlases)" instead of an anonymous liability flag.
        "sc_normal_essential_max_cell_type": sc_normal.get("sc_normal_essential_max_cell_type"),
        "sc_normal_essential_max_tissue":   sc_normal.get("sc_normal_essential_max_tissue"),
        "sc_normal_essential_max_detection_fraction": sc_normal.get("sc_normal_essential_max_detection_fraction"),
        "sc_normal_essential_n_datasets_reliable": sc_normal.get("sc_normal_essential_n_datasets_reliable"),
        # Abundance at the liability-anchor cell (merged #571) — previously emitted+declared but consumed
        # by NO skill; surface it so a low-abundance normal footprint (FOLR1-class) is visible next to the
        # liability. + the single-cell tumor-vs-normal window denominator (the positive atlas use).
        "sc_normal_abundance_class":        sc_normal.get("sc_normal_abundance_class"),
        "sc_normal_ceiling_detection_fraction": sc_normal.get("sc_normal_ceiling_detection_fraction"),
        # Human-readable named-organ liability string, populated whenever an essential-cell hit exists —
        # INDEPENDENT of which veto arm won the verdict. This is the masking fix: when a coarser window
        # KILL outranks the sc-normal arm (e.g. TROP2), the named kidney liability was discarded entirely;
        # now it survives as a caveat the narrator/headline can still surface.
        "sc_normal_liability_detail":       _sc_normal_liability_detail(sc_normal),
        # The FULL safety-essential-cell set {cell_type: median_det}, not just the argmax. The single
        # max_detection_cell_type is a pooled detection argmax over all surveyed cell types, so for a
        # broadly-expressed target the large brain shard (172 cell types) usually wins it — asserting one
        # "decisive organ" hides co-flagged essential organs (e.g. erythroid/MEP for CD47). Surface the
        # whole set so the narrative enumerates ALL flagged essential cell types. Verdict-inert.
        "sc_normal_safety_essential_flags": sc_normal.get("safety_essential_flags"),
        "sc_normal_n_cell_types_above_20pct": sc_normal.get("n_cell_types_above_20pct"),
        # Single-cell (TUMOR side): resolves the purity confound at single-cell resolution — is the
        # selective bulk signal malignant-cell-intrinsic or stroma/CAF-driven? malignant_detection_fraction
        # high + caf_vs_malignant_class == caf_low → real, tumor-cell-intrinsic (the CEACAM5/COADREAD read:
        # 0.76 malignant vs 0.03 stromal). The stromal_confound_class is VERDICT-DRIVING: stromal_confounded
        # fires tvn-stromal-confound-veto → the _verdict clamp downgrades a selective axis-A call to
        # selective_but_stromal_confound (the INT-axis KILL). Surfaced here for transparency (the resolved
        # spine is set by _verdict via the shared clamp over `fired`).
        "sc_stromal_confound_class":        sc_tumor.get("stromal_confound_class"),
        "sc_tumor_expression_class":        sc_tumor.get("sc_expression_class"),
        "sc_malignant_detection_fraction":  sc_tumor.get("malignant_detection_fraction"),
        "sc_top_microenvironment_compartment":       sc_tumor.get("top_microenvironment_compartment"),
        "sc_top_microenvironment_detection_fraction": sc_tumor.get("top_microenvironment_detection_fraction"),
        "sc_caf_vs_malignant_class":        sc_tumor.get("caf_vs_malignant_class"),
        "sc_tce_homogeneity_class":         sc_tumor.get("tce_homogeneity_class"),
        # In-situ spatial facets (verdict-inert): deconvolution-free tumour-compartment confirmation
        # (region RNA) + bystander-adjacency-to-normal-epithelium risk (colocalization) + protein-layer
        # spatial enrichment. data_unavailable where the spatial atlas doesn't cover the indication.
        "spatial_rna_class":                spatial_rna.get("spatial_rna_class"),
        "spatial_tumour_vs_tme_delta":      spatial_rna.get("tumour_vs_tme_delta"),
        "spatial_coloc_class":              spatial_coloc.get("spatial_coloc_class"),
        "spatial_normal_epithelium_adjacency_fraction": spatial_coloc.get("normal_epithelium_adjacency_fraction"),
        "spatial_protein_class":            spatial_protein.get("spatial_protein_class"),
    }
    # Additive, verdict-INERT: the claim vector (WIN/DIST/INT/SAFE signal×corroboration) + a brief
    # cited key-signals read — the WITHIN-lens evidence integration this subskill owns, built on the
    # SHARED claim_vector_core contract (tumor-selectivity is the third concrete after presence +
    # dependency). Both are projections over the headline just built; they NEVER touch the
    # selectivity_class spine or the normal-breadth veto (byte-stable, frozen by the CEACAM5/TACSTD2
    # replay guard). See _skills_common/selectivity_claims.py + claim_vector_core.py.
    hl["claim_vector"] = selectivity_claim_vector(hl, cards)
    hl["key_signals"] = selectivity_key_signals(hl, cards)
    # VERDICT-INERT: when the resolved class is a coverage-GAP token but the claim vector carries a
    # decisive measured signal (e.g. FAP = strongly present but stroma-driven → not_informative), name
    # it so the composed profile need not treat it as an unmeasured gap. None otherwise. Byte-stable spine.
    hl["measurement_caveat"] = _measurement_caveat(hl)
    # The 8-question LEADING GRAPHIC (Q × primary-signal / supporting / confidence) — the selectivity
    # analogue of presence's question_table, rendered by the SHARED render_question_table_html. A
    # verdict-INERT projection over the headline + claim_vector (WIN/DIST/INT/SAFE); never touches the
    # selectivity_class spine or the normal-breadth veto.
    hl["question_table"] = selectivity_question_table(hl, cards)
    # Canonical HEADLINE block (verdict + confidence + top tension) — the concise, consumer-facing headline
    # message, as deterministic text + a renderer-agnostic hero payload. A verdict-INERT projection over the
    # resolved selectivity_class + the claim_vector / key_signals just built; best-effort (a formatting/read
    # fault must NEVER discard the selectivity spine already fully built in `hl`, matching tumor-presence /
    # functional-requirement's degrade-on-exception discipline).
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the ONE cross-skill output shape, from the
    # RESOLVED (post-veto) selectivity_class + claim_vector + headline_block + question_table just built.
    # tumor-selectivity is a GATING skill (∈ target-profile _SHORT_TO_GATE) and — UNLIKE the earlier
    # adopters — carries genuine VETO verdicts, so it passes canonical_polarity_override="killer" for the
    # two KILL outcomes (broadly_normal / stromal_confound) so the killer distinction survives the helper's
    # 3-band→canonical floor. Best-effort + verdict-INERT.
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        _v = hl.get("selectivity_class")
        hl["skill_report"] = build_skill_report(
            role=ROLE_GATING,
            verdict=_v,
            driving_rule_id=hl.get("driving_rule_id"),
            headline_block=hl.get("headline_block"),
            claim_vector=hl.get("claim_vector"),
            question_table=hl.get("question_table"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
            canonical_polarity_override=("killer" if _v in _SELECTIVITY_KILLER_VERDICTS else None),
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        hl["skill_report"] = None
    return hl


# The uniform opt-in the target-profile fan-out looks for via getattr(module, "_synthesis_facet")
# (mirrors tumor-presence + functional-requirement). Lifts tumor-selectivity's claim_vector (the
# WIN/DIST/INT/SAFE SIGNAL decomposition) + key_signals to the composed synthesis, closing a gap where
# claim_vector was BUILT here but never surfaced to the cross-lens layer. VERDICT-INERT: reuses
# _headline (single source of truth); the fan-out treats an absent/failed facet as no-facet, and nothing
# here enters `fired` or the resolver. The per-axis certainty roll-up is the separate certainty_by_axis
# sidecar, NOT this facet (CERTAINTY_MODEL — this is the SIGNAL half).
_SYNTHESIS_FACET_KEYS = (
    "selectivity_class", "driving_rule_id", "axis_a_selectivity_class",
    "dominant_direction", "discordant",
    "selectivity_allgene_percentile_class", "purity_confound_class",
    "rna_protein_tvn_concordance",
    "sc_normal_safety_essential_class",              # the veto input (why a target down-graded)
    "claim_vector", "key_signals",
    "measurement_caveat",   # verdict-inert: coverage-gap class token that actually rests on a measured signal (stromal false window)
    # carry the 8-question leading table + the tumor-vs-normal WINDOW gate fields so the
    # composed target-profile dashboard can render the "Selectivity at a glance" leading table. All are
    # produced by _headline (single source of truth); absent ones project to None (verdict-inert).
    "question_table",
    "cells_supporting", "cells_ran", "max_abs_log2fc",
    "therapeutic_window_class", "sc_normal_max_detection_cell_type", "sc_normal_safety_essential_flags",
    # the NAMED sc-normal essential-cell liability (de-anonymized organ+cell+atlases) + the masking-safe
    # detail string + abundance at the liability cell — so the synthesis narrator names the organ.
    "sc_normal_essential_max_cell_type", "sc_normal_essential_max_tissue", "sc_normal_liability_detail",
    "sc_normal_abundance_class",
    "percentile_crossing_class", "fraction_tumor_above_normal_p95", "distribution_overlap_tumor_normal",
    "selectivity_allgene_percentile",
    "sc_tumor_expression_class", "sc_malignant_detection_fraction", "sc_caf_vs_malignant_class",
    "sc_stromal_confound_class",   # the INT-axis veto input (why a stroma-driven target down-graded)
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
    # the UNIFIED cross-skill output object (docs/UNIFIED_OUTPUT_CONTRACT.md) — Wave-3 skill_report
    # adoption (7th gating adopter; first with a killer-verdict override)
    "skill_report",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT selectivity facet for the composed target-profile synthesis prompt.
    Reuses `_headline` (single source of truth) and returns the reconciliation-relevant subset — the
    resolved selectivity verdict + the WIN/DIST/INT/SAFE claim_vector SIGNAL decomposition + a brief
    cited key-signals read. Never moves the verdict; safe to omit (fan-out treats absence as no-facet)."""
    h = _headline(cards, fired, verdict_pair)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = (
        "Deterministic selectivity facet from tumor-selectivity (a FACET, not a gate; the selectivity "
        "verdict + normal-breadth veto are owned by the shared resolver and are verdict-inert to this "
        "projection). claim_vector is the SIGNAL decomposition — WIN tumor-vs-normal window / DIST "
        "distribution-crossing / INT tumor-cell-intrinsic (purity/single-cell) / SAFE normal-liability, "
        "each a signal tier. The per-axis certainty roll-up is the separate certainty_by_axis sidecar.")
    return facet
# ── SUBTYPE PANORAMA (--subtypes; DESCRIPTIVE / verdict-INERT) ────────────────────────────
# The target_subtype-grain crossing card. Resolved ONLY when the run receives --subtypes AND this fn
# is passed to run_wired_skill; its cards are appended to the package + the panorama merged into the
# headline, but NEVER enter `fired` — the selectivity_class spine + normal-breadth veto are
# byte-identical with or without --subtypes (mirrors functional-requirement's dependency panorama).
SUBTYPE_CARDS = ["tumor-vs-normal-percentile-crossing-by-subtype"]
_CROSSING_VARIES_DELTA = 0.25   # fraction-range span flagging subtype-specific crossing (mirrors the card)


def _resolve_selectivity_subtype_panorama(target: str, indication: str | None, subtypes: list) -> dict:
    """DESCRIPTIVE per-subtype percentile-crossing selectivity panorama — resolve
    tumor-vs-normal-percentile-crossing-by-subtype across the requested strata (e.g. MSI_H, MSS). The
    card is a COMPUTE-ALL panorama dispatcher (fans out over every stratum internally), so a queried
    subtype spotlights but does not scope the computation. Mirrors functional-requirement's
    _resolve_dependency_subtype_panorama; NO resolver rung is touched (verdict spine byte-stable).
    Reads the card's ACTUAL emitted fields (per_subgroup_metrics: stratum_id / percentile_crossing_
    class / evidence_state / fraction_tumor_above_normal_p95 / distribution_overlap_tumor_normal)."""
    subgroup_context = {"resolved_strata_ids": list(subtypes), "catalog_status": "resolved_active"}
    sub_cards = resolve_cards(SUBTYPE_CARDS, target, indication, subgroup_context=subgroup_context)
    xs = next((c for c in sub_cards
               if c["card_id"] == "tumor-vs-normal-percentile-crossing-by-subtype"), None)
    summary = (xs or {}).get("summary") or {}
    per_subgroup = summary.get("per_subgroup_metrics") or []
    measured = [r for r in per_subgroup if r.get("evidence_state") == "measured"
                and r.get("fraction_tumor_above_normal_p95") is not None]

    # SECOND subtype view (complementary): the aggregate FOUR-CELL DESeq2 sensitivity per stratum
    # (product {indication}-dge-tumor-vs-normal-sensitivity-by-subgroup-v1), resolved by re-reading the
    # POOLED tumor-vs-normal-selectivity card WITH subgroup_context — the DUAL_GRAIN arm in
    # _live_readers routes that to read_stratified_tumor_vs_normal_selectivity (the pooled read on the
    # verdict spine is untouched). The crossing view (above) is per-sample fraction-above-normal-p95;
    # this is the MODELED log2FC selectivity_class per stratum. DESCRIPTIVE / verdict-inert.
    dge_cards = resolve_cards(["tumor-vs-normal-selectivity"], target, indication,
                              subgroup_context=subgroup_context)
    dg = next((c for c in dge_cards if c["card_id"] == "tumor-vs-normal-selectivity"), None)
    dg_sum = (dg or {}).get("summary") or {}
    dg_per = dg_sum.get("per_subgroup_metrics") or []
    dge_by_subgroup = {
        "status":                              dg_sum.get("status"),
        "selectivity_class_by_subgroup":       dg_sum.get("selectivity_class_by_subgroup"),
        "cross_subgroup_selectivity_divergence": dg_sum.get("cross_subgroup_selectivity_divergence"),
        "cross_subgroup_delta_log2fc":         dg_sum.get("cross_subgroup_delta_log2fc"),
        "any_subgroup_strong_selective":       dg_sum.get("any_subgroup_strong_selective"),
        "per_stratum": [{"stratum": r.get("stratum"),
                         "selectivity_class": r.get("selectivity_class"),
                         "evidence_state": r.get("evidence_state"),
                         "max_abs_log2fc": r.get("max_abs_log2fc"),
                         "subgroup_n": r.get("subgroup_n")}
                        for r in dg_per],
        "_missing": bool(dg is None or dg.get("_missing")),
    }

    return {
        "cards": sub_cards + dge_cards,
        "scope_subtypes": list(subtypes),
        "subtype_selectivity_panorama": {
            # display-only flavor: does per-sample crossing selectivity vary across subtypes?
            "crossing_varies_by_subtype":        summary.get("crossing_varies_by_subtype"),
            "n_subtypes_measured":               summary.get("n_subtypes_measured"),
            "n_subtypes_strongly_enriched":      summary.get("n_subtypes_strongly_enriched"),
            "max_subtype_fraction_above_normal_p95": summary.get("max_subtype_fraction_above_normal_p95"),
            "min_subtype_fraction_above_normal_p95": summary.get("min_subtype_fraction_above_normal_p95"),
            "matched_normal_tissue":             summary.get("matched_normal_tissue"),
            "measured_strata":                   [r.get("stratum_id") for r in measured],
            "per_stratum": [{"stratum_id": r.get("stratum_id"),
                             "percentile_crossing_class": r.get("percentile_crossing_class"),
                             "evidence_state": r.get("evidence_state"),
                             "fraction_tumor_above_normal_p95": r.get("fraction_tumor_above_normal_p95"),
                             "distribution_overlap_tumor_normal": r.get("distribution_overlap_tumor_normal")}
                            for r in per_subgroup],
            "_missing": bool(xs is None or xs.get("_missing")),
            "_missing_reason": (xs or {}).get("_missing_reason"),
            # the complementary modeled-DESeq2 per-stratum selectivity view (four-cell log2FC classes)
            "dge_by_subgroup": dge_by_subgroup,
        },
    }


def _emit_skill_figures(decision, figures_root):
    """Skill-level graphics (opt-in --figures): the EXISTING selectivity evidence-strip hero (verdict
    banner + independent comparator axes incl. the normal-tissue WINDOW veto) PLUS the shared canonical
    headline hero (verdict · confidence · top tension). Complementary, not a replacement — the evidence
    strip stays. Both are additive / display-only and offline (read only decision['headline']); the
    decision.json spine is byte-identical whether or not they run."""
    return list(emit_selectivity_hero(decision, figures_root)) + \
        list(emit_headline_hero(decision, figures_root))


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
    return make_synthesize_fn(_LENS)(decision, model_id, subtype)  # migrated to generic capsule-driven engine


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
        # Opt-in --synthesize narrates through the SELECTIVITY lens (its own tool schema + prompt).
        # Two-slot / verdict-inert.
        synthesize_fn=make_synthesize_fn(_LENS),
        # Opt-in --figures skill-level HEROES: the selectivity evidence-strip (verdict banner + the
        # independent comparator axes incl. the normal-tissue WINDOW veto) AND the shared canonical
        # headline hero (verdict · confidence · top tension). Complementary; both over decision['headline'].
        # Additive / display-only; reads no S3; decision.json byte-identical whether or not they run.
        skill_figures_fn=_emit_skill_figures,
        # Opt-in --subtypes: a DESCRIPTIVE per-subtype percentile-crossing panorama (Phase B). Its
        # cards/panorama are appended; NEVER enter `fired` → selectivity_class spine byte-identical.
        subtype_panorama_fn=_resolve_selectivity_subtype_panorama,
        # Signals-first: tuned sub-group reader for the selectivity vocabulary (correct polarity).
        # Verdict-INERT — feeds subgroup_signals / the narrator.
        subgroup_classify=make_value_classifier(_SELECTIVITY_VALUE_TIERS),
        # Opt-in --literature (verdict-INERT): a published-literature read scoped to THIS skill's
        # WIN/DIST/INT/SAFE axes (via _LENS thesis/axis_labels/polarity_note + the claim_vector), grounded
        # on LIVE Europe PMC + PMID-verified, attached as decision['literature_synthesis'] and fed to the
        # --synthesize narrator as a corroboration/contradiction lane. Shared lane, reused read-only.
        literature_fn=make_literature_fn(_LENS, retrieve_fn=default_retrieve,
                                         verify_fn=verify_citations),
    ))
