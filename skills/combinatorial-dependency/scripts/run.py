#!/usr/bin/env python3
"""combinatorial-dependency — is target X a COMBINATORIAL (paralog dual-KO) dependency?

Focused question skill: "When {target} is co-knocked-out with a paralog partner, is there a
synthetic-lethal / buffering genetic interaction, and is it CONSTITUTIVE (broad) or
CONTEXT/GENOTYPE-CONDITIONAL?" Consumes the single combinatorial-dependency card + the
combinatorial-dependency rule subset. Emits a data-package with a self-contained verdict.

This is the measured combinatorial-KO complement to:
  - functional-requirement (single-gene dependency), and
  - synthetic-lethal-partners (CURATED SL annotation → dependency veto-suppressor).
It sees paralog co-dependencies (CDK2/CDK4, KAT6A/KAT6B, MARK2/MARK3) that single-KO screens
miss. Biggest uncovered theme in the TIDVAL target-project benchmark.

SELF-CONTAINED VERDICT: _verdict() maps the fired combinatorial-dependency rules → the skill's
own combinatorial_dependency_verdict directly (NO shared resolver YAML, NO nomination_verdict_gate
rung). Composition into target-profile is a deliberate follow-on; keeping the verdict local means
the existing resolver golden snapshots stay byte-stable.

Biology-first output; modality is a POST-HOC lens (the rules carry small_molecule/degrader signals).
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import card_summary
from _skills_common.dispatcher import run_wired_skill
from _skills_common.headline_core import HeadlineSpec, build_headline
from _skills_common.literature_retrieval import default_retrieve, verify_citations
from _skills_common.literature_synthesis import make_literature_fn
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import COMBINATORIAL_DEPENDENCY as _LENS
from _skills_common.skill_report import ROLE_DESCRIPTIVE, build_skill_report
from _skills_common.sl_crosswalks import (
    SCAFFOLD_UNDRUGGABLE_PARTNERS,
    VALIDATED_PARALOG_SL,
    is_pan_essential,
    validated_paralog_sl,
)

SKILL_NAME = "combinatorial-dependency"
SKILL_VERSION = "1.1.0"  # 1.1.0 (2026-09-05, literature-and-claims arc, item #4): CREATE the
# COMBINATORIAL_DEPENDENCY narrator lens (was NONE) + wire synthesize_fn + BAKE the
# --literature lane (a GENUINE 2nd channel — published paralog-SL literature vs the
# measured DepMap ParalogV2 GI). Verdict-INERT confidence surface —
# combinatorial_dependency_confidence_caveat (3-tier: measured_gi_functionally_
# unconfirmed / pan_essential_or_context_restricted / validated_paralog_synthetic_lethal
# DATA-BLIND-TOLERANT false-demote guard) + combinatorial_druggability_caveat (scaffold
# partner → degrader) + combinatorial_dependency_provenance QUORUM. Caveats REUSE the
# shared _skills_common/sl_crosswalks corpus + gate on EXISTING headline fields → the
# SELF-CONTAINED verdict (combinatorial_dependency_verdict / driving_rule_id) is
# byte-stable. SET literals not 2-tuples.

CARDS = [
    "combinatorial-dependency",
]

QUESTION = (
    "When {target} is co-knocked-out with a paralog partner, is there a synthetic-lethal / "
    "buffering genetic interaction, and is it constitutive or context-conditional?"
)

# rule_id -> verdict (self-contained; mirrors combinatorial-dependency.rules.yaml verdicts).
# Precedence encoded by ordering: the resolver picks the strongest fired rule.
_RULE_VERDICT = {
    "combo-constitutive-synthetic-lethal": "constitutive_combinatorial_dependency",
    "combo-context-conditional-synthetic-lethal": "context_combinatorial_dependency",
    "combo-suppressive-interaction": "suppressive_combinatorial_interaction",
    "combo-no-interaction": "no_combinatorial_dependency",
    "combo-no-paralog-screened": "combinatorial_dependency_insufficient",
    "combo-dependency-data-unavailable": "combinatorial_dependency_insufficient",
}
# Strongest-wins order (constitutive > context > suppressive > no_interaction > insufficient).
_PRECEDENCE = [
    "combo-constitutive-synthetic-lethal",
    "combo-context-conditional-synthetic-lethal",
    "combo-suppressive-interaction",
    "combo-no-interaction",
    "combo-no-paralog-screened",
    "combo-dependency-data-unavailable",
]


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Self-contained combinatorial-dependency verdict from the fired rule set.

    Exactly one of the card's classes fires per run (the class is a partition), but we resolve by
    documented precedence for robustness. Returns (verdict, driving_rule_id). No shared resolver."""
    fired_ids = {r.get("rule_id") for r in fired}
    for rid in _PRECEDENCE:
        if rid in fired_ids:
            return (_RULE_VERDICT[rid], rid)
    # No combinatorial-dependency rule fired at all (card missing / no class) — insufficient, honest.
    return ("combinatorial_dependency_insufficient", None)


# ── COMBINATORIAL-DEPENDENCY confidence surface (VERDICT-INERT) — the measured-paralog-SL analog of
#    combination-and-vulnerability's partner_confirmation_caveat, reusing the SHARED _skills_common/
#    sl_crosswalks corpus. THE TRAP: a MEASURED DepMap ParalogV2 genetic-interaction score OVER-CALLS a
#    portable, druggable synthetic lethality. Three sub-inflations: (a) PAN-ESSENTIAL CO-FITNESS — a
#    co-dependency with a common-essential partner is a core-fitness artifact, NOT a selective SL (Hart 2015
#    PMID 26627737; Behan 2019 PMID 30971826); (b) CONTEXT / LINEAGE-RESTRICTED + SL REPRODUCIBILITY — a
#    context-conditional interaction is cell-line-restricted, and DepMap is IMMORTALIZED 2D lines where SL
#    frequently FAILS TO REPLICATE (Ryan-Bajrami-Lord 2018 PMID 30292351; Dempster 2019 PMID 31862961);
#    (c) KO ≠ INHIBITION — a dual-KO removes the ENTIRE paralog whereas a drug inhibits ONE activity partially
#    (Weiss-Shokat 2007 PMID 18007642), so a scaffold partner needs a DEGRADER (Farnaby 2019 PMID 31178587).
#    CONVERSELY, DepMap single-context ParalogV2 UNDER-calls canonical paralog SLs (buffering masks them until
#    both are hit — Dede 2020 PMID 33059726; De Kegel & Ryan 2019 PMID 31652272), so the validated-paralog-SL
#    guard is DATA-BLIND-TOLERANT (fires on a screened pair even when the GI reads no_interaction). This skill
#    is verdict-bearing (SELF-CONTAINED verdict), so the caveats are VERDICT-INERT annotation layers over the
#    already-emitted headline fields, NEVER read by the verdict map. SET literals (drift guard).

_COMBO_INTERACTION_VERDICTS = {
    "constitutive_combinatorial_dependency",
    "context_combinatorial_dependency",
    "suppressive_combinatorial_interaction",
}
_COMBO_PARTNER_KEYS = ("partner_gene", "paralog_partner", "partner", "gene", "symbol", "partner_symbol")


def _combo_partner_syms(hl: dict) -> list:
    """Screened paralog-partner symbols (strongest_partner + top_partners rows) — shape-tolerant."""
    out = []
    sp = hl.get("strongest_partner")
    if isinstance(sp, str) and sp:
        out.append(sp)
    for r in hl.get("top_partners") or []:
        if isinstance(r, dict):
            for k in _COMBO_PARTNER_KEYS:
                if r.get(k):
                    out.append(str(r[k]))
                    break
        elif isinstance(r, str) and r:
            out.append(r)
    seen, uniq = set(), []
    for s in out:
        u = s.upper()
        if u not in seen:
            seen.add(u)
            uniq.append(s)
    return uniq


def _combo_screened(hl: dict) -> bool:
    return bool((hl.get("n_paralog_partners_screened") or 0) > 0 or _combo_partner_syms(hl))


def _combo_has_interaction(hl: dict) -> bool:
    return hl.get("combinatorial_dependency_verdict") in _COMBO_INTERACTION_VERDICTS or bool(
        hl.get("n_interacting_partners") or 0
    )


def _combinatorial_dependency_confidence_caveat(hl: dict, target=None, indication=None) -> dict | None:
    """CONSOLIDATED measured-paralog-SL-vs-validated confidence call (VERDICT-INERT). Precedence: the MILDER
    canonical paralog-SL guard (iii, DATA-BLIND-TOLERANT — fires on a screened pair even when the GI reads
    no_interaction, because ParalogV2 under-calls) FIRST > the SHARP pan-essential / context-restricted tier
    (ii) > the SHARP measured-GI-unconfirmed default (i) > None (nothing screened, or screened-negative and
    not a validated paralog → honest thin). Gates on already-emitted headline fields + the SHARED paralog-SL
    crosswalk; NEVER moves the self-contained verdict (verdict-INERT)."""
    # TIER (iii) MILDER — canonical paralog-SL guard, DATA-BLIND-TOLERANT: the target is a curated paralog-SL
    # gene AND its known partner was screened (present among the paralog rows) — fires even if the GI reads
    # no_interaction (ParalogV2 under-calls: Dede 2020 PMID 33059726). Ordered FIRST so an under-called
    # canonical pair is not mis-degraded / dropped as thin.
    vp = validated_paralog_sl(target)
    if vp and _combo_screened(hl):
        partner_present = vp[0].upper() in {s.upper() for s in _combo_partner_syms(hl)}
        return {
            "reason": "validated_paralog_synthetic_lethal",
            "tier": "milder",
            "false_demote_guarded": True,
            "paralog_partner": vp[0],
            "partner_screened_present": partner_present,
            "detail": (
                vp[1]
                + (
                    " NB DepMap ParalogV2 may UNDER-call this pair (buffering masks it until "
                    "both are hit — Dede 2020 PMID 33059726); the guard is data-blind-tolerant."
                    if not partner_present
                    else ""
                )
            ),
        }

    if not _combo_has_interaction(hl):
        return None  # screened-negative non-canonical → byte-stable None

    syms = _combo_partner_syms(hl)
    pan = [s for s in syms if is_pan_essential(s)]
    context_restricted = (
        hl.get("combinatorial_dependency_verdict") == "context_combinatorial_dependency"
        or str(hl.get("combinatorial_context") or "").lower().startswith("context")
        or str(hl.get("combinatorial_dependency_class") or "").lower().startswith("context")
    )

    # TIER (ii) SHARP — pan-essential co-fitness OR context/lineage-restricted (not constitutive/portable).
    if pan or context_restricted:
        bits = []
        if pan:
            bits.append(
                f"a pan-essential / common-essential partner ({', '.join(pan[:4])}) — a core-fitness "
                "co-dependency expected by construction, NOT a selective druggable SL (Hart 2015 PMID "
                "26627737; Behan Project Score demotes common-essentials PMID 30971826)"
            )
        if context_restricted:
            bits.append(
                "the interaction is CONTEXT / GENOTYPE-CONDITIONAL (not a constitutive, portable "
                "buffering SL) — a cell-line/lineage-restricted signal"
            )
        return {
            "reason": "pan_essential_or_context_restricted",
            "tier": "sharp",
            "false_demote_guarded": False,
            "detail": (
                "The measured combinatorial dependency is confounded: " + "; ".join(bits) + ". "
                "DepMap ParalogV2 is IMMORTALIZED 2D cell lines where SL is context-dependent and "
                "frequently FAILS TO REPLICATE (Ryan-Bajrami-Lord 2018 PMID 30292351; Dempster 2019 "
                "PMID 31862961). Treat as a hypothesis pending orthogonal / in-vivo confirmation."
            ),
        }

    # TIER (i) SHARP — a measured GI without orthogonal / clinical confirmation in-package.
    return {
        "reason": "measured_gi_functionally_unconfirmed",
        "tier": "sharp",
        "false_demote_guarded": False,
        "detail": (
            "The measured paralog dual-KO genetic interaction rests on a DepMap ParalogV2 GI score "
            "WITHOUT orthogonal functional / in-vivo / clinical confirmation in-package. SL is "
            "strongly context/genotype-dependent and frequently fails to replicate across screens "
            "(the SL reproducibility problem; O'Neil-Bailey-Hart 2017 PMID 28649135; Ryan-Bajrami-"
            "Lord 2018 PMID 30292351), and a genetic KO removes the ENTIRE paralog whereas a drug "
            "inhibits ONE activity partially (KO ≠ inhibition; Weiss-Shokat 2007 PMID 18007642). "
            "Treat as a combination HYPOTHESIS; the single-gene dependency MAGNITUDE is owned by "
            "functional-requirement and the druggability call by tractability-small-molecule."
        ),
    }


def _combinatorial_druggability_caveat(hl: dict, target=None, indication=None) -> dict | None:
    """The KO≠inhibition sub-inflation (VERDICT-INERT): a dual-KO paralog SL whose partner is a curated
    scaffold / non-enzymatic partner needs a DEGRADER, not an active-site inhibitor. Fires only when a
    screened partner is a known scaffold-undruggable partner; None otherwise (byte-stable)."""
    if not _combo_screened(hl):
        return None
    scaffolds = sorted({s.upper() for s in _combo_partner_syms(hl) if s.upper() in SCAFFOLD_UNDRUGGABLE_PARTNERS})
    if not scaffolds:
        return None
    named = ", ".join(f"{g} ({SCAFFOLD_UNDRUGGABLE_PARTNERS[g]})" for g in scaffolds)
    return {
        "reason": "genetic_ko_undruggable_scaffold_partner",
        "tier": "sharp",
        "scaffold_partners": scaffolds,
        "detail": (
            f"The paralog partner {named} is a scaffold / non-enzymatic partner where a dual-KO is "
            "NOT reproduced by active-site inhibition — a DEGRADER / molecular-glue / PPI modality "
            "is required (KO ≠ inhibition; Weiss-Shokat 2007 PMID 18007642; SMARCA2 PROTAC Farnaby "
            "2019 PMID 31178587). Breadcrumb the druggability call to tractability-small-molecule."
        ),
    }


def _combinatorial_dependency_provenance(hl: dict, target=None, indication=None) -> dict | None:
    """QUORUM / PROVENANCE summary for the measured paralog dual-KO annex (VERDICT-INERT): the verdict/class,
    partners screened + interacting, strongest partner + GI + class, pan-essential / scaffold flags, and the
    validated-paralog-SL flag — so a single DepMap GI is never read as a validated portable druggable SL.
    None on the thin/empty path (byte-stable)."""
    if not _combo_screened(hl):
        return None
    syms = _combo_partner_syms(hl)
    pan = [s for s in syms if is_pan_essential(s)]
    scaffolds = sorted({s.upper() for s in syms if s.upper() in SCAFFOLD_UNDRUGGABLE_PARTNERS})
    return {
        "combinatorial_dependency_verdict": hl.get("combinatorial_dependency_verdict"),
        "combinatorial_dependency_class": hl.get("combinatorial_dependency_class"),
        "n_paralog_partners_screened": hl.get("n_paralog_partners_screened"),
        "n_interacting_partners": hl.get("n_interacting_partners"),
        "strongest_partner": hl.get("strongest_partner"),
        "strongest_partner_mean_gi": hl.get("strongest_partner_mean_gi"),
        "strongest_partner_class": hl.get("strongest_partner_class"),
        "pan_essential_partners_present": pan or None,
        "scaffold_undruggable_partners_present": scaffolds or None,
        "validated_paralog_sl_flag": (target or "").upper().strip() in VALIDATED_PARALOG_SL,
        "provenance_note": (
            "Measured DepMap ParalogV2 paralog dual-KO genetic interaction. A single-context "
            "GI is NOT a validated, portable, druggable SL: SL is context-dependent + often "
            "non-replicating (Ryan-Bajrami-Lord 2018 PMID 30292351), single-context screens "
            "UNDER-call buffered paralog pairs (Dede 2020 PMID 33059726), and KO ≠ "
            "pharmacological inhibition (Weiss-Shokat 2007 PMID 18007642). A paralog "
            "co-dependency is a combination OPPORTUNITY; this skill never nominates the target."
        ),
    }


# ── Canonical HEADLINE block (verdict + confidence + top-tension) for the DESCRIPTIVE spine ──────────
# combinatorial-dependency has NO claim_vector machinery (single-card self-contained verdict), so — like
# synthetic-lethal-partners — it declares a thin HeadlineSpec + a verdict→phrase/certainty map: the phrase
# is the verdict label, and confidence rides the CERTAINTY sidecar (derive_confidence honours it) so the
# block carries a MEANINGFUL confidence rather than the coverage-based "insufficient" a null claim_vector
# would yield. VERDICT-INERT projection over the already-emitted headline fields; never moves the verdict.
_COMBO_HEADLINE_SPEC = HeadlineSpec(
    gate="combinatorial_dependency",
    axis_labels={"CODEP": "paralog co-dependency (dual-KO GI)", "CONTEXT": "constitutive vs context"},
    axis_keys=("CODEP", "CONTEXT"),
    critical_axes=("CODEP",),
    verdict_label=lambda v: {
        "constitutive_combinatorial_dependency": "Constitutive paralog co-dependency (broad co-targeting rationale)",
        "context_combinatorial_dependency": "Context-conditional combinatorial dependency (genotype/lineage-selected)",
        "suppressive_combinatorial_interaction": "Suppressive combinatorial interaction (co-loss less lethal)",
        "no_combinatorial_dependency": "No combinatorial (paralog) dependency (measured negative)",
        "combinatorial_dependency_insufficient": "Insufficient evidence for a combinatorial-dependency call",
    }.get(v, str(v).replace("_", " ").strip().capitalize()),
)
# Weakest-link certainty by verdict: a measured DepMap ParalogV2 GI is a HYPOTHESIS (KO ≠ inhibition, SL
# reproducibility problem — see the confidence caveats), so even a constitutive call floors at moderate; a
# context-conditional / suppressive / measured-negative read is weak (ParalogV2 under-calls buffered pairs);
# the coverage-gap / read-failure collapse is honestly insufficient.
_COMBO_CERTAINTY_BY_VERDICT = {
    "constitutive_combinatorial_dependency": "moderate",
    "context_combinatorial_dependency": "weak",
    "suppressive_combinatorial_interaction": "weak",
    "no_combinatorial_dependency": "weak",
    "combinatorial_dependency_insufficient": "insufficient",
}


def _build_headline_block(hl: dict) -> dict:
    """Descriptive headline (verdict + certainty-sidecar confidence + top-tension). The measured-GI
    confidence caveat, when present, is the top tension. Never moves the self-contained verdict."""
    v = hl.get("combinatorial_dependency_verdict")
    hb = build_headline(
        hl,
        hl.get("claim_vector"),
        hl.get("key_signals"),
        spec=_COMBO_HEADLINE_SPEC,
        verdict_token=v,
        driving_rule_id=hl.get("driving_rule_id"),
        certainty={"level": _COMBO_CERTAINTY_BY_VERDICT.get(v, "insufficient")},
    )
    caveat = hl.get("combinatorial_dependency_confidence_caveat")
    if isinstance(caveat, dict) and caveat.get("detail") and not hb.get("top_tension"):
        hb["top_tension"] = {"text": caveat["detail"], "source": "combinatorial_dependency_confidence_caveat"}
    return hb


def _headline(cards, fired, verdict_pair, target=None, indication=None):
    def _summary(cid):
        return card_summary(cards, cid)  # shared helper (_skills_common)

    s = _summary("combinatorial-dependency")
    verdict, driving = verdict_pair
    hl = {
        "combinatorial_dependency_verdict": verdict,
        "driving_rule_id": driving,
        "combinatorial_dependency_class": s.get("combinatorial_dependency_class"),
        "n_paralog_partners_screened": s.get("n_paralog_partners_screened"),
        "n_interacting_partners": s.get("n_interacting_partners"),
        "strongest_partner": s.get("strongest_partner"),
        "strongest_partner_mean_gi": s.get("strongest_partner_mean_gi"),
        "strongest_partner_class": s.get("strongest_partner_class"),
        "top_partners": s.get("top_partners"),
        "combinatorial_context": s.get("combinatorial_context"),
    }
    # CONSOLIDATED measured-paralog-SL confidence caveats + provenance quorum (VERDICT-INERT) — the
    # measured-SL analog of combination-and-vulnerability's partner_confirmation surface, reusing the shared
    # paralog-SL crosswalk. Gate on the already-emitted headline fields; None on the thin / validated-guarded
    # paths → the self-contained verdict byte-stable. Best-effort: a fault degrades to None + _enrichment_errors,
    # never aborts the verdict spine. target / indication are OPTIONAL (signature-introspected by the dispatcher).
    for _fld, _fn in (
        ("combinatorial_dependency_confidence_caveat", _combinatorial_dependency_confidence_caveat),
        ("combinatorial_druggability_caveat", _combinatorial_druggability_caveat),
        ("combinatorial_dependency_provenance", _combinatorial_dependency_provenance),
    ):
        try:
            hl[_fld] = _fn(hl, target=target, indication=indication)
        except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the verdict spine
            hl.setdefault("_enrichment_errors", {})[_fld] = f"{type(exc).__name__}: {exc}"
            hl[_fld] = None
    # Canonical headline block (verdict + confidence + top tension) — the descriptive projection the
    # unified spine reads honest_phrase + confidence off. Best-effort + verdict-INERT.
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the verdict spine
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # Unified skill_report envelope (data-product lock): verdict-INERT normalizer — role DESCRIPTIVE
    # (self-contained verdict skill, NOT wired into the target-profile gate ladder → polarity not_scored),
    # call = the combinatorial_dependency_verdict. Best-effort: a fault degrades (never aborts the spine).
    try:
        _used = [c["card_id"] for c in (cards or []) if not c.get("_missing")]
        hl["skill_report"] = build_skill_report(
            role=ROLE_DESCRIPTIVE,
            verdict=hl.get("combinatorial_dependency_verdict"),
            driving_rule_id=hl.get("driving_rule_id"),
            headline_block=hl.get("headline_block"),
            claim_vector=hl.get("claim_vector"),
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
            axis="combinatorial_dependency",
            question=QUESTION,
            verdict_fn=_verdict,
            headline_fn=_headline,
            # NET-NEW capsule-driven narrator (generic engine + this skill's LensConfig). combinatorial-dependency
            # had NO lens/narrator before the literature-and-claims arc; COMBINATORIAL_DEPENDENCY (mode=verdict)
            # LEADS with constitutive-vs-context-conditional + validated-paralog-SL vs statistical/pan-essential.
            synthesize_fn=make_synthesize_fn(_LENS),
            # OPTIONAL verdict-INERT LLM --literature lane: the measured DepMap ParalogV2 GI is orthogonal to the
            # published paralog-SL literature, so the lane is a GENUINE second channel (UNLIKE literature-context).
            # Europe-PMC-grounded + PMID-verified; attached AFTER the self-contained verdict, fed to --synthesize.
            # Query terms (_LENS_QUERY_TERMS["combinatorial-dependency"]) front-load the paralog-buffering /
            # SL-validation / KO-vs-inhibition discriminators. Cannot touch the verdict (attached after it).
            literature_fn=make_literature_fn(_LENS, retrieve_fn=default_retrieve, verify_fn=verify_citations),
        )
    )
