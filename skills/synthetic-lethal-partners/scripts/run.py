#!/usr/bin/env python3
"""synthetic-lethal-partners — curated SL-partner annotation for a (target).

Gate-C step 2. Consumes the synthetic-lethal-partners card (SynLethDB v3, published)
and emits a sub-verdict the nomination gate's veto-suppressor keys on: an
experimentally-supported curated SL partner suppresses the pooled `non_dependent`
dependency veto → `insufficient` (SMARCA2←SMARCA4). ANNOTATION, not measurement — it
NEVER nominates (no positive_signal) and NEVER suppresses pan_essential.

Distinct sub_skill from functional-requirement (which emits the `dependency` verdict
being suppressed) — a sub_skill cannot emit both the veto and its own suppressor, so
the SL signal rides its own sub_skill `synthetic_lethal_partners`, exactly as the
biomarker-stratified suppressor rides `genomic_alteration`.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field
from _skills_common.resolver import resolve_or_raise
from _skills_common.claim_record import assemble_claim_record
from _skills_common.sl_question_table import sl_question_table
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.skill_report import build_skill_report, ROLE_DESCRIPTIVE
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import SYNTHETIC_LETHAL_PARTNERS as _LENS
from _skills_common.literature_synthesis import make_literature_fn
from _skills_common.literature_retrieval import default_retrieve, verify_citations
from _skills_common.sl_crosswalks import (
    validated_combination_precedent,
    validated_paralog_sl,
    norm_ind as _norm_ind,
    VALIDATED_COMBINATION_PRECEDENT,
    VALIDATED_PARALOG_SL,
)


SKILL_NAME = "synthetic-lethal-partners"
SKILL_VERSION = "1.1.0"  # 1.1.0 (2026-09-05, literature-and-claims arc, item #3): CREATE the
# SYNTHETIC_LETHAL_PARTNERS narrator lens (was NONE) + wire synthesize_fn + BAKE the
# --literature lane (a GENUINE 2nd channel — published SL literature vs the curated
# SynLethDB edge, UNLIKE literature-context). Verdict-INERT cited-evidence confidence
# surface — sl_partner_confidence_caveat (3-tier: computational_only_sl_edge /
# curated_sl_edge_context_unconfirmed / validated_established_synthetic_lethal
# false-demote guard) + sl_partner_provenance QUORUM. Caveats REUSE the shared
# _skills_common/sl_crosswalks validated-SL corpus + gate on EXISTING headline fields
# (NO new card-field read) → the resolver verdict + golden are UNTOUCHED
# (sl_partner_verdict / driving_rule_id byte-stable). SET literals not 2-tuples.

CARDS = ["synthetic-lethal-partners"]

QUESTION = (
    "Does {target} have a curated synthetic-lethal partner (SynLethDB v3), "
    "and is the evidence experimental — such that a pooled non-dependent "
    "CRISPR read in {indication} may be a context-conditional false negative?"
)


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (gap #5, 2026-07-20).
    The former if-chain now lives in resolvers/synthetic_lethal_partners.resolver.yaml (target-contracts),
    evaluated by the ONE interpreter both engines call. Proven byte-for-byte equivalent to
    the former if-chain by the golden-oracle test. A missing spec raises (the resolver is
    the source of truth — no silent fallback to a stale copy, which would reintroduce drift)."""
    return resolve_or_raise(fired, "synthetic_lethal_partners")


# ── FACTORED-RECORD SHADOW (M1) — the SYNTHETIC-LETHAL-PARTNERS per-axis builder. An SL partner is an
#    OPPORTUNITY (a combination strategy), so a partner SUPPORTS; its measured absence is neutral (not a
#    negative for the target itself). VERDICT-INERT: surfaced by the fan-out into
#    decision.claim_record_shadow.synthetic_lethal_partners, consumed by NOTHING. No verdict-disjoint
#    corroborator → minimal coverage-only certainty. Mirrors the other axes' hook.
def _sl_availability(v) -> str:
    if v == "data_unavailable" or v is None:
        return "not_wired"
    if v == "insufficient":
        return "insufficient"
    if v == "no_curated_sl_partner":
        return "measured_negative"  # we looked; no curated partner
    return "measured_positive"  # has_experimental / has_computational partner


def _sl_finding(v):
    """(direction, magnitude.level). Experimental SL evidence > computational."""
    if v == "has_experimental_sl_partner":
        return "supports", "strong"
    if v == "has_computational_sl_partner":
        return "supports", "moderate"
    return "neutral", "none"  # absence / insufficient / open-world


def _sl_certainty(v) -> dict:
    if v == "data_unavailable" or v is None:
        return {"level": "low", "coverage": "low", "corroboration": "unmeasured", "unknown_mass": 1.0}
    if v == "insufficient":
        return {"level": "low", "coverage": "low", "corroboration": "unmeasured", "unknown_mass": 0.5}
    return {"level": "medium", "coverage": "medium", "corroboration": "unmeasured", "unknown_mass": 0.0}


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — standalone, mirrors the other axes' hook."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    direction, level = _sl_finding(v)
    return assemble_claim_record(
        axis="synthetic_lethal_partners",
        state=(v or "insufficient"),
        direction=direction,
        availability=_sl_availability(v),
        magnitude={"level": level},
        certainty=_sl_certainty(v),
        fired=fired,
        cards=cards,
    )


# ── SL-PARTNER confidence surface (VERDICT-INERT) — the curated-SL analog of combination-and-vulnerability's
#    partner_confirmation_caveat, reusing the SHARED _skills_common/sl_crosswalks validated-SL corpus. THE
#    TRAP: a CURATED SynLethDB edge OVER-CALLS a CLINICALLY / FUNCTIONALLY VALIDATED, PORTABLE, DRUGGABLE
#    synthetic lethality. Three sub-inflations: (a) COMPUTATIONAL-ONLY — a predicted SynLethDB edge (Guo 2016
#    PMID 26516187; SynLethDB 2.0 Wang 2022 PMID 35562840) is the lowest evidence tier, no wet-lab confirmation;
#    (b) CURATED ≠ FUNCTIONAL-IN-CONTEXT — SynLethDB aggregates SL edges ACROSS cell-line contexts, and SL is
#    strongly context/genotype-dependent + frequently FAILS TO REPLICATE (O'Neil-Bailey-Hart 2017 PMID
#    28649135; penetrance barrier Ryan-Bajrami-Lord 2018 PMID 30292351), so a curated edge may not hold in THIS
#    indication; (c) KO ≠ INHIBITION — a curated SL from genetic KO removes the ENTIRE protein whereas a drug
#    inhibits ONE activity partially (Weiss-Shokat 2007 PMID 18007642), so a scaffold / non-catalytic partner
#    needs a DEGRADER (Farnaby 2019 PMID 31178587). This skill IS verdict-bearing (resolver + gate veto-
#    suppressor), so the caveats are VERDICT-INERT annotation layers over the already-emitted sl_partner_*
#    headline fields, NEVER read by the resolver: the honest discriminator is the SHARED, DISCLAIMED,
#    NON-EXHAUSTIVE curated crosswalk of clinically/functionally-validated SLs, corroborated by the
#    --literature lane + narrator. An absent (target, indication) degrades to the data-derived tier or None
#    (never a verdict change — the resolver verdict + golden are untouched). SET literals (drift guard).

_SL_PARTNER_PRESENT = {"has_experimental_sl_partner", "has_computational_sl_partner"}


def _sl_positive_substrate(hl: dict) -> bool:
    """Is there a CURATED SL partner to confidence-qualify? True when the verdict / class reports a partner,
    or an experimental/curated partner count is present. False on no_curated_sl_partner / insufficient /
    data_unavailable → the caveat is None (honest thin degrade; the resolver verdict is byte-stable)."""
    if hl.get("sl_partner_verdict") in _SL_PARTNER_PRESENT or hl.get("sl_partner_class") in _SL_PARTNER_PRESENT:
        return True
    return bool(hl.get("n_experimental_partners") or hl.get("sl_partner_count"))


def _sl_is_computational_only(hl: dict) -> bool:
    """The curated SL rests ONLY on a computational/predicted SynLethDB edge — no experimental partner."""
    comp = (
        hl.get("sl_partner_verdict") == "has_computational_sl_partner"
        or hl.get("sl_partner_class") == "has_computational_sl_partner"
    )
    no_exp = not hl.get("has_experimental_partner") and not (hl.get("n_experimental_partners") or 0)
    tier = str(hl.get("best_evidence_tier") or "").lower()
    return bool(comp or (no_exp and tier in {"computational", "predicted", "text_mining", "text-mining"}))


def _sl_partner_confidence_caveat(hl: dict, target=None, indication=None) -> dict | None:
    """CONSOLIDATED curated-SL-vs-validated confidence call (VERDICT-INERT). Precedence: the MILDER
    clinically/functionally-validated guard (iii) FIRST (BRCA↔PARP / WRN↔MSI / SMARCA4↔SMARCA2 must NOT be
    flagged) > the SHARP computational-only tier (ii) > the SHARP curated-context-unconfirmed default (i) >
    None (no curated partner → honest thin). Gates on already-emitted sl_partner_* fields + the SHARED
    validated-SL crosswalks; NEVER moves the resolver spine (verdict-INERT)."""
    if not _sl_positive_substrate(hl):
        return None  # thin / no partner → resolver verdict byte-stable

    # TIER (iii) MILDER — clinically/functionally-validated SL guard (false-demote): the (target, indication)
    # combination crosswalk OR the (target)-keyed canonical paralog-SL crosswalk.
    vc = validated_combination_precedent(target, indication)
    if vc:
        return {
            "reason": "validated_established_synthetic_lethal",
            "tier": "milder",
            "false_demote_guarded": True,
            "detail": vc,
        }
    vp = validated_paralog_sl(target)
    if vp:
        return {
            "reason": "validated_established_synthetic_lethal",
            "tier": "milder",
            "false_demote_guarded": True,
            "paralog_partner": vp[0],
            "detail": vp[1],
        }

    # TIER (ii) SHARP — computational-only predicted edge (lowest evidence tier).
    if _sl_is_computational_only(hl):
        return {
            "reason": "computational_only_sl_edge",
            "tier": "sharp",
            "false_demote_guarded": False,
            "detail": (
                "The curated SL rests ONLY on a COMPUTATIONAL / predicted SynLethDB edge (no "
                "experimental partner) — the LOWEST evidence tier (Guo 2016 PMID 26516187; SynLethDB "
                "2.0 Wang 2022 PMID 35562840), a network/ML-inferred edge with no wet-lab "
                "confirmation in any context. Treat as a hypothesis, not a validated SL; the "
                "druggability call is owned by tractability-small-molecule."
            ),
        }

    # TIER (i) SHARP — curated experimental edge, but context-aggregated + not in the validated crosswalk.
    return {
        "reason": "curated_sl_edge_context_unconfirmed",
        "tier": "sharp",
        "false_demote_guarded": False,
        "detail": (
            "The curated SynLethDB SL edge is EXPERIMENTALLY supported but is aggregated ACROSS "
            "cell-line contexts, so it may not hold in THIS indication: SL is strongly context/"
            "genotype-dependent and frequently FAILS TO REPLICATE across screens (O'Neil-Bailey-Hart "
            "2017 PMID 28649135; penetrance barrier Ryan-Bajrami-Lord 2018 PMID 30292351). It is also "
            "a curated edge — often genetic-KO-derived — and KO ≠ partial pharmacological inhibition "
            "(Weiss-Shokat 2007 PMID 18007642), so a scaffold / non-catalytic partner needs a "
            "DEGRADER not an inhibitor (Farnaby 2019 PMID 31178587). Treat as a combination "
            "HYPOTHESIS pending orthogonal / in-context confirmation; the single-target dependency "
            "MAGNITUDE is owned by functional-requirement and the druggability call by "
            "tractability-small-molecule."
        ),
    }


def _sl_partner_provenance(hl: dict, target=None, indication=None) -> dict | None:
    """QUORUM / PROVENANCE summary for the curated SL annotation (VERDICT-INERT): the SL class + partner
    count + experimental-partner count + best evidence tier + the validated-SL flags + the 'curated SynLethDB
    edge ≠ validated portable druggable SL' note. None on the thin/empty path (byte-stable)."""
    if not _sl_positive_substrate(hl):
        return None
    key = ((target or "").upper().strip(), _norm_ind(indication))
    return {
        "sl_partner_verdict": hl.get("sl_partner_verdict"),
        "sl_partner_class": hl.get("sl_partner_class"),
        "sl_partner_count": hl.get("sl_partner_count"),
        "n_experimental_partners": hl.get("n_experimental_partners"),
        "has_experimental_partner": bool(hl.get("has_experimental_partner")),
        "best_evidence_tier": hl.get("best_evidence_tier"),
        "computational_only": _sl_is_computational_only(hl),
        "validated_combination_flag": key in VALIDATED_COMBINATION_PRECEDENT,
        "validated_paralog_sl_flag": (target or "").upper().strip() in VALIDATED_PARALOG_SL,
        "provenance_note": (
            "Curated SynLethDB synthetic-lethal annotation (experimental > computational tier). "
            "A curated SL edge is CONTEXT-AGGREGATED and is NOT a validated, portable, druggable "
            "SL: SL is context/genotype-dependent + often non-replicating (Ryan-Bajrami-Lord "
            "2018 PMID 30292351), and KO ≠ pharmacological inhibition (Weiss-Shokat 2007 PMID "
            "18007642). An SL partner is a combination OPPORTUNITY; this skill never nominates "
            "the target (it rides a dependency veto-suppressor)."
        ),
    }


# ── Canonical HEADLINE block (verdict + confidence + top-tension) for the DESCRIPTIVE spine ──────────
# synthetic-lethal-partners has no claim_vector machinery (single-card veto-suppressor), so it declares
# a thin HeadlineSpec + a verdict→phrase/certainty map: the phrase is the verdict label, and confidence
# rides the CERTAINTY sidecar (derive_confidence honours it) so the block carries a MEANINGFUL confidence
# rather than the coverage-based "insufficient" a null claim_vector would yield. VERDICT-INERT projection.
_SL_HEADLINE_SPEC = HeadlineSpec(
    gate="synthetic_lethal_partners",
    axis_labels={"PARTNER": "curated SL partner", "SUPPORT": "experimental support"},
    axis_keys=("PARTNER", "SUPPORT"),
    critical_axes=("PARTNER",),
    verdict_label=lambda v: {
        "has_experimental_sl_partner": "Experimentally-supported curated SL partner",
        "has_computational_sl_partner": "Computational-only curated SL partner",
        "no_curated_sl_partner": "No curated SL partner",
        "insufficient": "Insufficient evidence for an SL-partner call",
        "data_unavailable": "SL-partner data unavailable",
    }.get(v, str(v).replace("_", " ").strip().capitalize()),
)
# Weakest-link certainty by verdict (experimental curation > computational; a curated corpus queried with
# no hit is a real-but-weak negative; the collapsed calls are honestly insufficient).
_SL_CERTAINTY_BY_VERDICT = {
    "has_experimental_sl_partner": "moderate",
    "has_computational_sl_partner": "weak",
    "no_curated_sl_partner": "weak",
    "insufficient": "insufficient",
    "data_unavailable": "insufficient",
}


def _build_headline_block(hl: dict) -> dict:
    """Descriptive headline (verdict + certainty-sidecar confidence + top-tension). The sl_partner
    confidence caveat, when present, is the top tension. Never moves the resolver verdict."""
    v = hl.get("sl_partner_verdict")
    caveat = hl.get("sl_partner_confidence_caveat")
    hb = build_headline(
        hl,
        hl.get("claim_vector"),
        hl.get("key_signals"),
        spec=_SL_HEADLINE_SPEC,
        verdict_token=v,
        certainty={"level": _SL_CERTAINTY_BY_VERDICT.get(v, "insufficient")},
    )
    if isinstance(caveat, dict) and caveat.get("detail") and not hb.get("top_tension"):
        hb["top_tension"] = {"text": caveat["detail"], "source": "sl_partner_confidence_caveat"}
    return hb


def _headline(cards, fired, verdict_pair, target=None, indication=None):
    v, drv = verdict_pair or ("insufficient", None)
    hl = {
        "sl_partner_verdict": v,
        "driving_rule_id": drv,
        "sl_partner_class": get_card_field(cards, "synthetic-lethal-partners", "sl_partner_class"),
        "sl_partner_count": get_card_field(cards, "synthetic-lethal-partners", "sl_partner_count"),
        "n_experimental_partners": get_card_field(cards, "synthetic-lethal-partners", "n_experimental_partners"),
        "has_experimental_partner": get_card_field(cards, "synthetic-lethal-partners", "has_experimental_partner"),
        "best_evidence_tier": get_card_field(cards, "synthetic-lethal-partners", "best_evidence_tier"),
    }
    # CONSOLIDATED curated-SL confidence caveat + provenance quorum (VERDICT-INERT) — the curated-SL analog of
    # combination-and-vulnerability's partner_confirmation surface, reusing the shared validated-SL crosswalks.
    # Gate on the already-emitted sl_partner_* fields + the curated crosswalk; None on the thin / validated-
    # guarded paths → the sl_partner spine + resolver verdict byte-stable. Best-effort: a fault degrades to
    # None + _enrichment_errors, never aborts the veto-suppressor spine. target / indication are OPTIONAL
    # (signature-introspected by the dispatcher) → they key the (target, indication) validated-SL guard.
    for _fld, _fn in (
        ("sl_partner_confidence_caveat", _sl_partner_confidence_caveat),
        ("sl_partner_provenance", _sl_partner_provenance),
    ):
        try:
            hl[_fld] = _fn(hl, target=target, indication=indication)
        except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
            hl.setdefault("_enrichment_errors", {})[_fld] = f"{type(exc).__name__}: {exc}"
            hl[_fld] = None
    # The compact 2-row LEADING table (Partner · Support) — a verdict-INERT projection over the just-built
    # headline (mirrors tumor-presence / tumor-selectivity). Best-effort: a formatting/read fault must
    # NEVER discard the sl_partner spine already built in `hl` (this skill is a nomination-gate veto-
    # suppressor, so its verdict must survive any display-layer fault).
    try:
        hl["question_table"] = sl_question_table(hl, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        hl["question_table"] = None
    # Canonical headline block (verdict + confidence + top tension) — the descriptive projection the
    # unified spine reads honest_phrase + confidence off. Best-effort + verdict-INERT.
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # Unified skill_report envelope (data-product lock): verdict-INERT normalizer — role DESCRIPTIVE
    # (gateless veto-suppressor; ∉ target-profile _SHORT_TO_GATE → polarity not_scored), call = the
    # sl_partner_verdict. Best-effort: a fault degrades (never aborts the veto-suppressor spine).
    try:
        _used = [c["card_id"] for c in (cards or []) if not c.get("_missing")]
        hl["skill_report"] = build_skill_report(
            role=ROLE_DESCRIPTIVE,
            verdict=hl.get("sl_partner_verdict"),
            driving_rule_id=hl.get("driving_rule_id"),
            headline_block=hl.get("headline_block"),
            question_table=hl.get("question_table"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=[c["card_id"] for c in (cards or []) if c.get("_missing")],
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert normalizer; never abort the spine
        hl.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        hl["skill_report"] = None
    return hl


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
            # NET-NEW capsule-driven narrator (generic engine + this skill's LensConfig). synthetic-lethal-partners
            # had NO lens/narrator before the literature-and-claims arc; SYNTHETIC_LETHAL_PARTNERS (mode=verdict)
            # LEADS with clinically/functionally-validated vs computational/curated-context-unconfirmed.
            synthesize_fn=make_synthesize_fn(_LENS),
            # OPTIONAL verdict-INERT LLM --literature lane: UNLIKE literature-context (whose card IS the literature),
            # a curated SynLethDB edge is orthogonal to the published SL literature, so the lane is a GENUINE second
            # channel. Europe-PMC-grounded + PMID-verified; attached as decision['literature_synthesis'] AFTER the
            # deterministic verdict and fed to the --synthesize narrator. Query terms
            # (_LENS_QUERY_TERMS["synthetic-lethal-partners"]) front-load the SL-validation / reproducibility /
            # KO-vs-inhibition discriminators. This lane cannot touch the resolver verdict (attached after it).
            literature_fn=make_literature_fn(_LENS, retrieve_fn=default_retrieve, verify_fn=verify_citations),
        )
    )
