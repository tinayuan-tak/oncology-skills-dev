#!/usr/bin/env python3
"""tumor-presence — expression status for a single (target, indication).

Consumes 2 wired expression cards + expression-* rule subset. Emits a
data-package output tree with a rank-ordered presence verdict.

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill


SKILL_NAME = "tumor-presence"
SKILL_VERSION = "1.1.0"

CARDS = [
    "expression-distribution",
    "expression-tumor-vs-adjacent",
    "protein-presence-cptac",           # Layer 6c addition
]

QUESTION = ("Is {target} expressed in {indication} tumor tissue, and how "
            "does its expression distribute across cancer cell lines vs. "
            "paired tumor/adjacent samples?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Rank-ordered verdict from fired rules."""
    fired_by_id = {r["rule_id"]: r for r in fired}

    if "expression-broadly-high-supportive" in fired_by_id:
        return "broadly_high_expression", "expression-broadly-high-supportive"
    if "expression-strong-upregulation-supportive" in fired_by_id:
        return "strongly_upregulated_in_tumor", "expression-strong-upregulation-supportive"
    if "expression-lineage-restricted-supportive" in fired_by_id:
        return "lineage_restricted", "expression-lineage-restricted-supportive"
    if "expression-modest-upregulation-neutral" in fired_by_id:
        return "modestly_upregulated_in_tumor", "expression-modest-upregulation-neutral"
    if "expression-broadly-moderate-neutral" in fired_by_id:
        return "broadly_moderate_expression", "expression-broadly-moderate-neutral"
    if "expression-broadly-low-degrader-killer" in fired_by_id:
        return "broadly_low_expression", "expression-broadly-low-degrader-killer"
    if "expression-call-not-informative-degrader-killer" in fired_by_id:
        return "not_informative", "expression-call-not-informative-degrader-killer"
    for rid in ("expression-data-unavailable-insufficient",
                "expression-call-data-unavailable-insufficient"):
        if rid in fired_by_id:
            return "data_unavailable", rid

    return "insufficient", None


def _headline(cards, fired, verdict_pair):
    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    v, drv = verdict_pair or ("insufficient", None)
    return {
        "presence_verdict":         v,
        "driving_rule_id":          drv,
        "median_log2tpm_panel":     _get("expression-distribution",
                                          "median_log2tpm_panel"),
        "expression_call_class":    _get("expression-distribution",
                                          "expression_call_class"),
        "tva_log2_fc":              _get("expression-tumor-vs-adjacent", "log2_fc"),
        "tva_q_value":              _get("expression-tumor-vs-adjacent", "q_value"),
        "tva_expression_call":      _get("expression-tumor-vs-adjacent",
                                          "expression_call_class"),
        "protein_expression_class": _get("protein-presence-cptac",
                                          "protein_expression_class"),
        "protein_effect_size":      _get("protein-presence-cptac",
                                          "protein_effect_size"),
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
