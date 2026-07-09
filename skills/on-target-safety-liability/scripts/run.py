#!/usr/bin/env python3
"""on-target-safety-liability — Phase-G partial skill (graduated 2026-07-08).

Germline LoF-constraint safety signal from gnomAD.

W4c refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill


SKILL_NAME = "on-target-safety-liability"
SKILL_VERSION = "1.2.0"

CARDS = ["gnomad-lof-constraint"]

QUESTION = ("Is {target} highly constrained against loss-of-function "
            "variants in the gnomAD population, and what does this imply "
            "for on-target safety of full-KO modalities (degrader, RNA "
            "therapeutic, full-inhibition SM) in {indication}?")

PARTIAL_STATUS_NOTE = (
    "on-target-safety-liability is status: partial; normal-tissue-liability "
    "+ protein-surface-evidence cards not wired (HPA IHC dispatcher pending). "
    "Only gnomAD germline constraint signal reflected in this decision."
)


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    fired_by_id = {r["rule_id"]: r for r in fired}
    if "highly-constrained-safety-warning" in fired_by_id:
        return "highly_constrained_safety_concern", "highly-constrained-safety-warning"
    if "tolerant-safety-supportive" in fired_by_id:
        return "tolerant_reduced_safety_risk", "tolerant-safety-supportive"
    if "constraint-data-unavailable-insufficient" in fired_by_id:
        return "data_unavailable", "constraint-data-unavailable-insufficient"
    return "insufficient", None


def _headline(cards, fired, verdict_pair):
    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    v, drv = verdict_pair or ("insufficient", None)
    return {
        "safety_verdict":   v,
        "driving_rule_id":  drv,
        "constraint_class": _get("gnomad-lof-constraint", "constraint_class"),
        "pli_score":        _get("gnomad-lof-constraint", "pli_score"),
        "loeuf_score":      _get("gnomad-lof-constraint", "loeuf_score"),
        "mis_z_score":      _get("gnomad-lof-constraint", "mis_z_score"),
        "syn_z_score":      _get("gnomad-lof-constraint", "syn_z_score"),
        "obs_lof_count":    _get("gnomad-lof-constraint", "obs_lof_count"),
        "exp_lof_count":    _get("gnomad-lof-constraint", "exp_lof_count"),
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
        partial_status_note=PARTIAL_STATUS_NOTE,
    ))
