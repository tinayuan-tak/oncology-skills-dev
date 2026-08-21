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
