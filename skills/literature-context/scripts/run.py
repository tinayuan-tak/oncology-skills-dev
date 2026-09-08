#!/usr/bin/env python3
"""literature-context — verdict-INERT descriptive skill (wired 2026-09-02).

Composes ONE card, cited-literature-evidence (OT europepmc co-occurrence + PubTator3 relation
direction), into a "what does the literature SAY about {target} in {indication}, with citations" read.

DESCRIPTIVE (verdict_fn=None): like target-intrinsic / translational-readiness, this skill emits no
nomination verdict — cited literature is CONTEXT/CONFIDENCE that informs the synthesis, never a gate
(RISK_ASSESSMENT_INTEGRATION.md §4). Uses the shared run_wired_skill dispatcher; skill-specific logic
reduces to CARDS + a headline callback.

PROMOTES the former cited_literature_evidence.json side-channel (the target-profile
tp_grounding.auto_cited_evidence bolt-on, now REMOVED) to a first-class fan-out member composing a
governed card — so the card/skill validators + the emission guard see it. Distinct from the sibling
literature-risk-assessment skill (live PubMed + LLM 6-dimension RISK read); this reads pinned,
catalogued products (reproducible, no LLM).
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import get_card_field
from _skills_common.dispatcher import run_wired_skill
from _skills_common.headline_core import HeadlineSpec, build_headline
from _skills_common.literature_context_claims import literature_context_claim_vector, literature_context_key_signals
from _skills_common.literature_context_question_table import literature_context_question_table
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import LITERATURE_CONTEXT as _LENS
from _skills_common.skill_report import ROLE_DESCRIPTIVE, build_skill_report

SKILL_NAME = "literature-context"
SKILL_VERSION = "1.1.0"  # 1.1.0 (2026-09-05, literature-and-claims arc, 2nd NON-standard skill after
# target-archetype #1052): CREATE the LITERATURE_CONTEXT narrator lens (was NONE)
# + wire synthesize_fn. DELIBERATE DECISION: SKIP the LLM --literature lane as
# REDUNDANT/CIRCULAR — the cited-literature-evidence card IS the Europe-PMC +
# PubTator3 literature, and default_retrieve grounds on those same two sources, so
# a lit lane would re-derive the card's own source + double-count its pmids (see
# SKILL.md "What this skill does NOT do"). Verdict-INERT cited-evidence confidence
# surface — cited_evidence_confidence_caveat (3-tier: volume_without_validated_relation
# / relation_direction_automated_or_conflicting / validated_established_relationship
# false-demote guard) + stale_literature recency note + cited_evidence_provenance
# QUORUM. Caveats gate on the EXISTING _headline fields (NO new card-field read) →
# GATELESS + verdict None + gate None byte-stable. SET literals not 2-tuples.

CARDS = [
    "cited-literature-evidence",  # OT europepmc co-occurrence (volume/recency + top cited statements)
    # + PubTator3 BioREx typed relation direction. gene×indication.
    # VERDICT-INERT descriptive literature context (composes both readers
    # via analysis-methods cited_literature_evidence.read).
]

QUESTION = (
    "What does the literature say about {target} in {indication} — co-occurrence volume/recency, "
    "the top cited statements (Open Targets europePMC), and typed relation direction (PubTator3 "
    "associate/cause/inhibit/…) — with citations?"
)


# ── CITED-EVIDENCE confidence surface (VERDICT-INERT) — the cited-literature analog of translational-
#    readiness's translational_readiness_confidence_caveat / target-archetype's archetype_confidence_caveat.
#    THE TRAP: the co-occurrence VOLUME (+ recency) and the PubTator3 BioREx typed RELATION DIRECTION
#    OVER-CALL a VALIDATED, CAUSAL, MECHANISTIC, DIRECTION-CORRECT relationship. Four sub-inflations:
#    (a) VOLUME ≠ VALIDATION — a high europePMC co-occurrence count reflects CITATION / ATTENTION / STUDY
#        bias (well-studied genes accrue mentions; the studied genome is a small, self-reinforcing minority —
#        Stoeger 2018 PMID 30226837; Edwards 2011 PMID 21307913; annotation bias — Haynes 2018 PMID 29358745;
#        hub-seeking research strategy — Rzhetsky 2015 PMID 26554009), NOT a validated/causal target–indication
#        relationship (guilt-by-association multifunctionality — Gillis & Pavlidis 2012 PMID 22479173);
#    (b) RELATION DIRECTION IS AUTOMATED + CONTEXT-FREE — PubTator3 (Wei 2024 PMID 38572754) typed edges are
#        produced by the BioREx model whose best-in-class score is 79.6% F1 on BioRED (Lai 2023 PMID 37673376;
#        Luo 2022 PMID 35849818) — i.e. ~1 in 5 relations mislabeled, before the single-sentence / context-free
#        limit — so a typed edge can be mis-typed, direction-ambiguous, CONFLICTING across papers, or a
#        single-paper in-vitro assertion, not a validated in-vivo mechanism;
#    (c) RECENCY / STALENESS — an old latest_year is a stale literature that may pre-date modern understanding;
#    (d) PLEIOTROPY / SCOPE — a high n_diseases = a promiscuous/pleiotropic target mentioned across many
#        diseases (the TP53 pattern — Kandoth 2013 PMID 24132290; a nonspecific hub, not indication-specific).
#    literature-context is GATELESS (verdict_fn=None) + TOKENLESS (no resolver) + CONTEXT-tier
#    (RISK_ASSESSMENT_INTEGRATION.md §4), so — like translational-readiness / target-archetype — these are
#    VERDICT-INERT annotation layers over the already-built VOLUME/RECENCY/RELATION headline fields, NEVER read
#    by a resolver. The caveats gate ONLY on fields the _headline ALREADY pulls (paper_disease_mentions /
#    recent_mentions / n_diseases / earliest_year / latest_year / relation_types / total_relation_publications /
#    top_cited / cited_evidence_status) → NO new card-field read (skills-only; no target-contracts / analysis-
#    methods change) → a run where the caveat is ABSENT is byte-identical. The MILDER false-demote guard is a
#    SMALL, DISCLAIMED, NON-EXHAUSTIVE curated crosswalk of canonical validated + direction-correct target–
#    indication relationships; an absent (target, indication) degrades to the SHARP data-derived tier or None
#    (never a verdict change — there is none). SET literals / dict, not 2-string tuples (reference-drift guard).

# NORMALISE the OncoTree code so the guard crosswalk matches leaf/composite/synonym codes (mirrors the
# translational-readiness / HCMI-reader normalization).
_LIT_IND_ALIAS = {
    "COAD": "COADREAD",
    "READ": "COADREAD",
    "COADREAD": "COADREAD",
    "LUSC": "LUAD",
    "NSCLC": "LUAD",
    "LUAD": "LUAD",
    "CCRCC": "KIRC",
    "RCC": "KIRC",
    "KIRC": "KIRC",
}


def _lit_norm_ind(indication) -> str:
    ind = (indication or "").upper().strip()
    return _LIT_IND_ALIAS.get(ind, ind)


# BioREx typed-relation labels grouped by POLARITY, for the conflict detector. A relation set carrying BOTH
# an UP and a DOWN label (across papers) is direction-CONFLICTING (the automated extraction disagrees).
_REL_UP = {"stimulate", "positive_correlate"}
_REL_DOWN = {"inhibit", "negative_correlate"}
# `cause` / `associate` are directional-but-not-polarity (a TSG-LoF "cause" is direction-consistent — see the
# VHL note), so they are NOT counted as a polarity conflict on their own.

_SINGLE_PAPER_MAX = 2  # total_relation_publications ≤ this ⇒ the typed relation rests on ≤2 papers (thin)
_PLEIOTROPY_MIN_DISEASES = 8  # n_diseases ≥ this ⇒ promiscuous/pleiotropic hub (the TP53 pattern)
_STALE_BEFORE_YEAR = 2016  # latest_year ≤ this (a decade before the OT 26.06 release) ⇒ stale literature.
# A FIXED data-release anchor (NOT wall-clock) so the note is deterministic.

# (target, indication) whose cited literature is a CANONICAL, VALIDATED, DIRECTION-CORRECT relationship — the
# MILDER false-demote guard (mirrors translational-readiness's _VALIDATED_PRECLINICAL_MODEL / differentiation's
# _BIOLOGICALLY_ESTABLISHED_COMUT). A high co-occurrence VOLUME + a consistent, mechanistically-correct
# relation direction here is EXPECTED, NOT an over-call. DISCLAIMED / non-exhaustive; an absent pair degrades
# to a sharp data-derived tier or None. PMIDs verified live (Phase-1 review). NOTE the polarity split the
# concordance table must handle: KRAS/ERBB2/EGFR are oncogene GoF/amplification (gene positively drives disease
# → cause/positive_correlate/stimulate); VHL is a LoF two-hit TSG (disease driven by LOSS — a typed "cause" is
# still direction-consistent but must NOT be read as oncogene-style GoF).
_VALIDATED_ESTABLISHED_RELATIONSHIP = {
    ("KRAS", "COADREAD"): (
        "Canonical activating GoF oncogene driver of colorectal cancer (codon 12/13 hotspot "
        "SNVs): an early, defining step of the adenoma→carcinoma sequence (Fearon & Vogelstein "
        "1990 PMID 2188735), a validated negative predictor of anti-EGFR benefit (Karapetis "
        "2008 PMID 18946061; Amado 2008 PMID 18316791), and pharmacologically validated by "
        "KRAS-G12C inhibition (sotorasib Hong 2020 PMID 32955176; adagrasib±cetuximab in CRC "
        "Yaeger 2023 PMID 36546659). A high co-occurrence VOLUME + a cause/positive_correlate "
        "direction is EXPECTED here, NOT a citation-bias over-call."
    ),
    ("ERBB2", "BRCA"): (
        "Canonical amplification/overexpression-driven oncogene in breast cancer — the founding "
        "predictive-biomarker→targeted-therapy story: HER2/neu amplification correlates with "
        "relapse and shortened survival (Slamon 1987 PMID 3798106) and anti-HER2 (trastuzumab) "
        "validates the amplification as driver (Slamon 2001 PMID 11248153). High VOLUME + a "
        "cause/positive_correlate direction is EXPECTED, NOT an over-call."
    ),
    ("EGFR", "LUAD"): (
        "Canonical activating GoF oncogene in lung adenocarcinoma via kinase-domain SNV/indel "
        "(exon-19 del / L858R) — the defining oncogene-addiction paradigm: activating EGFR "
        "mutations confer TKI sensitivity (Lynch 2004 PMID 15118073; Paez 2004 PMID 15118125; "
        "Pao 2004 PMID 15329413) and first-line TKI superiority is established (IPASS, Mok 2009 "
        "PMID 19692680). High VOLUME + a cause/positive_correlate/stimulate direction is "
        "EXPECTED, NOT an over-call."
    ),
    ("VHL", "KIRC"): (
        "Canonical loss-of-function two-hit TUMOR SUPPRESSOR of clear-cell RCC (biallelic "
        "inactivation: mutation/deletion + second-hit mutation or promoter methylation): VHL "
        "identified as the ccRCC TSG (Latif 1993 PMID 8493574), somatic VHL mutation in "
        "sporadic ccRCC (Gnarra 1994 PMID 7915601), pVHL degrades HIF-α so VHL loss → "
        "constitutive-HIF pseudohypoxia (Maxwell 1999 PMID 10353251). A high VOLUME is EXPECTED "
        "and a typed cause/associate direction is direction-CONSISTENT for a TSG — but this is "
        "a LOSS-driven relationship, OPPOSITE in sign to the oncogene guards; do NOT read the "
        "typed edge as oncogene-style GoF."
    ),
}


def _cited_positive_substrate(hl: dict) -> bool:
    """Is there an ACTUAL cited-literature signal to confidence-qualify? True only on a MEASURED corpus
    (cited_evidence_status == 'ok') with a nonzero co-occurrence VOLUME or a typed-relation signal. On
    insufficient / no_evidence / data_unavailable / missing → False → the confidence caveat is None (honest
    thin/stale degrade, byte-stable — no manufactured relationship)."""
    if hl.get("cited_evidence_status") != "ok":
        return False
    return bool(hl.get("paper_disease_mentions") or hl.get("total_relation_publications"))


def _relation_conflict(hl: dict) -> bool:
    """Direction CONFLICT: the typed-relation set carries BOTH an UP (stimulate/positive_correlate) and a DOWN
    (inhibit/negative_correlate) label — the automated BioREx extraction disagrees on direction across papers."""
    rts = {str(r).lower() for r in (hl.get("relation_types") or []) if r}
    return bool(rts & _REL_UP) and bool(rts & _REL_DOWN)


def _relation_single_paper(hl: dict) -> bool:
    """The typed relation rests on ≤ _SINGLE_PAPER_MAX publications — a single-/few-paper automated assertion,
    not a corroborated mechanism. Only meaningful when a relation signal is present at all."""
    rts = [r for r in (hl.get("relation_types") or []) if r]
    n = hl.get("total_relation_publications")
    return bool(rts) and isinstance(n, (int, float)) and n <= _SINGLE_PAPER_MAX


def _stale_literature_note(hl: dict) -> dict | None:
    """Optional RECENCY note (VERDICT-INERT, orthogonal to the tier): the literature is STALE — the latest
    mention pre-dates _STALE_BEFORE_YEAR (a decade before the data release), OR there is measured VOLUME but
    ZERO recent mentions. A low-confidence recency flag (Stoeger 2018 PMID 30226837; Edwards 2011 PMID
    21307913: attention concentrates on established hubs, so a stale low-volume pair was likely never built
    out). None when the literature is current / absent (byte-stable)."""
    if not _cited_positive_substrate(hl):
        return None
    latest = hl.get("latest_year")
    recent = hl.get("recent_mentions")
    vol = hl.get("paper_disease_mentions")
    old = isinstance(latest, (int, float)) and latest <= _STALE_BEFORE_YEAR
    quiet = isinstance(recent, (int, float)) and recent == 0 and isinstance(vol, (int, float)) and vol > 0
    if not (old or quiet):
        return None
    bits = []
    if old:
        bits.append(
            f"the latest cited mention is {latest} (≤ {_STALE_BEFORE_YEAR}, a decade before the data "
            "release) — a stale literature that may pre-date modern understanding"
        )
    if quiet:
        bits.append(
            f"there is measured co-occurrence VOLUME ({vol}) but ZERO recent mentions — attention has "
            "moved on (or the association was never built out)"
        )
    return {
        "reason": "stale_literature",
        "tier": "context",
        "detail": (
            "RECENCY flag: " + "; ".join(bits) + ". Recency is a low-confidence signal, not "
            "validation (Stoeger 2018 PMID 30226837; Edwards 2011 PMID 21307913)."
        ),
    }


def _cited_evidence_confidence_caveat(hl: dict, target=None, indication=None) -> dict | None:
    """CONSOLIDATED volume/relation-vs-validated cited-evidence confidence call (VERDICT-INERT). Precedence:
    the MILDER canonical validated+direction-correct guard (iii) FIRST (KRAS/COADREAD, ERBB2/BRCA, EGFR/LUAD,
    VHL/KIRC must NOT be flagged) > the SHARP automated/conflicting-relation tier (ii, more specific) > the
    SHARP volume-without-validated-relation default (i, the catch-all over-call warning incl. pleiotropy) >
    None (no positive substrate → honest thin/stale degrade). Gates on already-emitted VOLUME/RECENCY/RELATION
    fields + the curated (target, indication) crosswalk; never moves a spine (there is none — gateless +
    tokenless)."""
    if not _cited_positive_substrate(hl):
        return None  # thin / stale / no-evidence → byte-stable None
    key = ((target or "").upper().strip(), _lit_norm_ind(indication))

    # TIER (iii) MILDER — canonical validated + direction-correct relationship guard (false-demote).
    if key in _VALIDATED_ESTABLISHED_RELATIONSHIP:
        return {
            "reason": "validated_established_relationship",
            "tier": "milder",
            "false_demote_guarded": True,
            "detail": _VALIDATED_ESTABLISHED_RELATIONSHIP[key],
        }

    # TIER (ii) SHARP — the typed RELATION DIRECTION rests on automated / conflicting / single-paper BioREx
    # extraction. Fires when a relation signal is present AND (direction-conflict OR ≤2-paper thin).
    conflict = _relation_conflict(hl)
    single = _relation_single_paper(hl)
    if conflict or single:
        rts = [str(r) for r in (hl.get("relation_types") or []) if r]
        bits = []
        if conflict:
            bits.append(
                f"the typed-relation set CONFLICTS on direction (both up- and down-polarity labels "
                f"present: {', '.join(rts[:6])}) — the automated extraction disagrees across papers"
            )
        if single:
            bits.append(
                f"the typed relation rests on only {hl.get('total_relation_publications')} publication(s) "
                "— a single-/few-paper automated assertion, not a corroborated mechanism"
            )
        return {
            "reason": "relation_direction_automated_or_conflicting",
            "tier": "sharp",
            "false_demote_guarded": False,
            "detail": (
                "The RELATION DIRECTION is UNRELIABLE: " + "; ".join(bits) + ". PubTator3 typed "
                "edges are ML-extracted by BioREx (best-in-class 79.6% F1 on BioRED — Lai 2023 PMID "
                "37673376; Wei 2024 PMID 38572754), often from a SINGLE sentence, so the direction "
                "can be mis-typed / context-free (an in-vitro edge is not a validated in-vivo "
                "mechanism). The mechanistic/causal call is owned by mechanism-and-pharmacology."
            ),
        }

    # TIER (i) SHARP — volume-without-validated-relation default (the catch-all over-call warning). Covers a
    # HIGH-volume pair with thin/absent relation direction AND the pleiotropy inflation (high n_diseases).
    nd = hl.get("n_diseases")
    pleiotropic = isinstance(nd, (int, float)) and nd >= _PLEIOTROPY_MIN_DISEASES
    extra = ""
    if pleiotropic:
        extra = (
            f" This target co-occurs across MANY diseases (n_diseases={nd} ≥ {_PLEIOTROPY_MIN_DISEASES}) — "
            "a promiscuous/pleiotropic hub (the TP53 pattern; Kandoth 2013 PMID 24132290), so the VOLUME "
            "is a low-SPECIFICITY signal, not an indication-specific validated relationship."
        )
    return {
        "reason": "volume_without_validated_relation",
        "tier": "sharp",
        "false_demote_guarded": False,
        "detail": (
            "The co-occurrence VOLUME describes HOW MUCH is written, NOT a validated / causal target–"
            "indication relationship: a high count reflects CITATION / ATTENTION / STUDY bias "
            "(well-studied genes accrue mentions — Stoeger 2018 PMID 30226837; Edwards 2011 PMID "
            "21307913; guilt-by-association multifunctionality — Gillis & Pavlidis 2012 PMID 22479173), "
            "and the relation direction here is thin/absent/ambiguous so it cannot corroborate a "
            "specific mechanism." + extra + " Treat as DESCRIPTIVE citation context, not validation; "
            "the causal call is owned by mechanism-and-pharmacology and the RISK read by "
            "literature-risk-assessment."
        ),
    }


def _top_cited_pmids(hl: dict, cap: int = 8) -> list:
    """Extract the pmids from the top_cited statements (for the provenance quorum) — the card's OWN verified
    citations, so a consumer can attribute to them without inventing an identifier. Best-effort / shape-tolerant."""
    out = []
    for c in hl.get("top_cited") or []:
        if not isinstance(c, dict):
            continue
        pmid = c.get("pmid") or c.get("PMID")
        if pmid is not None and str(pmid) not in out:
            out.append(str(pmid))
        if len(out) >= cap:
            break
    return out


def _cited_evidence_provenance(hl: dict, target=None, indication=None) -> dict | None:
    """QUORUM / PROVENANCE summary for the cited-literature dossier (VERDICT-INERT): the co-occurrence VOLUME +
    recency + disease breadth, the year span, the typed-relation breadth + publication support + direction-
    conflict flag, the top-cited count + the card's OWN pmids, the pleiotropy + stale flags, and the curated
    validated-relationship flag — plus the load-bearing 'co-occurrence ≠ causation + BioREx is automated
    single-sentence extraction' note — so a high VOLUME or an automated relation is never mistaken for a
    validated, causal, direction-correct relationship. None only on a truly empty read (byte-stable)."""
    _fields = (
        "cited_evidence_status",
        "paper_disease_mentions",
        "recent_mentions",
        "n_diseases",
        "earliest_year",
        "latest_year",
        "relation_types",
        "total_relation_publications",
        "top_cited",
    )
    if all(hl.get(f) in (None, [], 0) for f in _fields):
        return None
    key = ((target or "").upper().strip(), _lit_norm_ind(indication))
    rts = [str(r) for r in (hl.get("relation_types") or []) if r]
    nd = hl.get("n_diseases")
    latest = hl.get("latest_year")
    recent = hl.get("recent_mentions")
    vol = hl.get("paper_disease_mentions")
    return {
        "cited_evidence_status": hl.get("cited_evidence_status"),
        "literature_scope": hl.get("literature_scope"),
        "paper_disease_mentions": vol,
        "recent_mentions": recent,
        "n_diseases": nd,
        "earliest_year": hl.get("earliest_year"),
        "latest_year": latest,
        "n_relation_types": len(rts),
        "relation_types": rts,
        "total_relation_publications": hl.get("total_relation_publications"),
        "relation_direction_conflict": _relation_conflict(hl),
        "relation_single_paper": _relation_single_paper(hl),
        "n_top_cited": len(hl.get("top_cited") or []),
        "top_cited_pmids": _top_cited_pmids(hl),
        "pleiotropic_flag": bool(isinstance(nd, (int, float)) and nd >= _PLEIOTROPY_MIN_DISEASES),
        "stale_flag": bool(isinstance(latest, (int, float)) and latest <= _STALE_BEFORE_YEAR),
        "validated_established_relationship_flag": key in _VALIDATED_ESTABLISHED_RELATIONSHIP,
        "provenance_note": (
            "Cited-literature CONTEXT (Open Targets europePMC co-occurrence + PubTator3 BioREx "
            "typed relations). CO-OCCURRENCE ≠ CAUSATION (volume tracks citation/attention/study "
            "bias — Stoeger 2018 PMID 30226837), and the typed relation DIRECTION is AUTOMATED "
            "single-sentence extraction (BioREx ~79.6% F1 — Lai 2023 PMID 37673376), NOT a "
            "validated in-vivo mechanism. Descriptive + context-tier — never a nomination gate "
            "(RISK_ASSESSMENT_INTEGRATION.md §4)."
        ),
    }


# Canonical headline spec (DESCRIPTIVE MODE — verdict_token=None). VOLUME (how much is written) is the
# coverage-critical axis that floors confidence.
_LITERATURE_HEADLINE_SPEC = HeadlineSpec(
    gate="literature_context",
    axis_labels={"VOLUME": "co-occurrence volume", "RECENCY": "recent activity", "RELATION": "typed relations"},
    axis_keys=("VOLUME", "RECENCY", "RELATION"),
    critical_axes=("VOLUME",),
)


def _build_headline_block(headline: dict) -> dict:
    """Canonical Headline block in DESCRIPTIVE MODE — literature-context is gateless (verdict_fn=None), so
    verdict_token=None and the deterministic key_signals.headline is the descriptive_phrase (call stays
    None, polarity neutral). Never moves a spine (there is none)."""
    ks = headline.get("key_signals") or {}
    return build_headline(
        headline,
        headline.get("claim_vector"),
        headline.get("key_signals"),
        spec=_LITERATURE_HEADLINE_SPEC,
        verdict_token=None,
        descriptive_phrase=ks.get("headline"),
    )


def _headline(cards, fired, verdict_pair, target=None, indication=None):
    """Descriptive cited-literature context — the flat summary fields from the composed card. No verdict
    spine (verdict_fn=None): cited literature informs confidence/context, not a nomination. A composed
    consumer reads these as gene×indication literature context.

    target / indication are OPTIONAL (the dispatcher signature-introspects headline_fn and passes them when
    present) — they key the (target, indication)-crosswalk false-demote guard in
    cited_evidence_confidence_caveat."""
    hl = {
        "cited_evidence_status": get_card_field(cards, "cited-literature-evidence", "cited_evidence_status"),
        "literature_scope": get_card_field(cards, "cited-literature-evidence", "literature_scope"),
        "paper_disease_mentions": get_card_field(cards, "cited-literature-evidence", "paper_disease_mentions"),
        "recent_mentions": get_card_field(cards, "cited-literature-evidence", "recent_mentions"),
        "n_diseases": get_card_field(cards, "cited-literature-evidence", "n_diseases"),
        "earliest_year": get_card_field(cards, "cited-literature-evidence", "earliest_year"),
        "latest_year": get_card_field(cards, "cited-literature-evidence", "latest_year"),
        "top_cited": get_card_field(cards, "cited-literature-evidence", "top_cited"),
        "relation_types": get_card_field(cards, "cited-literature-evidence", "relation_types"),
        "total_relation_publications": get_card_field(
            cards, "cited-literature-evidence", "total_relation_publications"
        ),
    }
    # ── verdict-INERT signals-first projections (mirrors the other descriptive skills) ─────────────
    hl["claim_vector"] = literature_context_claim_vector(hl, cards)
    hl["key_signals"] = literature_context_key_signals(hl, cards)
    # CONSOLIDATED cited-evidence confidence caveats + provenance quorum (VERDICT-INERT) — the cited-literature
    # analog of translational-readiness / target-archetype's confidence surface. Gate on the already-emitted
    # VOLUME/RECENCY/RELATION fields + the curated (target, indication) crosswalk; None on the thin/stale /
    # validated-guarded paths → the VOLUME/RECENCY/RELATION headline + verdict(=None) byte-stable. Best-effort:
    # a fault degrades to None + _enrichment_errors, never aborts the context spine (tumor-presence discipline).
    _cc = None
    try:
        _cc = _cited_evidence_confidence_caveat(hl, target=target, indication=indication)
        hl["cited_evidence_confidence_caveat"] = _cc
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the context spine
        hl.setdefault("_enrichment_errors", {})["cited_evidence_confidence_caveat"] = f"{type(exc).__name__}: {exc}"
        hl["cited_evidence_confidence_caveat"] = None
    for _fld, _fn in (
        ("stale_literature_note", _stale_literature_note),
        ("cited_evidence_provenance", _cited_evidence_provenance),
    ):
        try:
            hl[_fld] = _fn(hl, target=target, indication=indication) if _fld == "cited_evidence_provenance" else _fn(hl)
        except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the context spine
            hl.setdefault("_enrichment_errors", {})[_fld] = f"{type(exc).__name__}: {exc}"
            hl[_fld] = None
    # Surface the PRIMARY cited-evidence-confidence caveat in the key_signals.caveat slot (read by the narrator
    # + cross-evidence) so it is deterministic, not LLM discretion. base key_signals sets no caveat on the
    # negative/thin path → caveat stays None → byte-stable where the caveat is absent.
    if _cc and _cc.get("detail") and isinstance(hl.get("key_signals"), dict):
        hl["key_signals"]["caveat"] = _cc["detail"]
    # The per-question LEADING table + the DESCRIPTIVE headline block + the UNIFIED skill_report. All
    # best-effort + verdict-INERT — a formatting/read fault must NEVER discard the literature-context
    # fields already built in `hl` (tumor-presence degrade-on-exception discipline).
    try:
        hl["question_table"] = literature_context_question_table(hl, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the context spine
        hl.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        hl["question_table"] = None
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — literature-context is GATELESS DESCRIPTIVE
    # (verdict_fn=None → no call) + CONTEXT-tier → role=descriptive, verdict=None → call=None,
    # polarity=not_scored. Never a gate (RISK_ASSESSMENT_INTEGRATION.md §4).
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        hl["skill_report"] = build_skill_report(
            role=ROLE_DESCRIPTIVE,
            verdict=None,
            headline_block=hl.get("headline_block"),
            claim_vector=hl.get("claim_vector"),
            question_table=hl.get("question_table"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
        )
    except Exception as exc:  # noqa: BLE001
        hl.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        hl["skill_report"] = None
    return hl


# ── OPTIONAL cross-modal synthesis facet (lifts the claim_vector to the composed target-profile) ────
# literature-context is DESCRIPTIVE + context-tier (verdict_fn=None); this carries the verdict-INERT
# literature claim_vector + headline_block + question_table + skill_report to the composed target-profile
# synthesis (getattr(module, "_synthesis_facet")). Never moves a verdict + never a gate.
_SYNTHESIS_FACET_KEYS = (
    "cited_evidence_status",
    "literature_scope",
    "paper_disease_mentions",
    "recent_mentions",
    "n_diseases",
    "earliest_year",
    "latest_year",
    "top_cited",
    "relation_types",
    "total_relation_publications",
    "claim_vector",
    "key_signals",
    # the CONSOLIDATED cited-evidence confidence caveats + provenance quorum (verdict-INERT; the cited-
    # literature analog of translational-readiness / target-archetype's confidence surface):
    "cited_evidence_confidence_caveat",
    "stale_literature_note",
    "cited_evidence_provenance",
    "question_table",
    "headline_block",
    "skill_report",
)


def _synthesis_facet(cards, fired, verdict_pair=None, target=None, indication=None):
    """Compact, VERDICT-INERT cited-literature facet for the composed target-profile synthesis. Reuses
    _headline (single source). Gateless + context-tier — never a verdict, never a gate. target / indication
    are signature-introspected by the fan-out (tp_fanout) so the (target, indication)-keyed validated-
    established-relationship false-demote guard reaches the composed profile too."""
    h = _headline(cards, fired, verdict_pair, target=target, indication=indication)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = (
        "Deterministic literature-context facet; claim_vector is VOLUME/RECENCY/"
        "RELATION over the cited-literature card. Context-tier — never a gate."
    )
    return facet


if __name__ == "__main__":
    sys.exit(
        run_wired_skill(
            skill_name=SKILL_NAME,
            skill_version=SKILL_VERSION,
            cards=CARDS,
            axis="intracellular_intrinsic",  # rules axis for loading; literature-context emits no verdict
            question=QUESTION,
            verdict_fn=None,  # DESCRIPTIVE — cited literature is context, not a gate
            headline_fn=_headline,
            # NET-NEW capsule-driven narrator (generic engine + this skill's LensConfig). literature-context had
            # NO lens/narrator before the literature-and-claims arc; LITERATURE_CONTEXT (mode=descriptive) LEADS
            # with the top CITED STATEMENTS + separates a canonical validated relationship from a volume-inflation
            # / automated-relation / pleiotropy over-call.
            synthesize_fn=make_synthesize_fn(_LENS),
            # NB: NO literature_fn. The LLM --literature lane is DELIBERATELY SKIPPED as REDUNDANT / CIRCULAR — the
            # cited-literature-evidence card IS the Europe-PMC + PubTator3 literature, and default_retrieve grounds
            # a lit lane on those SAME two sources, so the lane would re-derive the card's own source and
            # double-count its pmids (it cannot be an INDEPENDENT corroboration of itself). The "literature
            # grounding" the arc wants is ALREADY the deterministic card, surfaced by the narrator + the confidence
            # caveats. See SKILL.md "What this skill does NOT do" + the concordance doc. (Under --literature the
            # dispatcher honest-skips: no literature_fn declared.)
        )
    )
