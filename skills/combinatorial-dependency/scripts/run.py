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

from _skills_common.dispatcher import run_wired_skill


SKILL_NAME = "combinatorial-dependency"
SKILL_VERSION = "1.0.0"

CARDS = [
    "combinatorial-dependency",
]

QUESTION = ("When {target} is co-knocked-out with a paralog partner, is there a synthetic-lethal / "
            "buffering genetic interaction, and is it constitutive or context-conditional?")

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


def _headline(cards, fired, verdict_pair):
    def _summary(cid):
        for c in cards:
            if c.get("card_id") == cid:
                return c.get("summary") or {}
        return {}
    s = _summary("combinatorial-dependency")
    verdict, driving = verdict_pair
    return {
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


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="combinatorial_dependency",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
    ))
