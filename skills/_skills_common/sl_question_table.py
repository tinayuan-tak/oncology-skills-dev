"""Synthetic-lethal-partners QUESTION TABLE — the LEADING hero for the synthetic-lethal-partners skill.

Canonical question (target_profiling_axes.yaml → home_skill combination-and-vulnerability family):
"Does {target} have a curated synthetic-lethal partner, and how strong is the support?" This is a
THIN single-card skill (SynLethDB v3), so the hero is a compact 2-row table:
  Partner  — is there a curated SL partner at all?
  Support  — is the best evidence experimental (not just computational)?
Verdict-INERT: a one-way projection over decision['headline']; reuses the shared Signal/Confidence
vocab + renderer. (Small tables are honest here — a thin skill should not be inflated into a false
multi-question decomposition.)
"""

from __future__ import annotations

from typing import Optional

from _skills_common.question_table_core import sig as _sig, conf as _conf, row as _row  # shared Signal/Confidence vocab

_PARTNER = {
    "has_experimental_sl_partner": "strong",
    "has_computational_sl_partner": "moderate",
    "no_curated_sl_partner": "absent",
    "data_unavailable": "unmeasured",
}
_EVIDENCE = {"experimental": "strong", "other": "moderate", "computational": "weak"}


def _tier(mapping: dict, val) -> str:
    if val in (None, "", "data_unavailable"):
        return "unmeasured"
    return mapping.get(str(val), "weak")


def sl_question_table(headline: dict, cards: Optional[list] = None) -> list:
    """Compact 2-row SL hero from the synthetic-lethal-partners headline. Verdict-inert."""
    h = headline or {}
    partner_cls = h.get("sl_partner_class")
    count = h.get("sl_partner_count")
    n_exp = h.get("n_experimental_partners")
    tier_cls = h.get("best_evidence_tier")

    partner_sig = _sig(
        _tier(_PARTNER, partner_cls),
        "not measured" if partner_cls in (None, "", "data_unavailable") else str(partner_cls),
    )
    # Support row is unmeasured when there is no partner at all (nothing to support).
    ev_tier = (
        "unmeasured"
        if partner_cls in (None, "", "no_curated_sl_partner", "data_unavailable")
        else _tier(_EVIDENCE, tier_cls)
    )
    ev_sig = _sig(ev_tier, "not measured" if ev_tier == "unmeasured" else str(tier_cls))

    return [
        _row(
            "Partner",
            "Curated synthetic-lethal partner (SynLethDB)?",
            str(partner_cls if partner_cls not in (None, "") else "—"),
            f"partners: {count}" if count not in (None, "") else "",
            partner_sig,
            _conf("unmeasured" if partner_sig["tier"] == "unmeasured" else "moderate"),
        ),
        _row(
            "Support",
            "Experimental support (not just computational)?",
            str(tier_cls if tier_cls not in (None, "") else "—"),
            f"experimental: {n_exp}" if n_exp not in (None, "") else "",
            ev_sig,
            _conf("unmeasured" if ev_tier == "unmeasured" else "moderate"),
        ),
    ]


__all__ = ["sl_question_table"]
