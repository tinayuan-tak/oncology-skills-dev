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


SKILL_NAME = "synthetic-lethal-partners"
SKILL_VERSION = "1.0.0"

CARDS = ["synthetic-lethal-partners"]

QUESTION = ("Does {target} have a curated synthetic-lethal partner (SynLethDB v3), "
            "and is the evidence experimental — such that a pooled non-dependent "
            "CRISPR read in {indication} may be a context-conditional false negative?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Map the SL-partner card's class → the sub-verdict the gate suppressor reads.

    The verdict string MUST equal the sl_partner_class value the gate's veto_suppressor
    names (`has_experimental_sl_partner`) — that exact (synthetic_lethal_partners,
    has_experimental_sl_partner) tuple is what suppresses (dependency, non_dependent).
    A computational-only partner is surfaced but does NOT trigger suppression.
    """
    fired_by_id = {r["rule_id"]: r for r in fired}
    if "sl-experimental-partner-context-conditional" in fired_by_id:
        return "has_experimental_sl_partner", "sl-experimental-partner-context-conditional"
    if "sl-computational-partner-informational" in fired_by_id:
        return "has_computational_sl_partner", "sl-computational-partner-informational"
    if "sl-no-partner-neutral" in fired_by_id:
        return "no_curated_sl_partner", "sl-no-partner-neutral"
    if "sl-data-unavailable-insufficient" in fired_by_id:
        return "data_unavailable", "sl-data-unavailable-insufficient"
    return "insufficient", None


def _headline(cards, fired, verdict_pair):
    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    v, drv = verdict_pair or ("insufficient", None)
    return {
        "sl_partner_verdict":       v,
        "driving_rule_id":          drv,
        "sl_partner_class":         _get("synthetic-lethal-partners", "sl_partner_class"),
        "sl_partner_count":         _get("synthetic-lethal-partners", "sl_partner_count"),
        "n_experimental_partners":  _get("synthetic-lethal-partners", "n_experimental_partners"),
        "has_experimental_partner": _get("synthetic-lethal-partners", "has_experimental_partner"),
        "best_evidence_tier":       _get("synthetic-lethal-partners", "best_evidence_tier"),
    }


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
