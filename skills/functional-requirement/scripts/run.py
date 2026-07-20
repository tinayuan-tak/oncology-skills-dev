#!/usr/bin/env python3
"""functional-requirement — is target X a genetic dependency in indication Y.

Consumes 5 dependency-relevant cards (CRISPR + RNAi + concordance +
lineage-selectivity + paralog-buffering) + the dependency-* rule subset.

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill


SKILL_NAME = "functional-requirement"
SKILL_VERSION = "1.1.0"

CARDS = [
    "pan-cancer-crispr-dependency-distribution",
    "pan-cancer-rnai-dependency-distribution",
    "crispr-rnai-dependency-concordance",
    "dependency-lineage-selectivity",
    "paralog-buffering",                        # Layer 6d addition
]

QUESTION = ("Is {target} a genetic dependency in {indication}, and how does "
            "the call hold up across CRISPR, RNAi, concordance, lineage-"
            "selectivity, and paralog-buffering views?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Rank-ordered verdict resolution. Returns (verdict, driving_rule_id)."""
    fired_by_id = {r["rule_id"]: r for r in fired}

    # Pan-essential ADMISSIBILITY guard (H fix 2026-07-20): a >=85% pan-essential call on
    # an underpowered panel (< coverage floor) is a tiny-panel artifact, NOT a trusted
    # pan-essential. Checked BEFORE the pan-essential killer so it escapes the VETO and
    # routes to insufficient. The classifier emits common_essential OR
    # common_essential_underpowered (never both). Symmetric to the non-dependent-
    # underpowered guard below. Distinct verdict for provenance.
    for rid in ("common-essential-underpowered-insufficient",
                "rnai-common-essential-underpowered-insufficient"):
        if rid in fired_by_id:
            return "insufficient_underpowered_pan_essential", rid

    for rid in ("pan-essential-killer", "rnai-pan-essential-killer"):
        if rid in fired_by_id:
            return "pan_essential_killer", rid

    if "concordant-dependent-supportive-dominant" in fired_by_id:
        return "concordant_dependent", "concordant-dependent-supportive-dominant"

    if "lineage-selective-supportive" in fired_by_id:
        return "lineage_selective", "lineage-selective-supportive"

    for rid in ("strongly-selective-supportive", "rnai-strongly-selective-supportive"):
        if rid in fired_by_id:
            return "selective_dependent", rid

    if "concordance-discordant-warning" in fired_by_id:
        return "discordant", "concordance-discordant-warning"

    # DepMap-power admissibility guard (2026-07-17): a below-floor pooled negative
    # CONTRADICTED by a well-sampled concentrated-dependent lineage (EGFR-mut lung,
    # FLT3-mut AML, IDH1-mut under-sampled in DepMap). Distinct from non_dependent:
    # this is a coverage gap (pooled power diluted), NOT a measured negative, so it
    # must NOT reach the `non_dependent` gate veto. Checked BEFORE non-dependent-killer
    # (the classifier emits one or the other; both never fire together) so the
    # underpowered verdict + its driving rule are recorded for provenance rather than
    # collapsing into a bare `insufficient` fall-through.
    if "non-dependent-underpowered-insufficient" in fired_by_id:
        return "insufficient_underpowered", "non-dependent-underpowered-insufficient"

    # Paralog-buffering veto-suppressor (2026-07-20): a pooled CRISPR non-dependence
    # CONTRADICTED by a measured STRONG paralog buffer (MARK2/3, SMARCA2/4-class). A
    # strong buffer means the single-gene KO is rescued by its paralog — so the pooled
    # non-dependence is a BUFFERING ARTIFACT, not a trusted negative (the target may be
    # a genuine dependency once the paralog is co-inhibited / lost). Like the power-guard
    # above, this is checked BEFORE non-dependent-killer and emits a DISTINCT verdict so
    # the gate's `non_dependent` veto does not fire (auditable: the verdict names the
    # buffering reason, not a bare insufficient). Mirrors the shipped
    # non_dependent_underpowered pattern — measured-vs-null discipline: a strong buffer
    # is a measured reason the pooled negative is untrustworthy. Only `strong` buffering
    # qualifies (partial/none do not rescue the veto). Requires the non-dependent-killer
    # to have fired (a real pooled negative) AND strong paralog buffering.
    if ("non-dependent-killer" in fired_by_id
            and "strong-paralog-buffering-degrader-preferred" in fired_by_id):
        return "non_dependent_paralog_buffered", "strong-paralog-buffering-degrader-preferred"

    # non_dependent → gate VETO. Only CRISPR non-dependence (reliable) qualifies.
    # RNAi non-dependence is NOT included (2026-07-17): rnai-non-dependent-neutral
    # emits `neutral` signals — RNAi is false-negative-prone, so RNAi-alone-not-
    # dependent is absence-of-confirmation, not evidence-against. Collapsing it into
    # `non_dependent` here silently upgraded a neutral signal to a veto. RNAi-only
    # non-dependence now falls through to `insufficient` (honest "not established").
    if "non-dependent-killer" in fired_by_id:
        return "non_dependent", "non-dependent-killer"

    for rid in ("broadly-dependent-neutral", "rnai-broadly-dependent-neutral"):
        if rid in fired_by_id:
            return "broadly_dependent", rid

    return "insufficient", None


def _headline(cards, fired, verdict_pair):
    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    v, drv = verdict_pair or ("insufficient", None)
    return {
        "dependency_verdict":       v,
        "driving_rule_id":          drv,
        "crispr_call":              _get("pan-cancer-crispr-dependency-distribution",
                                          "dependency_class"),
        "rnai_call":                _get("pan-cancer-rnai-dependency-distribution",
                                          "dependency_class"),
        "concordance_call":         _get("crispr-rnai-dependency-concordance",
                                          "concordance_class"),
        "lineage_selectivity":      _get("dependency-lineage-selectivity",
                                          "lineage_selectivity_class"),
        "paralog_buffering_class":  _get("paralog-buffering",
                                          "paralog_buffering_class"),
        "strongest_paralog_symbol": _get("paralog-buffering",
                                          "strongest_paralog_symbol"),
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
