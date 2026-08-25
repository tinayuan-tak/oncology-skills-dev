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


SKILL_NAME = "synthetic-lethal-partners"
SKILL_VERSION = "1.0.0"

CARDS = ["synthetic-lethal-partners"]

QUESTION = ("Does {target} have a curated synthetic-lethal partner (SynLethDB v3), "
            "and is the evidence experimental — such that a pooled non-dependent "
            "CRISPR read in {indication} may be a context-conditional false negative?")


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
        return "measured_negative"               # we looked; no curated partner
    return "measured_positive"                   # has_experimental / has_computational partner


def _sl_finding(v):
    """(direction, magnitude.level). Experimental SL evidence > computational."""
    if v == "has_experimental_sl_partner":
        return "supports", "strong"
    if v == "has_computational_sl_partner":
        return "supports", "moderate"
    return "neutral", "none"                      # absence / insufficient / open-world


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


def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    hl = {
        "sl_partner_verdict":       v,
        "driving_rule_id":          drv,
        "sl_partner_class":         get_card_field(cards, "synthetic-lethal-partners", "sl_partner_class"),
        "sl_partner_count":         get_card_field(cards, "synthetic-lethal-partners", "sl_partner_count"),
        "n_experimental_partners":  get_card_field(cards, "synthetic-lethal-partners", "n_experimental_partners"),
        "has_experimental_partner": get_card_field(cards, "synthetic-lethal-partners", "has_experimental_partner"),
        "best_evidence_tier":       get_card_field(cards, "synthetic-lethal-partners", "best_evidence_tier"),
    }
    # The compact 2-row LEADING table (Partner · Support) — a verdict-INERT projection over the just-built
    # headline (mirrors tumor-presence / tumor-selectivity). Best-effort: a formatting/read fault must
    # NEVER discard the sl_partner spine already built in `hl` (this skill is a nomination-gate veto-
    # suppressor, so its verdict must survive any display-layer fault).
    try:
        hl["question_table"] = sl_question_table(hl, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        hl["question_table"] = None
    return hl


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
    ))
